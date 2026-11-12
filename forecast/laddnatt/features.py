"""Bygger träningsrader och prognosrader.

Vid prognostillfället är priserna kända t.o.m. dag L (i morgon, när körningen sker
efter kl. 13). Vi förutspår dag L+1 .. L+6 ("lead" 1..6), timme för timme.

Målvariabeln är skillnaden mot senaste veckans prisnivå för samma timme. Då behöver
modellen bara lära sig hur vind, temperatur och veckodag flyttar priset relativt
nivån just nu, och den klarar perioder med annan prisnivå än i träningsdatat.
"""
from __future__ import annotations

import datetime as dt

import holidays
import numpy as np
import pandas as pd

from .sources import TEMP_POINTS, WIND_POINTS

LEADS = range(1, 7)
LEVEL_DAYS = 8  # dagar bakåt (inkl. L) som beskriver "prisnivån just nu"
_SE_HOLIDAYS = holidays.Sweden(include_sundays=False)


def is_free_day(d: dt.date) -> int:
    return int(d.weekday() >= 5 or d in _SE_HOLIDAYS)


def weather_matrices(weather: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per variabel: DataFrame index=datum, kolumner 0..23."""
    w = weather.copy()
    w["wind"] = w[list(WIND_POINTS)].mean(axis=1)
    # Vindkraftens effekt växer ungefär med vindhastigheten i kubik upp till märkeffekt.
    w["windpow"] = (w[list(WIND_POINTS)].clip(upper=12) ** 3).mean(axis=1) / 12 ** 3
    w["temp"] = w[list(TEMP_POINTS)].mean(axis=1)
    out = {}
    for c in ["wind", "windpow", "temp", *WIND_POINTS]:
        out[c] = w[c].unstack("hour").reindex(columns=range(24)).interpolate(axis=1, limit_direction="both")
    return out


def forecast_matrices(fc_weather: pd.DataFrame) -> dict[int, dict[str, pd.DataFrame]]:
    """Arkiverade väderprognoser -> väder-matriser per lead.

    Körningen sker dagen före last_known, så måldagen last_known+lead ligger
    lead+1 dagar fram från den väderprognos som fanns då.
    """
    return {k - 1: weather_matrices(fc_weather.xs(k, level="days_ahead"))
            for k in fc_weather.index.get_level_values("days_ahead").unique()}


def rows_for_origin(prices: pd.DataFrame, wm: dict[str, pd.DataFrame], last_known: dt.date,
                    with_target: bool,
                    wm_lead: dict[int, dict[str, pd.DataFrame]] | None = None) -> pd.DataFrame | None:
    """Rader för alla leads och timmar givet att priser är kända t.o.m. last_known.

    wm är uppmätt väder (används för de senaste dagarna). Om wm_lead anges tas
    måldagens väder i stället från den prognos som fanns vid tillfället.
    """
    hist_days = [last_known - dt.timedelta(days=i) for i in range(LEVEL_DAYS)]
    if any(d not in prices.index for d in hist_days) or any(d not in wm["wind"].index for d in hist_days):
        return None
    ph = prices.loc[hist_days].to_numpy(dtype=float)  # [0] = last_known
    level_hour = ph.mean(axis=0)                      # nivå per timme
    base = {
        "level_day": ph.mean(),
        "level_std": ph.std(),
        "last_day_mean": ph[0].mean(),
        "last_day_vs_level": ph[0].mean() - ph.mean(),
        "hist_windpow": wm["windpow"].loc[hist_days].to_numpy().mean(),
        "hist_temp": wm["temp"].loc[hist_days].to_numpy().mean(),
        "hist_free_share": np.mean([is_free_day(d) for d in hist_days]),
    }
    frames = []
    for lead in LEADS:
        t = last_known + dt.timedelta(days=lead)
        tw = wm if wm_lead is None else wm_lead.get(lead)
        if tw is None or t not in tw["wind"].index:
            continue
        if with_target and t not in prices.index:
            continue
        f = pd.DataFrame({"hour": np.arange(24)})
        f["origin"] = last_known
        f["target_date"] = t
        f["lead"] = lead
        f["dow"] = t.weekday()
        f["free_day"] = is_free_day(t)
        doy = t.timetuple().tm_yday
        f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
        for k, v in base.items():
            f[k] = v
        f["level_hour"] = level_hour
        f["last_same_hour"] = ph[0]
        for c in ["wind", "windpow", "temp", *WIND_POINTS]:
            f[c] = tw[c].loc[t].to_numpy()
        f["windpow_day"] = f["windpow"].mean()
        f["temp_day"] = f["temp"].mean()
        f["windpow_vs_hist"] = f["windpow"] - base["hist_windpow"]
        f["temp_vs_hist"] = f["temp"] - base["hist_temp"]
        if with_target:
            f["price"] = prices.loc[t].to_numpy(dtype=float)
            f["y"] = f["price"] - f["level_hour"]
        frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else None


def build_training(prices: pd.DataFrame, weather: pd.DataFrame,
                   fc_weather: pd.DataFrame | None = None) -> pd.DataFrame:
    wm = weather_matrices(weather)
    wm_lead = forecast_matrices(fc_weather) if fc_weather is not None else None
    frames = [r for d in prices.index
              if (r := rows_for_origin(prices, wm, d, with_target=True, wm_lead=wm_lead)) is not None]
    return pd.concat(frames, ignore_index=True)


META = ["origin", "target_date", "price", "y"]


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META]
