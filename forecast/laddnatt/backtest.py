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
from .features import build_training
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


def run_backtest(prices: pd.DataFrame, weather: pd.DataFrame, test_days: int = 365,
                 folds: int = 4, max_iter: int = 300,
                 fc_weather: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = build_training(prices, weather, fc_weather)
    # Bara dagar där alla sex dagar framåt finns, så att alla sju nätter kan jämföras.
    full = data.groupby("origin")["lead"].nunique()
    data = data[data["origin"].isin(full[full == 6].index)]
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
    weather = sources.update_weather(a.data / "weather.csv")
    pred, nights = run_backtest(prices, weather)
    text = report(pred, nights)
    try:
        fc_weather = sources.update_forecast_weather(a.data / "forecast_weather.csv")
    except Exception as e:  # tjänsten kan vara nere; det ska inte stoppa resten
        text += f"\nKunde inte hämta arkiverade väderprognoser: {e}\n"
    else:
        pred, nights = run_backtest(prices, weather, fc_weather=fc_weather)
        text += "\n" + report(
            pred, nights, title="Test med de väderprognoser som fanns då",
            note="Det här är det ärliga testet: modellen har både tränats och testats med de "
                 "väderprognoser som fanns 2-7 dagar i förväg (data från februari 2024).")
    a.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
