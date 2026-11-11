"""Nattfönster och kostnad per natt.

Natt k räknat från dag D (dagen då notisen skickas): kl. 22-24 dag D+k-1 och
kl. 00-06 dag D+k. Kostnaden för en natt är medelpriset för de billigaste
sammanhängande CHARGE_HOURS timmarna, eftersom laddningen inte behöver hela natten.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

NIGHT_EVENING = [22, 23]
NIGHT_MORNING = [0, 1, 2, 3, 4, 5]
CHARGE_HOURS = 3  # Zoe 41 kWh på 11 kW trefas: ca 20->80 % på under tre timmar
N_NIGHTS = 7


def night_hours(start_day: dt.date) -> list[tuple[dt.date, int]]:
    nxt = start_day + dt.timedelta(days=1)
    return [(start_day, h) for h in NIGHT_EVENING] + [(nxt, h) for h in NIGHT_MORNING]


def best_window(values: np.ndarray, n: int = CHARGE_HOURS) -> tuple[float, int]:
    """(medelpris, startindex) för billigaste sammanhängande n timmar."""
    sums = np.convolve(values, np.ones(n), mode="valid")
    i = int(np.argmin(sums))
    return float(sums[i] / n), i
