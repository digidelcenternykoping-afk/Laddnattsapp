"""Test mot historik: hur ofta hade modellen valt rätt natt?

För varje dag D i testperioden (priser kända t.o.m. D+1) jämförs sju nätter.
Modellen väljer den natt som ser billigast ut. Vi mäter vad den natten faktiskt
kostade jämfört med alternativen. Modellen tränas om inför varje testblock och
ser aldrig priser från testblocket eller senare.
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import sources
from .features import HYDRO_COLS, NUCLEAR_COLS, MarketData, build_training
from .daily import load_market
from .model import PriceModel
from .nights import N_NIGHTS, best_window, night_hours


def evaluate_nights(prices: pd.DataFrame, pred: pd.DataFrame) -> pd.DataFrame:
    """En rad per dag D med faktisk kostnad för varje strategi (SEK/kWh)."""
    lookup = pred.set_index(["origin", "target_date", "hour"])["p50"].to_dict()
    rows = []
    for last_known in sorted(pred["origin"].unique()):
        d = last_known - dt.timedelta(days=1)
        actual, model, persist = [], [], []
        ok = True
        for k in range(1, N_NIGHTS + 1):
            hrs = night_hours(d + dt.timedelta(days=k - 1))
            if any(day not in prices.index for day, _ in hrs):
                ok = False
                break
            a = np.array([prices.at[day, h] for day, h in hrs])
            m = np.array([prices.at[day, h] if day <= last_known
                          else lookup.get((last_known, day, h), np.nan) for day, h in hrs])
            p = np.array([prices.at[min(day, last_known), h] for day, h in hrs])
            actual.append(best_window(a)[0])
            model.append(best_window(m)[0])
            persist.append(best_window(p)[0])
        if not ok or np.isnan(model).any():
            continue
        actual = np.array(actual)
        rows.append({
            "date": d,
            "ikvall": actual[0],
            "slump": actual.mean(),
            "samma_som_idag": actual[int(np.argmin(persist))],
            "modell": actual[int(np.argmin(model))],
            "facit": actual.min(),
            "modell_ratt_natt": int(np.argmin(model) == np.argmin(actual)),
            "modell_topp2": int(np.argmin(model) in np.argsort(actual)[:2]),
        })
    return pd.DataFrame(rows)


def prepare(prices: pd.DataFrame, weather: pd.DataFrame,
            fc_weather: pd.DataFrame | None = None, market: MarketData | None = None) -> pd.DataFrame:
    data = build_training(prices, weather, fc_weather, market)
    # Bara dagar där alla sex dagar framåt finns, så att alla sju nätter kan jämföras.
    full = data.groupby("origin")["lead"].nunique()
    return data[data["origin"].isin(full[full == 6].index)]


def run_backtest(prices: pd.DataFrame, weather: pd.DataFrame, test_days: int = 365,
                 folds: int = 4, max_iter: int = 300,
                 fc_weather: pd.DataFrame | None = None, market: MarketData | None = None,
                 data: pd.DataFrame | None = None,
                 exclude: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ger (prognoser, utfall per dag). data kan byggas en gång med prepare() och
    återanvändas; exclude tar bort kolumner så att olika indata kan jämföras på
    exakt samma dagar."""
    if data is None:
        data = prepare(prices, weather, fc_weather, market)
    if exclude:
        data = data.drop(columns=[c for c in exclude if c in data.columns])
    origins = sorted(data["origin"].unique())
    test_origins = origins[-test_days:]
    preds = []
    for block in np.array_split(np.array(test_origins, dtype=object), folds):
        start = block[0]
        # Träna bara på rader vars facit var känt innan testblocket började.
        train = data[data["target_date"] < start]
        model = PriceModel(max_iter=max_iter).fit(train)
        test = data[data["origin"].isin(set(block))]
        p = model.predict(test)
        p["price"] = test["price"].to_numpy()
        preds.append(p)
    pred = pd.concat(preds, ignore_index=True)
    return pred, evaluate_nights(prices, pred)


VARIANTS = {
    "Nuvarande modell": NUCLEAR_COLS + HYDRO_COLS,
    "+ kärnkraft": HYDRO_COLS,
    "+ vattenmagasin": NUCLEAR_COLS,
    "+ kärnkraft och vattenmagasin": [],
}


def summarize(pred: pd.DataFrame, nights: pd.DataFrame, folds: int = 4) -> dict:
    m = nights[["slump", "modell", "facit"]].mean()
    span = m["slump"] - m["facit"]
    cost = nights.sort_values("date")["modell"].to_numpy()
    quarters = [float(b.mean()) for b in np.array_split(cost, folds)]
    return {
        "cost": m["modell"],
        "captured": (m["slump"] - m["modell"]) / span if span > 0 else float("nan"),
        "right": nights["modell_ratt_natt"].mean(),
        "top2": nights["modell_topp2"].mean(),
        "mae": (pred["p50"] - pred["price"]).abs().mean(),
        "mae_far": (pred["p50"] - pred["price"]).abs()[pred["lead"] >= 4].mean(),
        "quarters": quarters,
    }


def compare_report(results: dict[str, dict], period: str) -> str:
    base = results["Nuvarande modell"]
    lines = [
        "# Jämförelse: kärnkraft och vattenmagasin som indata",
        "",
        f"Ärligt test med de väderprognoser som fanns då, samma dagar för alla varianter ({period}).",
        "Kärnkraft: svensk produktion t.o.m. dagen före prognosen (Energy-Charts). "
        "Vattenmagasin: Norges fyllnadsgrad och avvikelse från medianen, "
        "senaste publicerade veckan (NVE).",
        "",
        "| Variant | Medelkostnad | Fångad besparing | Rätt natt | En av två billigaste | Medelfel per timme | Medelfel 5-7 dagar fram |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in results.items():
        lines.append(f"| {name} | {r['cost']:.3f} | {r['captured']:.0%} | {r['right']:.0%} | "
                     f"{r['top2']:.0%} | {r['mae']:.3f} | {r['mae_far']:.3f} |")
    lines += ["", "Medelkostnad per kvartal av testperioden (lägre är bättre):", "",
              "| Variant | " + " | ".join(f"Kvartal {i + 1}" for i in range(len(base["quarters"]))) + " |",
              "|---|" + "---|" * len(base["quarters"])]
    for name, r in results.items():
        lines.append(f"| {name} | " + " | ".join(f"{q:.3f}" for q in r["quarters"]) + " |")
    lines += ["", "En variant räknas som bättre om medelkostnaden blir lägre utan att medelfelet "
                  "per timme blir sämre, och den inte är sämre än nuvarande modell i mer än ett kvartal.", ""]
    for name, r in results.items():
        if name == "Nuvarande modell":
            continue
        worse_q = sum(q > b + 1e-9 for q, b in zip(r["quarters"], base["quarters"]))
        better = r["cost"] < base["cost"] and r["mae"] <= base["mae"] + 1e-9 and worse_q <= 1
        lines.append(f"- {name}: {'bättre' if better else 'inte bättre'} "
                     f"({r['cost'] - base['cost']:+.3f} SEK/kWh, sämre i {worse_q} kvartal).")
    return "\n".join(lines) + "\n"


def report(pred: pd.DataFrame, nights: pd.DataFrame, title: str = "Test mot historik",
           note: str = "Obs: testet använder uppmätt väder i stället för de väderprognoser som fanns då. "
                       "Verklig träffsäkerhet blir därför något sämre, särskilt 4-6 dagar framåt.") -> str:
    m = nights[["ikvall", "slump", "samma_som_idag", "modell", "facit"]].mean()
    span = m["slump"] - m["facit"]
    captured = (m["slump"] - m["modell"]) / span if span > 0 else float("nan")
    captured_p = (m["slump"] - m["samma_som_idag"]) / span if span > 0 else float("nan")
    err = (pred["p50"] - pred["price"]).abs().groupby(pred["lead"]).mean()
    cover = ((pred["price"] >= pred["p10"]) & (pred["price"] <= pred["p90"])).mean()
    lines = [
        f"# {title}",
        "",
        f"Period: {nights['date'].min()} till {nights['date'].max()} ({len(nights)} dagar).",
        "Priser i SEK/kWh exklusive moms och avgifter, billigaste 3 timmarna per natt.",
        "",
        "| Strategi | Medelkostnad |",
        "|---|---|",
        f"| Ladda alltid i kväll | {m['ikvall']:.3f} |",
        f"| Slumpvis natt av sju | {m['slump']:.3f} |",
        f"| Anta att alla dagar blir som i morgon | {m['samma_som_idag']:.3f} |",
        f"| **Modellen** | **{m['modell']:.3f}** |",
        f"| Facit (bästa natten i efterhand) | {m['facit']:.3f} |",
        "",
        f"Modellen fångar {captured:.0%} av den möjliga besparingen (enkla antagandet: {captured_p:.0%}).",
        f"Den valde exakt rätt natt {nights['modell_ratt_natt'].mean():.0%} av dagarna "
        f"och en av de två billigaste {nights['modell_topp2'].mean():.0%}.",
        "",
        "| Dagar framåt | Medelfel per timme |",
        "|---|---|",
        *[f"| {lead + 1} | {e:.3f} |" for lead, e in err.items()],
        "",
        f"Andel timmar där priset hamnade inom intervallet p10-p90: {cover:.0%} (målet är 80 %).",
        "",
        note,
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("backtest.md"))
    a = ap.parse_args()
    prices = sources.update_prices(a.data / "prices_SE3.csv")
    try:
        weather = sources.update_weather(a.data / "weather.csv")
    except RuntimeError as e:
        # Testet behöver bara historiskt väder; de sista dagarna faller bort utan prognos-API:t.
        print(f"Väderprognosen gick inte att hämta, testar med arkivet: {e}")
        weather = sources.update_weather(a.data / "weather.csv", forecast=False)
    pred, nights = run_backtest(prices, weather)
    text = report(pred, nights)
    try:
        fc_weather = sources.update_forecast_weather(a.data / "forecast_weather.csv")
    except Exception as e:  # tjänsten kan vara nere; det ska inte stoppa resten
        text += f"\nKunde inte hämta arkiverade väderprognoser: {e}\n"
    else:
        market = load_market(a.data, use_nuclear=True, use_hydro=True)
        data = prepare(prices, weather, fc_weather, market)
        results = {}
        for name, exclude in VARIANTS.items():
            if any(c not in data.columns for c in set(NUCLEAR_COLS + HYDRO_COLS) - set(exclude)):
                continue  # datakällan gick inte att hämta
            pred, nights = run_backtest(prices, weather, data=data, exclude=exclude)
            results[name] = summarize(pred, nights)
            if name == "Nuvarande modell":
                text += "\n" + report(
                    pred, nights, title="Test med de väderprognoser som fanns då",
                    note="Det här är det ärliga testet: modellen har både tränats och testats med de "
                         "väderprognoser som fanns 2-7 dagar i förväg (data från februari 2024).")
                period = f"{nights['date'].min()} till {nights['date'].max()}"
        if len(results) > 1:
            text += "\n" + compare_report(results, period)
    a.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
