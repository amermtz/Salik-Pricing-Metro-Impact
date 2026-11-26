# Progress

_Last updated: 2026-11-26_

## Current stage
**Stage 1: Repo, download and aggregation.** Code done and tested, waiting on
data access.

## Done
- [x] Repo layout, `.gitignore`, `requirements.txt`, MIT `LICENSE`
- [x] `scripts/download_and_aggregate.py`: resumable, one day at a time, deletes raw after processing, manifest with per-day stats
- [x] `scripts/check_data.py`: missing days, drops/spikes, station name changes
- [x] Tests: 9 passing on synthetic data
- [x] `data/events.csv` header (columns: type, name, dates, source URL, verified)

## Next steps
1. Get Dubai Pulse access: metro ridership, metro stations, Salik gate locations.
2. Check Dubai Pulse terms of use: may aggregated data be published in a public repo?
3. Download one day, run `inspect`, fill in `schema.yaml` (especially date/time formats).
4. Run the full download for 2024-07-01 to 2025-06-30.
5. Run `check_data.py`; log findings in DEVLOG.
6. Fill in `data/events.csv` from official sources (gate opening dates, Ramadan 2025, holidays, school terms, parking tariff change, disruptions).

## Blocked on
- Dubai Pulse data access
- Mohammed: map review (Stage 2, later)

## Stages
- [ ] 1. Repo, download and aggregation
- [ ] 2. Label OD pairs (+ Mohammed's map review)
- [ ] 3. Fix windows in `config.yaml`, committed before analysis
- [ ] 4. Analysis: ITS, DiD + event study, triple difference, counterfactual, placebos
- [ ] 5. Memo and README
