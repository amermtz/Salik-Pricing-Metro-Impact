"""Calendar features and Salik pricing periods, built from data/events.csv.

Salik variable pricing (from 31 Jan 2025), as modelled here:
- Weekday peak, Monday to Saturday: 06:00-10:00 and 16:00-20:00 -> AED 6
- During Ramadan the peak is 09:00-17:00 (Monday to Saturday)
- Off-peak: AED 4. Sundays and public holidays: off-peak all day
- Late night 01:00-06:00: free

The same period definitions are applied before the change, so pre- and
post-period trips are compared like for like.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
EVENTS = REPO / "data" / "events.csv"

PEAK_HOURS = frozenset({6, 7, 8, 9, 16, 17, 18, 19})
RAMADAN_PEAK_HOURS = frozenset(range(9, 17))
LATE_NIGHT_HOURS = frozenset({1, 2, 3, 4, 5})
LATE_EVENING_HOURS = frozenset({20, 21, 22, 23})  # off-peak placebo outcome


def load_events(path: Path = EVENTS) -> pd.DataFrame:
    ev = pd.read_csv(path, parse_dates=["start_date", "end_date"])
    ev["end_date"] = ev["end_date"].fillna(ev["start_date"])
    return ev


def _in_ranges(dates: pd.DatetimeIndex, ev: pd.DataFrame, kind: str) -> np.ndarray:
    out = np.zeros(len(dates), dtype=bool)
    for r in ev[ev.event_type == kind].itertuples():
        out |= (dates >= r.start_date) & (dates <= r.end_date)
    return out


def event_date(ev: pd.DataFrame, kind: str, name_contains: str | None = None) -> pd.Timestamp:
    sub = ev[ev.event_type == kind]
    if name_contains:
        sub = sub[sub.name.str.contains(name_contains, case=False)]
    if sub.empty:
        raise KeyError(f"No {kind} event matching {name_contains!r} in events.csv")
    return sub.start_date.min()


def daily_calendar(start, end, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per date with calendar flags."""
    ev = load_events() if events is None else events
    d = pd.date_range(start, end, freq="D")
    cal = pd.DataFrame({"date": d})
    cal["dow"] = d.day_of_week                    # 0 = Monday ... 6 = Sunday
    cal["holiday"] = _in_ranges(d, ev, "public_holiday")
    cal["ramadan"] = _in_ranges(d, ev, "ramadan")
    cal["school_holiday"] = _in_ranges(d, ev, "school_holiday")
    cal["disruption"] = _in_ranges(d, ev, "disruption")
    # Days on which the peak tariff applies (Mon-Sat, not a public holiday).
    cal["priced_day"] = (cal.dow <= 5) & ~cal.holiday
    return cal


def priced_peak(cal_row_priced_day: np.ndarray, cal_row_ramadan: np.ndarray,
                hour: np.ndarray) -> np.ndarray:
    """Vectorised: is (date, hour) inside a priced peak window?"""
    normal = np.isin(hour, list(PEAK_HOURS))
    ram = np.isin(hour, list(RAMADAN_PEAK_HOURS))
    return cal_row_priced_day & np.where(cal_row_ramadan, ram, normal)
