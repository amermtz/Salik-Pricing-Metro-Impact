"""Data checks on the aggregated ridership.

Checks
------
1. Missing days: dates in the range with no processed file (or marked missing/error).
2. Sudden drops or spikes: daily total trips compared with the median of the same
   weekday over the previous 4 weeks. Flags days below 60% or above 150%.
3. Station names: stations that first appear after the start, or disappear before
   the end, of the data. These are often renames and need a mapping.
4. Same-station trips (origin == destination): share of trips, reported.

Writes results/data_checks.md. Copy the findings into DEVLOG.md.

Usage:
    python scripts/check_data.py --start 2024-07-01 --end 2025-06-30
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "data" / "processed"
DEFAULT_REPORT = REPO / "results" / "data_checks.md"

DROP_LOW, DROP_HIGH = 0.60, 1.50


def load_daily(out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (daily totals by trip date, station first/last seen)."""
    glob = str(out_dir / "od_hourly" / "*.parquet").replace("\\", "/")
    con = duckdb.connect()
    try:
        daily = con.execute(
            f"""
            SELECT date, sum(trips) AS trips,
                   sum(trips) FILTER (WHERE origin = destination) AS same_station
            FROM read_parquet('{glob}')
            GROUP BY date ORDER BY date
            """
        ).df()
        stations = con.execute(
            f"""
            WITH s AS (
                SELECT origin AS station, date, trips FROM read_parquet('{glob}')
                UNION ALL
                SELECT destination, date, trips FROM read_parquet('{glob}')
            )
            SELECT station, min(date) AS first_seen, max(date) AS last_seen,
                   count(DISTINCT date) AS n_days, sum(trips) AS trips
            FROM s GROUP BY station ORDER BY station
            """
        ).df()
    finally:
        con.close()
    for df, cols in ((daily, ["date"]), (stations, ["first_seen", "last_seen"])):
        for c in cols:
            df[c] = pd.to_datetime(df[c]).dt.date
    daily["same_station"] = daily["same_station"].fillna(0)
    return daily, stations


def missing_days(manifest: pd.DataFrame, daily: pd.DataFrame,
                 start: dt.date, end: dt.date) -> pd.DataFrame:
    all_days = pd.date_range(start, end, freq="D").date
    status = dict(zip(manifest["file_date"], manifest["status"])) if len(manifest) else {}
    have = set(daily["date"])
    rows = []
    for d in all_days:
        s = status.get(d.isoformat(), "not attempted")
        if d not in have or s != "ok":
            rows.append({"date": d, "manifest_status": s, "has_trips": d in have})
    return pd.DataFrame(rows, columns=["date", "manifest_status", "has_trips"])


def anomalies(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily[["date", "trips"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").asfreq("D")
    ref = []
    for ts in df.index:
        prev = [ts - pd.Timedelta(weeks=k) for k in range(1, 5)]
        vals = df.loc[df.index.intersection(prev), "trips"].dropna()
        ref.append(vals.median() if len(vals) >= 2 else float("nan"))
    df["ref_median"] = ref
    df["ratio"] = df["trips"] / df["ref_median"]
    flag = df[(df["ratio"] < DROP_LOW) | (df["ratio"] > DROP_HIGH)].copy()
    flag["kind"] = flag["ratio"].map(lambda r: "drop" if r < DROP_LOW else "spike")
    flag = flag.reset_index()
    flag["date"] = flag["date"].dt.date
    return flag[["date", "trips", "ref_median", "ratio", "kind"]]


def station_anomalies(out_dir: Path, low: float = 0.5) -> pd.DataFrame:
    """Station-days far below the station's same-weekday median of the previous
    4 weeks. Catches partial outages that barely move the network total."""
    glob = str(out_dir / "od_hourly" / "*.parquet").replace("\\", "/")
    con = duckdb.connect()
    try:
        df = con.execute(
            f"""
            WITH s AS (
                SELECT origin AS station, date, trips FROM read_parquet('{glob}')
                UNION ALL
                SELECT destination, date, trips FROM read_parquet('{glob}')
            ),
            d AS (SELECT station, date, sum(trips) AS trips FROM s GROUP BY ALL),
            r AS (
                SELECT a.station, a.date, a.trips,
                       median(b.trips) AS ref_median, count(b.trips) AS n_ref
                FROM d a JOIN d b
                  ON a.station = b.station
                 AND b.date IN (a.date - INTERVAL 7 DAY, a.date - INTERVAL 14 DAY,
                                a.date - INTERVAL 21 DAY, a.date - INTERVAL 28 DAY)
                GROUP BY ALL
            )
            SELECT date, station, trips, ref_median, trips / ref_median AS ratio
            FROM r WHERE n_ref >= 2 AND trips < {low} * ref_median
            ORDER BY date, station
            """
        ).df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def tag_events(dates: pd.Series, events_path: Path) -> pd.Series:
    """Name any events.csv event covering each date (to explain flagged days)."""
    if not events_path.exists():
        return pd.Series("", index=dates.index)
    ev = pd.read_csv(events_path, parse_dates=["start_date", "end_date"])
    ev["end_date"] = ev["end_date"].fillna(ev["start_date"])

    def names(d):
        t = pd.Timestamp(d)
        hit = ev[(ev.start_date <= t) & (ev.end_date >= t)]
        return "; ".join(hit.name)

    return dates.map(names)


def station_changes(stations: pd.DataFrame, start: dt.date, end: dt.date,
                    slack_days: int = 7) -> pd.DataFrame:
    late = stations["first_seen"] > start + dt.timedelta(days=slack_days)
    early = stations["last_seen"] < end - dt.timedelta(days=slack_days)
    out = stations[late | early].copy()
    out["note"] = ""
    out.loc[late, "note"] += "appears late; "
    out.loc[early, "note"] += "disappears early; "
    return out


def to_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_None._\n"
    return df.to_markdown(index=False, floatfmt=".2f") + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    a = p.parse_args(argv)

    mpath = a.out_dir / "manifest.csv"
    manifest = pd.read_csv(mpath, dtype=str) if mpath.exists() else pd.DataFrame(
        columns=["file_date", "status"])
    daily, stations = load_daily(a.out_dir)

    events_path = REPO / "data" / "events.csv"
    miss = missing_days(manifest, daily, a.start, a.end)
    anom = anomalies(daily)
    anom["events"] = tag_events(anom["date"], events_path)
    st_anom = station_anomalies(a.out_dir)
    chg = station_changes(stations, a.start, a.end)
    # Renamed stations look like a total collapse on the first day; drop those.
    st_anom = st_anom[~st_anom.station.isin(chg.station)]
    st_days = (st_anom.groupby("date")
               .agg(n_stations=("station", "size"),
                    stations=("station", lambda s: ", ".join(sorted(s))),
                    median_ratio=("ratio", "median"))
               .reset_index())
    st_days["events"] = tag_events(st_days["date"], events_path)
    total = daily["trips"].sum()
    same = daily["same_station"].sum()

    a.report.parent.mkdir(parents=True, exist_ok=True)
    text = [
        f"# Data checks ({a.start} to {a.end})\n",
        f"Generated {dt.datetime.now().isoformat(timespec='seconds')}.\n",
        "## Summary\n",
        f"- Days with data: {daily['date'].nunique()} of {(a.end - a.start).days + 1}",
        f"- Total trips: {int(total):,}",
        f"- Stations seen: {len(stations)}",
        f"- Same-station trips: {int(same):,} ({same / total:.2%} of trips)" if total else
        "- Same-station trips: n/a",
        f"- Missing or failed days: {len(miss)}",
        f"- Flagged network drops/spikes: {len(anom)} "
        f"({(anom['events'] == '').sum()} not explained by events.csv)",
        f"- Days with station-level drops (<50%): {len(st_days)} "
        f"({(st_days['events'] == '').sum()} not explained by events.csv)",
        f"- Stations appearing late or disappearing early: {len(chg)}\n",
        "## 1. Missing days\n", to_md(miss),
        f"## 2. Drops and spikes (vs same-weekday median of previous 4 weeks; "
        f"<{DROP_LOW:.0%} or >{DROP_HIGH:.0%})\n",
        "Check each against events.csv (holidays, Ramadan, disruptions) before "
        "deciding whether to exclude it.\n",
        to_md(anom),
        "## 3. Station-level drops (station below 50% of its same-weekday median)\n",
        "Partial outages can hide in the network total. One row per day.\n",
        to_md(st_days),
        "## 4. Station name changes (possible renames)\n", to_md(chg),
    ]
    a.report.write_text("\n".join(text), encoding="utf-8")
    print("\n".join(text[:12]))
    print(f"\nFull report: {a.report}")


if __name__ == "__main__":
    main()
