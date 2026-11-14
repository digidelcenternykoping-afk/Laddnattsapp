"""Datahämtning: spotpriser (elprisetjustnu.se) och väder (Open-Meteo).

Allt cachas som CSV i data/ så att den dagliga körningen bara hämtar nya dagar.
"""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

AREA = "SE3"
TZ = "Europe/Stockholm"
FIRST_PRICE_DATE = dt.date(2022, 11, 1)  # elprisetjustnu.se har data härifrån
UA = {"User-Agent": "laddnattsapp-forecast (github.com/digidelcenternykoping-afk/laddnattsapp)"}

# Punkter som representerar vindkraft som påverkar SE3 samt temperatur (förbrukning).
WIND_POINTS = {
    "w_vg": (58.3, 13.0),      # Västergötland (SE3)
    "w_uppl": (60.3, 18.0),    # Upplandskusten (SE3)
    "w_sm": (57.0, 16.3),      # Småland/Kalmar (SE4)
    "w_se2": (63.2, 16.5),     # Västernorrland/Jämtland (SE2)
    "w_fi": (63.0, 22.0),      # Finlands västkust
    "w_dk": (55.0, 9.0),       # Jylland/Nordtyskland
}
TEMP_POINTS = {
    "t_sthlm": (59.33, 18.07),
    "t_gbg": (57.70, 11.97),
}
POINTS = {**WIND_POINTS, **TEMP_POINTS}


def _get(url: str, params: dict | None = None, tries: int = 4) -> requests.Response | None:
    """GET med omförsök. Returnerar None vid 404."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 ** i)
    raise RuntimeError(f"Kunde inte hämta {url}")


# ---------------------------------------------------------------- priser

def parse_price_day(rows: list[dict]) -> pd.Series:
    """En dags JSON (tim- eller kvartsvärden) -> timmedel i SEK/kWh, index 0..23."""
    df = pd.DataFrame(rows)
    t = pd.to_datetime(df["time_start"], utc=True).dt.tz_convert(TZ)
    s = df["SEK_per_kWh"].astype(float).groupby(t.dt.hour.values).mean()
    # Sommartidsbyte: timme 2 saknas på våren. Fyll så att alla dagar har 24 timmar.
    return s.reindex(range(24)).interpolate(limit_direction="both")


def fetch_price_day(day: dt.date) -> pd.Series | None:
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{day:%Y}/{day:%m-%d}_{AREA}.json"
    r = _get(url)
    if r is None:
        return None
    return parse_price_day(r.json())


def update_prices(path: Path, today: dt.date | None = None) -> pd.DataFrame:
    """Uppdaterar pris-cachen. Returnerar DataFrame med index=datum, kolumner 0..23."""
    today = today or dt.datetime.now(tz=dt.timezone.utc).astimezone().date()
    prices = load_prices(path) if path.exists() else pd.DataFrame(columns=range(24), dtype=float)
    have = set(prices.index)
    wanted = [FIRST_PRICE_DATE + dt.timedelta(days=i)
              for i in range((today - FIRST_PRICE_DATE).days + 2)]  # t.o.m. i morgon
    missing = [d for d in wanted if d not in have]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(fetch_price_day, missing))
    new = {d: s for d, s in zip(missing, results) if s is not None}
    if new:
        prices = pd.concat([prices, pd.DataFrame(new).T]).sort_index()
        prices.columns = range(24)
        save_prices(prices, path)
    return prices


def save_prices(prices: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = prices.round(5)
    out.index.name = "date"
    out.to_csv(path)


def load_prices(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col="date")
    df.index = pd.to_datetime(df.index).date
    df.columns = range(24)
    return df


# ---------------------------------------------------------------- väder

def parse_weather(payload: list[dict] | dict) -> pd.DataFrame:
    """Open-Meteo-svar för alla POINTS -> DataFrame index=(date, hour), en kolumn per punkt."""
    if isinstance(payload, dict):
        payload = [payload]
    cols = {}
    for name, loc in zip(POINTS, payload):
        h = loc["hourly"]
        var = "wind_speed_100m" if name.startswith("w_") else "temperature_2m"
        cols[name] = pd.Series(h[var], index=pd.to_datetime(h["time"]), dtype=float)
    df = pd.DataFrame(cols).dropna(how="all")
    out = df.groupby([df.index.date, df.index.hour]).mean()
    out.index.names = ["date", "hour"]
    return out


def _weather_params() -> dict:
    return {
        "latitude": ",".join(str(p[0]) for p in POINTS.values()),
        "longitude": ",".join(str(p[1]) for p in POINTS.values()),
        "hourly": "wind_speed_100m,temperature_2m",
        "wind_speed_unit": "ms",
        "timezone": TZ,
    }


def fetch_weather_archive(start: dt.date, end: dt.date) -> pd.DataFrame:
    r = _get("https://archive-api.open-meteo.com/v1/archive",
             {**_weather_params(), "start_date": start.isoformat(), "end_date": end.isoformat()})
    return parse_weather(r.json())


def fetch_weather_forecast() -> pd.DataFrame:
    r = _get("https://api.open-meteo.com/v1/forecast",
             {**_weather_params(), "past_days": 14, "forecast_days": 16})
    return parse_weather(r.json())


def update_weather(path: Path, today: dt.date | None = None) -> pd.DataFrame:
    """Historik från arkivet (cachas) + de senaste dagarna och prognosen från prognos-API:t."""
    today = today or dt.date.today()
    hist = load_weather(path) if path.exists() else None
    start = FIRST_PRICE_DATE - dt.timedelta(days=10)
    if hist is not None and len(hist):
        start = max(hist.index.get_level_values(0)) + dt.timedelta(days=1)
    end = today - dt.timedelta(days=7)  # arkivet ligger några dagar efter
    if start <= end:
        new = fetch_weather_archive(start, end).dropna()
        hist = new if hist is None else pd.concat([hist, new])
        hist = hist[~hist.index.duplicated(keep="last")].sort_index()
        path.parent.mkdir(parents=True, exist_ok=True)
        hist.round(1).to_csv(path)
    fc = fetch_weather_forecast()
    allw = pd.concat([hist, fc]) if hist is not None else fc
    return allw[~allw.index.duplicated(keep="last")].sort_index()


def load_weather(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index(["date", "hour"])


# ---------------------------------------------------------------- arkiverade väderprognoser

FC_START = dt.date(2024, 2, 1)  # Open-Meteos arkiv över tidigare prognoskörningar börjar i januari 2024
FC_DAYS_AHEAD = range(2, 8)     # prognos gjord 2..7 dagar före måldagen


def parse_forecast_weather(payload: list[dict] | dict) -> pd.DataFrame:
    """Svar från previous-runs-API:t -> index=(days_ahead, date, hour), en kolumn per punkt."""
    if isinstance(payload, dict):
        payload = [payload]
    frames = []
    for k in FC_DAYS_AHEAD:
        cols = {}
        for name, loc in zip(POINTS, payload):
            h = loc["hourly"]
            var = "wind_speed_100m" if name.startswith("w_") else "temperature_2m"
            cols[name] = pd.Series(h[f"{var}_previous_day{k}"], index=pd.to_datetime(h["time"]), dtype=float)
        df = pd.DataFrame(cols).dropna()
        g = df.groupby([df.index.date, df.index.hour]).mean()
        g.index.names = ["date", "hour"]
        frames.append(pd.concat({k: g}, names=["days_ahead"]))
    return pd.concat(frames)


def fetch_forecast_weather(start: dt.date, end: dt.date) -> pd.DataFrame:
    hourly = ",".join(f"{v}_previous_day{k}" for v in ("wind_speed_100m", "temperature_2m")
                      for k in FC_DAYS_AHEAD)
    r = _get("https://previous-runs-api.open-meteo.com/v1/forecast",
             {**_weather_params(), "hourly": hourly,
              "start_date": start.isoformat(), "end_date": end.isoformat()})
    return parse_forecast_weather(r.json())


def update_forecast_weather(path: Path, today: dt.date | None = None) -> pd.DataFrame:
    """Väderprognoser så som de såg ut 2..7 dagar i förväg. Hämtas i block om 90 dagar."""
    today = today or dt.date.today()
    have = None
    start = FC_START
    if path.exists():
        have = pd.read_csv(path)
        have["date"] = pd.to_datetime(have["date"]).dt.date
        have = have.set_index(["days_ahead", "date", "hour"])
        start = max(have.index.get_level_values("date")) + dt.timedelta(days=1)
    end = today - dt.timedelta(days=1)
    parts = [] if have is None else [have]
    while start <= end:
        stop = min(start + dt.timedelta(days=89), end)
        parts.append(fetch_forecast_weather(start, stop))
        start = stop + dt.timedelta(days=1)
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.round(1).to_csv(path)
    return out
