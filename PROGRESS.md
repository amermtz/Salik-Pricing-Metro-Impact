# Progress

_Last updated: 2026-11-26_

## Current stage
**Stage 3 done: analysis plan written in `config.yaml`.** It must be committed
on its own before Stage 4 starts.

## Key decision
Real 2025 Metro ridership is not available on Dubai Pulse, so the project is a
**simulation study**: synthetic data with a planted +5% effect, and a test of
whether the methods recover it. This is stated in the README, the memo and the
CV bullet.

## Done
- [x] Stage 1: repo, resumable pipeline, data checks, simulator
  - 365 simulated days, 134.4M trips, 8.5 MB of parquet
  - The pipeline reproduces the simulator's counts exactly on a trip-level raw file
  - The checks find all planted problems: missing day, outage, station rename, holidays
- [x] Stage 2: OD labels (674 of 1,260 pairs toll-substituting), folium and PNG maps
- [x] Stage 3: `config.yaml` (windows, models, thresholds, headline)
- [x] Tests: 15 passing

## Next steps
1. YOU: commit Stages 1–2, then commit `config.yaml` on its own.
2. Optional: Mohammed reviews `report/figures/od_map.html`.
3. Stage 4: ITS, DiD + event study, triple difference, counterfactual, placebos.
4. Stage 5: memo, figures, final README with the recovered estimate.

## Open review items
- Long diagonal pairs (e.g. UAE Exchange to Etisalat/Centrepoint) are labelled control.
  This is plausible, since the car route can avoid gates, but needs the map review.

## Stages
- [x] 1. Repo, data and checks
- [x] 2. Label OD pairs (review pending)
- [x] 3. Fix windows in `config.yaml` (commit pending)
- [ ] 4. Analysis
- [ ] 5. Memo and README
