# Dev log

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
