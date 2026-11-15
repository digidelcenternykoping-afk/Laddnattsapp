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


def synthetic_forecast_weather(w, seed=2):
    """Väderprognoser = uppmätt väder plus brus som växer med antal dagar framåt."""
    rng = np.random.default_rng(seed)
    parts = {k: w + rng.normal(0, 0.4 * k, w.shape) for k in sources.FC_DAYS_AHEAD}
    return pd.concat(parts, names=["days_ahead"])


def test_parse_forecast_weather():
    times = [f"2025-01-01T{h:02d}:00" for h in range(24)]
    hourly = {"time": times}
    for k in sources.FC_DAYS_AHEAD:
        hourly[f"wind_speed_100m_previous_day{k}"] = [float(k)] * 24
        hourly[f"temperature_2m_previous_day{k}"] = [-float(k)] * 24
    fw = sources.parse_forecast_weather([{"hourly": hourly} for _ in sources.POINTS])
    assert fw.loc[(3, dt.date(2025, 1, 1), 5), "w_vg"] == 3.0
    assert fw.loc[(7, dt.date(2025, 1, 1), 5), "t_gbg"] == -7.0


def test_training_uses_forecast_weather_for_target_day():
    prices, w = synthetic(60)
    fw = synthetic_forecast_weather(w)
    a = build_training(prices, w)
    b = build_training(prices, w, fw)
    assert len(a) == len(b)
    assert not np.allclose(a["wind"], b["wind"])          # måldagens väder skiljer sig
    assert np.allclose(a["hist_windpow"], b["hist_windpow"])  # historiken är uppmätt


def test_backtest_with_forecast_weather():
    prices, w = synthetic()
    pred, nights = run_backtest(prices, w, test_days=120, folds=2, max_iter=80,
                                fc_weather=synthetic_forecast_weather(w))
    m = nights.mean(numeric_only=True)
    assert len(nights) > 100
    assert m["facit"] <= m["modell"] < m["slump"]


# ---------------------------------------------------------------- kärnkraft och vattenmagasin

from laddnatt.backtest import VARIANTS, compare_report, prepare, summarize  # noqa: E402
from laddnatt.features import HYDRO_COLS, NUCLEAR_COLS, MarketData  # noqa: E402


def test_parse_nuclear_v1_and_v2():
    t = pd.date_range("2025-01-01", periods=48, freq="h", tz="Europe/Stockholm")
    v1 = {"unix_seconds": [int(x.timestamp()) for x in t],
          "production_types": [{"name": "Wind onshore", "data": [1.0] * 48},
                               {"name": "Nuclear", "data": [6000.0] * 24 + [5000.0] * 12 + [None] * 12}]}
    s = sources.parse_nuclear(v1)
    assert s[dt.date(2025, 1, 1)] == 6000.0
    assert dt.date(2025, 1, 2) not in s.index  # halva dygnet saknas
    v2 = {"series": [{"id": "nuclear", "name": "Nuclear"}],
          "data": [{"timestamp": x.isoformat(), "values": {"nuclear": 4000.0}} for x in t]}
    s2 = sources.parse_nuclear(v2)
    assert list(s2) == [4000.0, 4000.0]


def test_parse_hydro():
    data = [{"omrType": "NO", "omrnr": 0, "iso_aar": 2025, "iso_uke": w, "fyllingsgrad": 0.5 + w / 100}
            for w in (1, 2)] + [{"omrType": "EL", "omrnr": 1, "iso_aar": 2025, "iso_uke": 1, "fyllingsgrad": 0.1}]
    median = [{"omrType": "NO", "omrnr": 0, "iso_uke": w, "medianFyllingsGrad": 0.5} for w in (1, 2)]
    h = sources.parse_hydro(data, median)
    assert len(h) == 2 and h["fill"].tolist() == [0.51, 0.52] and h["median"].tolist() == [0.5, 0.5]


def test_market_data_uses_only_what_was_known():
    d0 = dt.date(2025, 1, 1)
    nuclear = pd.Series({d0 + dt.timedelta(days=i): 1000.0 * i for i in range(30)})
    hydro = pd.DataFrame({"iso_year": [2025] * 3, "iso_week": [1, 2, 3],
                          "fill": [0.6, 0.55, 0.5], "median": [0.6, 0.6, 0.6]})
    m = MarketData(nuclear, hydro)
    run_day = dt.date(2025, 1, 20)  # måndag vecka 4
    f = m.features(run_day)
    assert f["nuc_gw"] == 18.0  # gårdagens dygn, inte dagens
    # Vecka 3 slutar söndag 19 januari och räknas som känd först torsdag 23 januari.
    assert f["hydro_fill"] == 0.55 and abs(f["hydro_change"] + 0.05) < 1e-9
    assert m.features(dt.date(2025, 1, 23))["hydro_fill"] == 0.5
    assert np.isnan(MarketData(nuclear, hydro).features(dt.date(2025, 3, 1))["nuc_gw"])


def synthetic_market(prices, seed=3):
    """Kärnkraft som ibland står still i flera veckor och då höjer priset."""
    rng = np.random.default_rng(seed)
    days = sorted(prices.index)
    nuc = np.full(len(days), 6500.0)
    for start in rng.choice(len(days) - 40, 6, replace=False):
        nuc[start:start + 25] -= 2500
    nuclear = pd.Series(nuc + rng.normal(0, 100, len(days)), index=days)
    p = prices.copy()
    for i, d in enumerate(days):
        if i >= 1:
            p.loc[d] += 0.0001 * (6500 - nuc[i - 1])
    weeks = sorted({d.isocalendar()[:2] for d in days})
    hydro = pd.DataFrame({"iso_year": [y for y, _ in weeks], "iso_week": [w for _, w in weeks],
                          "fill": 0.6 + 0.1 * np.sin(np.arange(len(weeks)) / 8), "median": 0.6})
    return p, MarketData(nuclear, hydro)


def test_backtest_compares_variants_on_same_days():
    prices, w = synthetic()
    prices, market = synthetic_market(prices)
    data = prepare(prices, w, market=market)
    assert set(NUCLEAR_COLS + HYDRO_COLS) <= set(data.columns)
    results = {}
    for name, exclude in VARIANTS.items():
        pred, nights = run_backtest(prices, w, test_days=120, folds=2, max_iter=80,
                                    data=data, exclude=exclude)
        results[name] = summarize(pred, nights, folds=2)
        results[name]["days"] = len(nights)
    assert len({r["days"] for r in results.values()}) == 1
    # Priserna beror på kärnkraften här, så den ska hjälpa.
    assert results["+ kärnkraft"]["mae"] < results["Nuvarande modell"]["mae"]
    assert "Nuvarande modell" in compare_report(results, "test")


def test_daily_forecast_with_market_keeps_format():
    prices, w = synthetic(200)
    prices, market = synthetic_market(prices)
    last = max(prices.index)
    now = dt.datetime.combine(last - dt.timedelta(days=1), dt.time(13, 40))
    plain = make_forecast(prices, w, now, max_iter=40)
    fc = make_forecast(prices, w, now, max_iter=40, market=market)
    assert fc.keys() == plain.keys()
    assert [n.keys() for n in fc["nights"]] == [n.keys() for n in plain["nights"]]
    assert [h.keys() for h in fc["hours"]] == [h.keys() for h in plain["hours"]]
    assert len(fc["nights"]) == 7


def test_daily_forecast_without_recent_market_values():
    prices, w = synthetic(200)
    _, market = synthetic_market(prices)
    last = max(prices.index)
    old = {d: v for d, v in market.nuclear.items() if d < last - dt.timedelta(days=20)}
    stale = MarketData(pd.Series(old), market.hydro[["iso_year", "iso_week", "fill", "median"]])
    now = dt.datetime.combine(last - dt.timedelta(days=1), dt.time(13, 40))
    fc = make_forecast(prices, w, now, max_iter=40, market=stale)
    assert len(fc["nights"]) == 7
