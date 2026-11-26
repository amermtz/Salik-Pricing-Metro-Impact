# Did Salik's Peak Pricing Push People onto the Metro?

A causal analysis of Dubai's January 2025 Salik variable toll pricing on Metro
ridership, using difference-in-differences on station-to-station trips.

> **Status: in progress.** Data pipeline built; waiting on data access.
> No results yet. The headline estimate will be reported here with its
> 95% confidence interval, whatever it shows.

## The question

On 31 January 2025 Salik moved to variable pricing: AED 6 per crossing at
weekday peaks (6–10 am, 4–8 pm), AED 4 off-peak and all day Sunday, and free
late at night. Did this shift trips onto the Metro, especially at peak hours and
on routes that would cross a toll gate by car?

This is a cause-and-effect question. "Ridership went up after January" proves
nothing on its own. The design compares routes that substitute for a toll
crossing with routes that don't, and peak with off-peak hours, before and after
the change.

## Method (planned)

1. **Interrupted time series** on total daily ridership.
2. **Difference-in-differences** with an event study: toll-substituting
   origin–destination pairs vs other pairs.
3. **Triple difference**: toll-substituting × weekday peak × after, with
   Sundays and off-peak hours as built-in controls.
4. **Counterfactual forecast check**, used only if it is at least 85% accurate
   on held-out pre-period weeks.
5. **Placebo tests** (fake change date, an outcome that should not move) and
   robustness windows.

Analysis windows are fixed in `config.yaml` and committed before any results
are looked at.

## Data

- RTA Metro ridership (Dubai Pulse), July 2024 – June 2025, aggregated to
  OD pair × date × hour. Raw files are not kept or redistributed.
- RTA Metro stations and Salik toll gate locations (Dubai Pulse).
- `data/events.csv`: holidays, Ramadan, school terms, gate openings, parking
  tariff changes and disruptions, each with its official source.

## Reproduce

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# 1. Inspect one raw file and fill in schema.yaml
python scripts/download_and_aggregate.py inspect data/raw/<one-file>.csv

# 2. Aggregate (resumable; deletes each raw file after processing)
python scripts/download_and_aggregate.py run --start 2024-07-01 --end 2025-06-30

# 3. Data checks -> results/data_checks.md
python scripts/check_data.py --start 2024-07-01 --end 2025-06-30

pytest
```

## Repo layout

```
data/events.csv              hand-built calendar with sources
data/processed/              aggregated parquet + manifest (regenerated if > 20 MB)
scripts/                     download/aggregate and data checks
src/                         labelling and analysis
report/                      memo and figures
results/                     model outputs and check reports
tests/
```

## License

MIT. See `LICENSE`.
