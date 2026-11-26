"""Generate SIMULATED metro ridership with a planted, known effect.

Real 2025 Metro ridership was not available, so this project is a simulation
study. This script builds a synthetic world on top of the station list,
gate list and event calendar, and writes data in exactly the format the real
pipeline produces (data/processed/od_hourly/date=YYYY-MM-DD.parquet plus
manifest.csv). Every downstream step then runs as if the data were real.

The ground truth (planted effect, confounders, noise) is in simulation.yaml.
The analysis code never reads that file.

Usage:
    python scripts/simulate_ridership.py                    # full simulated year
    python scripts/simulate_ridership.py --raw-days 2025-01-15 2025-01-18
        # also writes trip-level raw CSVs for those days into data/raw/, to
        # demonstrate the real pipeline (download_and_aggregate.py)
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from calendar_utils import daily_calendar, priced_peak  # noqa: E402
from download_and_aggregate import MANIFEST_FIELDS, write_manifest  # noqa: E402

HOURS = np.arange(24)

# Relative hourly demand by day type (Metro runs ~05:00 to midnight, later on Fri/Sat).
_PROFILES = {
    "work": {5: .5, 6: 2.5, 7: 5, 8: 5.5, 9: 3.5, 10: 2.5, 11: 2.3, 12: 2.4, 13: 2.5,
             14: 2.6, 15: 3, 16: 4, 17: 5.5, 18: 5.5, 19: 4, 20: 3, 21: 2.5, 22: 2,
             23: 1.2},
    "fri": {5: .5, 6: 2.3, 7: 4.6, 8: 5, 9: 3.4, 10: 2.6, 11: 2.4, 12: 1.6, 13: 1.8,
            14: 3, 15: 3.4, 16: 4.2, 17: 5, 18: 5, 19: 4.2, 20: 3.6, 21: 3.2, 22: 2.6,
            23: 2, 0: .9},
    "sat": {5: .3, 6: .8, 7: 1.5, 8: 2, 9: 2.5, 10: 3, 11: 3.3, 12: 3.4, 13: 3.4,
            14: 3.5, 15: 3.7, 16: 3.9, 17: 4, 18: 4, 19: 4, 20: 3.8, 21: 3.2, 22: 2.5,
            23: 1.8, 0: 1},
    "sun": {5: .3, 6: .9, 7: 1.6, 8: 2, 9: 2.4, 10: 2.9, 11: 3.1, 12: 3.2, 13: 3.2,
            14: 3.3, 15: 3.5, 16: 3.7, 17: 3.8, 18: 3.8, 19: 3.6, 20: 3.2, 21: 2.6,
            22: 1.9, 23: 1.1},
    "ramadan_work": {5: .4, 6: 1.5, 7: 2.5, 8: 4, 9: 5, 10: 3, 11: 2.6, 12: 2.6,
                     13: 3, 14: 4.5, 15: 4, 16: 2.5, 17: 1.5, 18: .8, 19: 2, 20: 3.5,
                     21: 4, 22: 4, 23: 3.5, 0: 2},
}
PROFILES = {}
for _k, _v in _PROFILES.items():
    arr = np.array([_v.get(h, 0.0) for h in HOURS])
    PROFILES[_k] = arr / arr.sum()
DAY_SCALE = {"work": 1.0, "fri": 0.95, "sat": 0.72, "sun": 0.62, "holiday": 0.55}
SCHOOL_PEAK_HOURS = np.isin(HOURS, [6, 7, 8, 9, 16, 17, 18, 19])


class World:
    """Fixed, pair-level features of the simulated world."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        st = pd.read_csv(REPO / "data" / "stations.csv")
        lab = pd.read_csv(REPO / "data" / "od_labels.csv")
        w = st.set_index("station")["weight"]
        cbd = st.set_index("station")["cbd"].astype(bool)
        lab["share"] = w[lab.origin].values * w[lab.destination].values / (
            lab.distance_km.values + 2.0)
        lab["share"] /= lab["share"].sum()
        rng = np.random.default_rng([cfg["seed"], 0])
        lab["od_trend"] = rng.normal(0, cfg["od_trend_sd"], len(lab))
        lab["dest_cbd"] = cbd[lab.destination].values
        self.pairs = lab
        out = set(cfg["outage"]["stations"])
        self.outage_mask = (lab.origin.isin(out) | lab.destination.isin(out)).values
        self.cal = daily_calendar(cfg["start"], cfg["end"]).set_index("date")
        self.pricing = pd.Timestamp(cfg["pricing_date"])

    def day_type(self, row) -> str:
        if row.holiday:
            return "holiday"
        return {4: "fri", 5: "sat", 6: "sun"}.get(row.dow, "work")

    def simulate_day(self, day: pd.Timestamp) -> pd.DataFrame:
        cfg, p = self.cfg, self.pairs
        row = self.cal.loc[day]
        rng = np.random.default_rng([cfg["seed"], 1, day.toordinal()])
        kind = self.day_type(row)

        if row.ramadan and kind in ("work", "fri"):
            prof = PROFILES["ramadan_work"].copy()
        else:
            prof = PROFILES["sun" if kind == "holiday" else kind].copy()
        if row.school_holiday and kind in ("work", "fri"):
            prof = np.where(SCHOOL_PEAK_HOURS, prof * (1 + cfg["school_holiday_peak"]), prof)

        t_years = (day - self.pricing).days / 365.25
        doy = day.day_of_year
        summer = 0.5 * (1 + np.cos(2 * np.pi * (doy - 205) / 365.25))
        scale = (DAY_SCALE[kind]
                 * np.exp(cfg["trend_per_year"] * t_years)
                 * (1 - cfg["summer_dip"] * summer)
                 * (1 + (cfg["ramadan_level"] if row.ramadan else 0.0))
                 * np.exp(rng.normal(0, cfg["daily_shock_sd"])))

        # pairs x hours matrix of expected trips
        od = p.share.values * np.exp(p.od_trend.values * t_years) \
            * np.exp(rng.normal(0, cfg["od_day_sd"], len(p)))
        lam = cfg["daily_trips"] * scale * np.outer(od, prof)

        peak = priced_peak(np.array(row.priced_day), np.array(row.ramadan), HOURS)
        toll = p.toll_substituting.values.astype(bool)
        if day >= self.pricing:
            e = cfg["effect"]
            mult = np.where(toll[:, None],
                            np.where(peak[None, :], 1 + e["toll_peak"], 1 + e["toll_offpeak"]),
                            1 + e["control"])
            lam *= mult
        if day >= pd.Timestamp(cfg["new_gates"]["date"]):
            lam[p.crosses_new_gate.values.astype(bool)] *= 1 + cfg["new_gates"]["effect"]
        if day >= pd.Timestamp(cfg["parking"]["date"]):
            lam[np.ix_(p.dest_cbd.values, peak)] *= 1 + cfg["parking"]["effect"]
        if day == pd.Timestamp(cfg["outage"]["date"]):
            lam[self.outage_mask] *= cfg["outage"]["factor"]

        k = cfg["cell_dispersion"]
        lam = lam * rng.gamma(k, 1 / k, lam.shape)
        trips = rng.poisson(lam)

        i, h = np.nonzero(trips)
        df = pd.DataFrame({
            "origin": p.origin.values[i],
            "destination": p.destination.values[i],
            "date": day.date(),
            "hour": h.astype(np.int8),
            "trips": trips[i, h].astype(np.int64),
        })
        # Late-night trips (00:xx) belong to the next calendar date in real data.
        nxt = df.hour == 0
        df.loc[nxt, "date"] = (day + pd.Timedelta(days=1)).date()

        ren = cfg.get("renamed_station")
        if ren and day >= pd.Timestamp(ren["date"]):
            for c in ("origin", "destination"):
                df.loc[df[c] == ren["old"], c] = ren["new"]
        return df


def write_raw_day(df: pd.DataFrame, path: Path, rng: np.random.Generator) -> None:
    """Explode aggregated counts into trip-level rows, in a plausible raw format."""
    rep = df.loc[df.index.repeat(df.trips)].reset_index(drop=True)
    n = len(rep)
    secs = rng.integers(0, 3600, n)
    ts = (pd.to_datetime(rep["date"]) + pd.to_timedelta(rep["hour"].astype(int), unit="h")
          + pd.to_timedelta(secs, unit="s"))
    raw = pd.DataFrame({
        "Transaction Date": ts.dt.strftime("%d/%m/%Y"),
        "Transaction Time": ts.dt.strftime("%H:%M:%S"),
        "Entry Station": rep["origin"],
        "Exit Station": rep["destination"],
        "Mode": "Metro",
        "Card Type": rng.choice(["Silver", "Gold", "Blue", "Red"], n, p=[.7, .05, .2, .05]),
    })
    # Add some tram rows that the pipeline must filter out.
    tram = raw.sample(frac=0.03, random_state=1).assign(
        Mode="Tram", **{"Entry Station": "Tram Stop A", "Exit Station": "Tram Stop B"})
    raw = pd.concat([raw, tram]).sample(frac=1.0, random_state=2)
    raw.to_csv(path, index=False)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=REPO / "simulation.yaml")
    ap.add_argument("--out-dir", type=Path, default=REPO / "data" / "processed")
    ap.add_argument("--raw-days", nargs="*", default=[])
    a = ap.parse_args(argv)

    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))
    world = World(cfg)
    out = a.out_dir / "od_hourly"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    days =pd.date_range(cfg["start"], cfg["end"], freq="D")
    missing = {pd.Timestamp(m) for m in cfg.get("missing_days", [])}
    by_date: dict = {}
    for day in days:
        df = world.simulate_day(day)
        for d, part in df.groupby("date"):
            by_date.setdefault(d, []).append(part)

    manifest = {}
    total = 0
    for day in days:
        key = day.date()
        if day in missing:
            manifest[key.isoformat()] = {"file_date": key.isoformat(), "status": "missing",
                                         "note": "simulated missing file"}
            continue
        parts = by_date.get(key, [])
        df = (pd.concat(parts).groupby(["origin", "destination", "date", "hour"],
                                       as_index=False)["trips"].sum())
        df["hour"] = df["hour"].astype(np.int8)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                       out / f"date={key.isoformat()}.parquet", compression="zstd")
        n = int(df.trips.sum())
        total += n
        manifest[key.isoformat()] = {
            "file_date": key.isoformat(), "status": "ok", "raw_file": "simulated",
            "raw_rows": n, "dropped_null_od": 0, "dropped_bad_time": 0, "dropped_filter": 0,
            "kept_rows": n, "n_od_pairs": int(df[["origin", "destination"]].drop_duplicates()
                                              .shape[0]),
            "total_trips": n, "min_trip_date": key.isoformat(),
            "max_trip_date": key.isoformat(),
            "processed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "note": "SIMULATED DATA",
        }
    assert set(MANIFEST_FIELDS) >= set().union(*[m.keys() for m in manifest.values()])
    write_manifest(a.out_dir, manifest)
    print(f"Simulated {len(days)} days, {total:,} trips -> {out}")

    raw_dir = REPO / "data" / "raw"
    for s in a.raw_days:
        day = pd.Timestamp(s)
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / f"metro_ridership_{day.strftime('%Y%m%d')}.csv"
        write_raw_day(world.simulate_day(day), path,
                      np.random.default_rng([cfg["seed"], 2, day.toordinal()]))
        print(f"Raw demo file: {path}")


if __name__ == "__main__":
    main()
