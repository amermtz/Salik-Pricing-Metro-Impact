# Results summary (SIMULATED DATA)

Planted effect: **+5.0%** on toll-substituting pairs at priced peak hours, equal to **+0.86%** of all trips after the change.

## Validity checks

| Check | Value | Target | Result |
|---|---|---|---|
| counterfactual_accuracy | 99.3% | >= 85% | PASS |
| event_study_pretrend_p | 0.976 | > 0.10 | PASS |
| placebo_fake_date_p | 0.511 | > 0.05 | PASS |
| placebo_fake_outcome_p | 0.691 | > 0.05 | PASS |

## Estimates vs truth

| Estimate | Type | Estimate (95% CI) | Truth | Error | CI covers truth |
|---|---|---|---|---|---|
| (b) DiD, main window: HEADLINE | pre-registered | +5.16% (+4.81 to +5.51) | +5.00% | +0.16 pp | yes |
| (c) Triple difference, main window | pre-registered | +4.80% (+4.34 to +5.27) | +5.00% | -0.20 pp | yes |
| DiD, long window + controls | pre-registered | +4.84% (+4.58 to +5.10) | +5.00% | -0.16 pp | yes |
| DiD, pre-parking window | pre-registered | +5.14% (+4.80 to +5.48) | +5.00% | +0.14 pp | yes |
| (d) Counterfactual forecast | pre-registered | +5.74% (+5.42 to +6.07) | +5.00% | +0.74 pp | **no** |
| (a) ITS, all trips | pre-registered | -0.12% (-2.16 to +1.96) | +0.86% | -0.98 pp | yes |
| Placebo: fake date | pre-registered | +0.14% (-0.27 to +0.55) | +0.00% | +0.14 pp | yes |
| Placebo: late-evening outcome | pre-registered | +0.11% (-0.44 to +0.67) | +0.00% | +0.11 pp | yes |
| DiD, long window, NO controls | exploratory | +6.09% (+5.85 to +6.34) | +5.00% | +1.09 pp | **no** |
| DiD, long window + parking control | exploratory | +5.11% (+4.88 to +5.33) | +5.00% | +0.11 pp | yes |
| Counterfactual + new-gate term | exploratory | +5.30% (+4.94 to +5.66) | +5.00% | +0.30 pp | yes |

## Naive comparisons (no control group)

| Comparison | Estimate | Truth | Error |
|---|---|---|---|
| Naive: toll-peak trips, 4 weeks before vs after | +5.17% | +5.00% | +0.17 pp |
| Naive: toll-peak trips, whole pre vs whole post | +8.47% | +5.00% | +3.47 pp |
| Naive: all trips, whole pre vs whole post | +3.16% | +0.86% | +2.30 pp |
