# Dev log

## 2026-11-26: Switch to a simulation study; Stages 1–3

**Why:** Dubai Pulse has no 2025 Metro ridership, so the real study cannot run.
Rather than drop the project, it becomes a simulation study: a synthetic year
with a known planted effect, used to test whether the designs recover it. The
data is labelled as simulated everywhere, and no result is presented as a
real-world finding.

**Simulated world** (`simulation.yaml`, `scripts/simulate_ridership.py`)
- 36 stations (Red and Green Line subset, approximate coordinates), 1,260 ordered pairs.
- Demand: gravity model (station weights / distance), hourly profiles by day
  type (workday, Friday, Saturday, Sunday/holiday, Ramadan), growth trend,
  summer dip, day shocks, pair-level drift, over-dispersed Poisson counts.
- **Planted effect:** +5% on toll-substituting pairs at priced peak hours from
  2025-01-31. Zero elsewhere.
- **Traps:** new gates (+3% on pairs crossing them, from 2024-11-24), parking
  tariff (+4% at peak into CBD stations, from 2025-04-04), Ramadan, school holidays.
- **Data problems:** missing day 2024-07-23, south Red Line outage 2024-10-15,
  station rename Sharaf DG -> Sharaf DG Metro from 2025-05-01.
- Output: 365 days, 134.4M trips, 8.5 MB parquet (kept out of git; it is
  regenerated from the seed in about 15 s).

**Pipeline check:** generated a trip-level raw CSV for 2025-01-15 (with tram rows
and dd/mm/yyyy dates) and ran the real pipeline on it. Result: 420,630 trips and
0 mismatched cells against the simulator. The 12,619 tram rows were filtered and
the raw file was deleted.

**Data checks** found every planted problem:
- the missing day;
- 7 network drops, all public holidays (tagged from events.csv);
- the rename (Sharaf DG disappears 2025-04-30, Sharaf DG Metro appears 2025-05-01).
- The outage was **missed** at first: only 8 stations dropped, so the network
  total stayed above the 60% threshold. A station-level check now flags it
  (8 stations at 26% of normal).

**Labels** (`src/label_od_pairs.py`): first run had the Jebel Ali gate off the
road line (4 pairs crossed it) and 1.5 km screen lines that missed long
diagonal trips. I moved Jebel Ali onto the DMCC–UAE Exchange line and made the
Sheikh Zayed Road screen lines 3 km long. Result: 674 of 1,260 pairs are
toll-substituting, and 402 cross a gate that opened in late 2024.
For review: long diagonals such as UAE Exchange to Etisalat stay control.

**Analysis plan** (`config.yaml`), written before any analysis:
- Main window: 2024-12-01 to 2025-02-28 (after the new gates, before Ramadan).
- Robustness windows: the full year with controls, and a window that ends
  before the parking change.
- Headline: DiD on priced-peak trips, main window, pair and date fixed
  effects, clustered by pair.
- Thresholds: pre-trends p > 0.10, placebo p > 0.05, counterfactual MAPE <= 15%.
- Cleaning: merge the rename and drop the outage day. Both were decided from
  the data checks, not from any outcome.

## 2026-11-26: Stage 1 pipeline

**Done**
- Set up the repo structure and environment (Python 3.12).
- Wrote `scripts/download_and_aggregate.py`:
  - Processes one day at a time to OD pair × date × hour trip counts in Parquet
    (`data/processed/od_hourly/date=YYYY-MM-DD.parquet`).
  - Resumable: skips days already marked `ok` in `data/processed/manifest.csv`.
  - Works on hand-downloaded files in `data/raw/` or a URL template.
  - Deletes the raw file after a successful day.
  - Per-day manifest: raw rows, rows dropped (null station, bad time, filter),
    OD pairs, total trips.
- Wrote `scripts/check_data.py`: missing days, drops/spikes vs the same weekday
  over the previous 4 weeks, stations that appear or disappear (possible renames),
  share of same-station trips.

**Decisions**
- **Raw columns are read as text, and dates are parsed with explicit formats.**
  A test showed DuckDB's type auto-detection read `03/02/2025` as a date before
  the configured format was applied, so every row was dropped. On real data it
  could also silently swap day and month. The formats now go in `schema.yaml`.
- **Bad days are not marked ok.** A day with zero usable trips is `error`. A day
  with more than 5% of rows dropped is `suspect`. In both cases the raw file is
  kept and the day is retried on the next run.
- Trips are bucketed by the calendar date and hour of the timestamp. Trips after
  midnight count on the next calendar day. Revisit if the analysis needs
  "service day".

**Open questions**
- Exact raw schema: unknown until data access.
- Does the ridership file include non-metro modes? If so, set `row_filter`.
- Dubai Pulse licence terms for publishing aggregated data.
