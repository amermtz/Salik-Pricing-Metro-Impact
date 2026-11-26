# Data checks (2024-07-01 to 2025-06-30)

Generated 2026-11-26T15:24:03.

## Summary

- Days with data: 364 of 365
- Total trips: 134,425,037
- Stations seen: 37
- Same-station trips: 0 (0.00% of trips)
- Missing or failed days: 1
- Flagged network drops/spikes: 7 (0 not explained by events.csv)
- Days with station-level drops (<50%): 1 (0 not explained by events.csv)
- Stations appearing late or disappearing early: 2

## 1. Missing days

| date       | manifest_status   | has_trips   |
|:-----------|:------------------|:------------|
| 2024-07-23 | missing           | False       |

## 2. Drops and spikes (vs same-weekday median of previous 4 weeks; <60% or >150%)

Check each against events.csv (holidays, Ramadan, disruptions) before deciding whether to exclude it.

| date       |     trips |   ref_median |   ratio | kind   | events                                    |
|:-----------|----------:|-------------:|--------:|:-------|:------------------------------------------|
| 2024-12-02 | 234149.00 |    426171.50 |    0.55 | drop   | Commemoration and National Day            |
| 2024-12-03 | 236272.00 |    422414.00 |    0.56 | drop   | Commemoration and National Day            |
| 2025-01-01 | 255008.00 |    430839.50 |    0.59 | drop   | New Year's Day 2025; Winter break 2024-25 |
| 2025-03-31 | 238418.00 |    397945.00 |    0.60 | drop   | Eid al-Fitr 2025                          |
| 2025-06-05 | 231588.00 |    420573.50 |    0.55 | drop   | Arafat Day and Eid al-Adha 2025           |
| 2025-06-06 | 229039.00 |    397305.00 |    0.58 | drop   | Arafat Day and Eid al-Adha 2025           |
| 2025-06-26 | 229737.00 |    415508.00 |    0.55 | drop   | Islamic New Year 2025                     |

## 3. Station-level drops (station below 50% of its same-weekday median)

Partial outages can hide in the network total. One row per day.

| date       |   n_stations | stations                                                                                                |   median_ratio | events                                    |
|:-----------|-------------:|:--------------------------------------------------------------------------------------------------------|---------------:|:------------------------------------------|
| 2024-10-15 |            8 | DMCC, Dubai Internet City, Equiti, Mall of the Emirates, Mashreq, Onpassive, Sobha Realty, UAE Exchange |           0.26 | Simulated Red Line outage (south section) |

## 4. Station name changes (possible renames)

| station         | first_seen   | last_seen   |   n_days |      trips | note              |
|:----------------|:-------------|:------------|---------:|-----------:|:------------------|
| Sharaf DG       | 2024-07-01   | 2025-04-30  |      303 | 6019586.00 | disappears early; |
| Sharaf DG Metro | 2025-05-01   | 2025-06-30  |       61 | 1193710.00 | appears late;     |
