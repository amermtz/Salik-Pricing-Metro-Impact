# Progress

_Last updated: 2026-11-26_

## Status: all 5 stages done (simulation study)

Real 2025 Metro ridership is not available, so this is a **simulation study**
with a planted +5% effect. This is stated in the README, the memo and the CV bullet.

## Results
- Headline DiD: **+5.2% (95% CI 4.8 to 5.5)**; truth +5.0% ✅
- Triple difference: +4.8% (4.3 to 5.3) ✅
- Pre-trends p = 0.98 ✅, placebos p = 0.51 and 0.69 ✅, counterfactual accuracy 99.3% ✅
- Counterfactual estimate +5.7% misses the truth (left out the Nov 2024 gates). Reported honestly; the exploratory fix gives +5.3%
- ITS can't detect the effect (it is only 0.86% of all trips)

## Done
- [x] 1. Repo, pipeline, data checks, simulator
- [x] 2. OD labels and review map (Mohammed's review optional/pending)
- [x] 3. `config.yaml` committed before analysis (commit d49e0e3)
- [x] 4. Analysis: ITS, DiD + event study, triple difference, counterfactual, placebos, recovery vs truth
- [x] 5. Memo (2-page PDF), README with headline and CI, NOTES.md
- [x] Automation: `run_all.py` (about 40 s end to end) and a GitHub Actions workflow
- [x] 19 tests passing

## Possible next steps
- Mohammed reviews the map; if labels change, rerun `python run_all.py`
- If real Metro OD data becomes available: fill in `schema.yaml`, aggregate, then `python run_all.py --skip-sim`
- Sensitivity: rerun with other seeds or effect sizes (e.g. 0% or 2%) to show the false-positive rate and power
