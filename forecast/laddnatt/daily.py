"""Daglig körning: hämta data, träna, skriv public/forecast_SE3.json."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import sources
from .features import build_training, rows_for_origin, weather_matrices
from .model import PriceModel
from .nights import CHARGE_HOURS, N_NIGHTS, best_window, night_hours


def make_forecast(prices: pd.DataFrame, weather: pd.DataFrame, now: dt.datetime,
                  max_iter: int = 300) -> dict:
    last_known = max(prices.index)
    model = PriceModel(max_iter=max_iter).fit(build_training(prices, weather))
    rows = rows_for_origin(prices, weather_matrices(weather), last_known, with_target=False)
    if rows is None:
        raise RuntimeError("Saknar pris- eller väderdata för de senaste dagarna")
    pred = model.predict(rows)
    fc = {(r.target_date, r.hour): (r.p10, r.p50, r.p90) for r in pred.itertuples()}

    def hour_value(day: dt.date, h: int) -> tuple[float, float, float, bool] | None:
        if day in prices.index:
            v = float(prices.at[day, h])
            return v, v, v, True
        if (day, h) in fc:
            return (*map(float, fc[(day, h)]), False)
        return None

    hours = []
    day = min(now.date(), last_known)
    while (v := hour_value(day, 0)) is not None:
        for h in range(24):
            p10, p50, p90, known = hour_value(day, h)
            hours.append({"date": day.isoformat(), "hour": h, "known": known,
                          "p10": round(p10, 4), "p50": round(p50, 4), "p90": round(p90, 4)})
        day += dt.timedelta(days=1)

    # Första natten börjar i kväll om morgondagens priser finns, annars i går kväll.
    first_evening = last_known - dt.timedelta(days=1)
    nights = []
    for k in range(N_NIGHTS):
        start = first_evening + dt.timedelta(days=k)
        vals = [hour_value(d, h) for d, h in night_hours(start)]
        if any(v is None for v in vals):
            break
        arr = np.array([v[:3] for v in vals])
        cost, i = best_window(arr[:, 1])
        d0, h0 = night_hours(start)[i]
        nights.append({
            "evening": start.isoformat(),
            "known": all(v[3] for v in vals),
            "best_start": f"{d0.isoformat()}T{h0:02d}:00",
            "charge_hours": CHARGE_HOURS,
            "p50": round(cost, 4),
            "p10": round(float(arr[i:i + CHARGE_HOURS, 0].mean()), 4),
            "p90": round(float(arr[i:i + CHARGE_HOURS, 2].mean()), 4),
        })
    return {
        "area": sources.AREA,
        "unit": "SEK/kWh exkl. moms och avgifter",
        "generated": now.isoformat(timespec="seconds"),
        "prices_known_through": last_known.isoformat(),
        "nights": nights,
        "hours": hours,
    }


def append_log(forecast: dict, path: Path) -> None:
    """Sparar dagens prognos så att den senare kan jämföras med verkligt utfall."""
    rows = [{"generated": forecast["generated"][:10], **h} for h in forecast["hours"] if not h["known"]]
    if not rows:
        return
    new = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_csv(path)
        new = pd.concat([old[old["generated"] != new["generated"].iloc[0]], new])
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("public/forecast_SE3.json"))
    a = ap.parse_args()
    now = dt.datetime.now(ZoneInfo(sources.TZ))
    prices = sources.update_prices(a.data / "prices_SE3.csv", now.date())
    weather = sources.update_weather(a.data / "weather.csv", now.date())
    forecast = make_forecast(prices, weather, now)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(forecast, ensure_ascii=False, indent=1), encoding="utf-8")
    append_log(forecast, a.data / "forecast_log.csv")
    for n in forecast["nights"]:
        print(n)


if __name__ == "__main__":
    main()
