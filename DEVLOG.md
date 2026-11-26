# Dev log

## 2026-11-26: Stages 4–5, analysis, memo, automation

The plan (`config.yaml`) was committed in d49e0e3 before any of this ran.

**Analysis** (`src/`): panel builder (OD × date, priced-peak / off-peak /
late-evening slots, aliases and excluded dates from config), DiD, event study
with a cluster-robust joint pre-trend F-test, triple difference, ITS (HAC),
forecast counterfactual, placebos. `src/recovery.py` is the only step that reads
`simulation.yaml`. It runs last and compares every estimate with the truth.

**Results** (truth: +5.0%)
- Headline DiD +5.16% (4.81 to 5.51) ✅. Triple difference +4.80% (4.34 to 5.27) ✅.
- Full year with controls +4.84% ✅. Pre-parking window +5.14% ✅.
- Pre-trends p = 0.976. Placebos p = 0.511 and 0.691. All pass.
- **Counterfactual: accuracy 99.3% (passes the bar), but the estimate is +5.74%
  (5.42 to 6.07), which misses the truth.** Cause: the pre-registered predictors
  have no term for the 24 Nov gate openings, and most of the training data comes
  from before them, so the model under-predicts toll trips afterwards. This is
  reported as it came out. An exploratory run with a gate step gives +5.30%
  (4.94 to 5.66) and confirms the explanation.
- ITS: −0.12% (−2.16 to 1.96). The true effect on all trips is 0.86%, below what
  one aggregate series can detect.
- Naive toll-peak before/after over 4 weeks: +5.17%. That is right by luck,
  because the confounders were quiet around late January. Over the whole year:
  +8.47%. Kept in the memo, since it shows why a control group is needed.
- Exploratory: full year without the new-gate control gives +6.09%, missing the truth.

**Event study note:** week +4 is a single day (28 Feb, the end of the main
window), so its interval is wider.

**Fixes along the way**
- DuckDB 2.0 needs results fully fetched before reusing a connection
  (`fetchall` instead of `fetchone`).
- numpy ints are not JSON-serialisable; cast them explicitly.
- Memo wording: "all checks pass" was too broad while the counterfactual missed
  the truth. The memo now says exactly which estimates recover the effect.

**Memo**: `report/build_memo.py` fills every number from `results/*.json` and
exports a 2-page PDF (xhtml2pdf, since pandoc isn't installed).

**Automation**: `run_all.py` runs every step (about 40 s) and can resume with
`--from`. `.github/workflows/run-study.yml` runs the tests and the full study
on every push and uploads results and the report.

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
