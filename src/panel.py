"""Build analysis panels from the aggregated OD x date x hour parquet.

Applies the cleaning in config.yaml (station aliases, excluded dates), joins
the toll-substituting labels and the calendar, and splits each day's trips into
Salik pricing slots:

    peak        priced weekday peak (Mon-Sat 06-10, 16-20; Ramadan 09-17)
    offpeak     every other hour
    late_eve    priced days, 20:00-23:59 (a subset of offpeak; placebo outcome)

The panel is balanced: every OD pair has a row for every date (zeros filled).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from calendar_utils import (LATE_EVENING_HOURS, PEAK_HOURS, RAMADAN_PEAK_HOURS,
                            daily_calendar, load_events)

REPO = Path(__file__).resolve().parents[1]
PROCESSED = REPO / "data" / "processed" / "od_hourly"


def load_config(path: Path = REPO / "config.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _hours_sql(hours) -> str:
    return "(" + ", ".join(str(h) for h in sorted(hours)) + ")"


@lru_cache(maxsize=2)
def daily_od_panel(config_path: str = str(REPO / "config.yaml")) -> pd.DataFrame:
    """OD x date panel over the full data range, with slot trip counts and flags."""
    cfg = load_config(Path(config_path))
    clean = cfg.get("cleaning", {})
    aliases = clean.get("station_aliases", {}) or {}
    exclude = [pd.Timestamp(d) for d in clean.get("exclude_dates", []) or []]

    glob = str(PROCESSED / "*.parquet").replace("\\", "/")
    con = duckdb.connect()
    try:
        span = con.execute(
            f"SELECT min(date), max(date) FROM read_parquet('{glob}')").fetchall()[0]
        cal = daily_calendar(span[0], span[1])
        con.register("cal", cal[["date", "priced_day", "ramadan"]])
        alias = pd.DataFrame({"old": list(aliases), "new": list(aliases.values())},
                             columns=["old", "new"]).astype(str)
        con.register("alias", alias)
        df = con.execute(
            f"""
            WITH h AS (
                SELECT COALESCE(ao.new, t.origin) AS origin,
                       COALESCE(ad.new, t.destination) AS destination,
                       CAST(t.date AS DATE) AS date, t.hour, t.trips
                FROM read_parquet('{glob}') t
                LEFT JOIN alias ao ON t.origin = ao.old
                LEFT JOIN alias ad ON t.destination = ad.old
            )
            SELECT h.origin, h.destination, h.date,
                SUM(trips) FILTER (WHERE c.priced_day AND (
                    (NOT c.ramadan AND hour IN {_hours_sql(PEAK_HOURS)}) OR
                    (c.ramadan AND hour IN {_hours_sql(RAMADAN_PEAK_HOURS)})))  AS peak,
                SUM(trips) AS total,
                SUM(trips) FILTER (WHERE c.priced_day AND hour IN
                                   {_hours_sql(LATE_EVENING_HOURS)})               AS late_eve
            FROM h JOIN cal c ON h.date = CAST(c.date AS DATE)
            GROUP BY ALL
            """
        ).df()
    finally:
        con.close()

    for c in ("peak", "total", "late_eve"):
        df[c] = df[c].fillna(0).astype(np.int64)
    df["offpeak"] = df["total"] - df["peak"]
    df["date"] = pd.to_datetime(df["date"])

    # Balanced grid: every pair x every date that has data
    dates = np.sort(df["date"].unique())
    dates = dates[~np.isin(dates, np.array(exclude, dtype="datetime64[ns]"))]
    labels = pd.read_csv(REPO / "data" / "od_labels.csv")
    grid = labels[["origin", "destination"]].merge(pd.DataFrame({"date": dates}), how="cross")
    df = grid.merge(df, on=["origin", "destination", "date"], how="left")
    for c in ("peak", "total", "late_eve", "offpeak"):
        df[c] = df[c].fillna(0).astype(np.int64)

    df = df.merge(labels[["origin", "destination", "toll_substituting", "crosses_new_gate"]],
                  on=["origin", "destination"])
    df = df.merge(cal, on="date", how="left")
    df["od"] = df["origin"] + " > " + df["destination"]
    stations = pd.read_csv(REPO / "data" / "stations.csv")
    cbd = set(stations.loc[stations.cbd == 1, "station"])
    df["dest_cbd"] = df["destination"].isin(cbd).astype(int)

    ev = load_events()
    treat = pd.Timestamp(cfg["treatment_date"])
    gate_open = ev.loc[ev.event_type == "gate_opening", "start_date"].min()
    parking = ev.loc[ev.event_type == "parking", "start_date"].min()
    df["post"] = (df["date"] >= treat).astype(int)
    df["toll"] = df["toll_substituting"].astype(int)
    df["new_gate_post"] = ((df["date"] >= gate_open) & (df["crosses_new_gate"] == 1)).astype(int)
    df["parking_post"] = (df["date"] >= parking).astype(int)
    for c in ("holiday", "ramadan", "school_holiday", "priced_day", "disruption"):
        df[c] = df[c].astype(int)
    return df.sort_values(["od", "date"]).reset_index(drop=True)


def window(df: pd.DataFrame, win: dict) -> pd.DataFrame:
    s, e = pd.Timestamp(win["start"]), pd.Timestamp(win["end"])
    return df[(df["date"] >= s) & (df["date"] <= e)].copy()


def slot_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Long format: one row per OD x date x slot (peak / offpeak), priced days only
    for the peak slot. Non-priced days (Sundays, holidays) contribute all their
    trips to the offpeak slot, which is what makes them built-in controls."""
    pk = df[df.priced_day == 1].assign(slot="peak", trips=lambda d: d["peak"])
    op = df.assign(slot="offpeak", trips=lambda d: d["offpeak"])
    out = pd.concat([pk, op], ignore_index=True)
    out["is_peak"] = (out["slot"] == "peak").astype(int)
    out["y"] = np.log1p(out["trips"])
    return out
