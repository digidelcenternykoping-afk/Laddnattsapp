import datetime as dt

import numpy as np
import pandas as pd

from laddnatt import sources
from laddnatt.backtest import report, run_backtest
from laddnatt.daily import append_log, make_forecast
from laddnatt.features import build_training, is_free_day
from laddnatt.nights import best_window, night_hours


def synthetic(days=420, seed=1):
    """Priser som beror på vind, temperatur, veckodag och timme, plus brus och nivådrift."""
    rng = np.random.default_rng(seed)
    start = dt.date(2024, 1, 1)
    dates = [start + dt.timedelta(days=i) for i in range(days + 20)]
    n = len(dates)
    wind_day = np.clip(7 + 3 * np.sin(np.arange(n) / 2.3) + rng.normal(0, 2, n), 0.5, 20)
    temp_day = 5 - 10 * np.cos(2 * np.pi * np.arange(n) / 365) + rng.normal(0, 2, n)
    idx = pd.MultiIndex.from_product([dates, range(24)], names=["date", "hour"])
    w = pd.DataFrame(index=idx)
    for c in sources.WIND_POINTS:
        w[c] = np.clip(np.repeat(wind_day, 24) + rng.normal(0, 1, n * 24), 0, None)
    for c in sources.TEMP_POINTS:
        w[c] = np.repeat(temp_day, 24) + rng.normal(0, 1, n * 24)
    level = 0.5 + 0.2 * np.sin(np.arange(n) / 60)
    hour_shape = 0.15 * np.sin((np.arange(24) - 8) / 24 * 2 * np.pi)
    rows = {}
    for i, d in enumerate(dates[:days]):
        p = (level[i] - 0.05 * (wind_day[i] - 7) - 0.01 * (temp_day[i] - 5)
             - 0.1 * is_free_day(d) + hour_shape + rng.normal(0, 0.03, 24))
        rows[d] = p
    prices = pd.DataFrame(rows).T
    prices.columns = range(24)
    return prices, w


def test_parse_quarter_hour_prices():
    t0 = pd.Timestamp("2025-11-10T00:00:00+01:00")
    rows = [{"SEK_per_kWh": 1.0 + (i // 4), "time_start": (t0 + pd.Timedelta(minutes=15 * i)).isoformat()}
            for i in range(96)]
    s = sources.parse_price_day(rows)
    assert list(s.index) == list(range(24))
    assert s[0] == 1.0 and s[23] == 24.0


def test_parse_prices_dst_spring_has_24_hours():
    # 2025-03-30: timme 02 finns inte.
    times = pd.date_range("2025-03-30", "2025-03-31", freq="h", tz="Europe/Stockholm", inclusive="left")
    rows = [{"SEK_per_kWh": 1.0, "time_start": t.isoformat()} for t in times]
    assert len(rows) == 23
    s = sources.parse_price_day(rows)
    assert len(s) == 24 and not s.isna().any()


def test_parse_weather():
    times = [f"2025-01-01T{h:02d}:00" for h in range(24)]
    payload = [{"hourly": {"time": times, "wind_speed_100m": [5.0] * 24, "temperature_2m": [-3.0] * 24}}
               for _ in sources.POINTS]
    w = sources.parse_weather(payload)
    assert w.shape == (24, len(sources.POINTS))
    assert w["w_vg"].iloc[0] == 5.0 and w["t_sthlm"].iloc[0] == -3.0


def test_best_window_and_night_hours():
    cost, i = best_window(np.array([5, 4, 1, 1, 1, 6, 7, 8.0]))
    assert (cost, i) == (1.0, 2)
    hrs = night_hours(dt.date(2025, 1, 1))
    assert hrs[0] == (dt.date(2025, 1, 1), 22) and hrs[-1] == (dt.date(2025, 1, 2), 5)


def test_training_has_no_future_prices():
    prices, w = synthetic(60)
    data = build_training(prices, w)
    assert (data["target_date"] > data["origin"]).all()
    assert set(data["lead"]) == set(range(1, 7))


def test_backtest_beats_random_on_synthetic_data():
    prices, w = synthetic()
    pred, nights = run_backtest(prices, w, test_days=120, folds=2, max_iter=80)
    m = nights.mean(numeric_only=True)
    assert m["facit"] <= m["modell"] < m["slump"]
    assert "Modellen" in report(pred, nights)


def test_daily_forecast_json(tmp_path):
    prices, w = synthetic(200)
    last = max(prices.index)
    now = dt.datetime.combine(last - dt.timedelta(days=1), dt.time(13, 40))
    fc = make_forecast(prices, w, now, max_iter=40)
    assert fc["prices_known_through"] == last.isoformat()
    assert len(fc["nights"]) == 7
    assert now.date().isoformat() in fc["daily_temp"]
    assert fc["nights"][0]["known"] and not fc["nights"][-1]["known"]
    assert fc["nights"][0]["evening"] == (last - dt.timedelta(days=1)).isoformat()
    unknown = [h for h in fc["hours"] if not h["known"]]
    assert len(unknown) == 6 * 24
    assert all(h["p10"] <= h["p50"] <= h["p90"] for h in unknown)
    log = tmp_path / "log.csv"
    append_log(fc, log)
    append_log(fc, log)  # samma dag två gånger ska inte ge dubbletter
    assert len(pd.read_csv(log)) == 6 * 24
