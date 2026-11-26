# Notes: the ideas behind the design

Plain-language notes on the causal-inference ideas used in this study. Numbers
refer to the **simulated** data (see `results/summary.md`).

## 1. Correlation vs causation

"Metro ridership went up after January 2025" is a correlation in time. It does
not show that the toll caused it, because many things change at once:

- ridership grows every year (population, new jobs);
- the seasons change (winter is busy, summer is quiet);
- school breaks end, Ramadan starts, holidays come and go;
- other policies change too (new Salik gates in November 2024, parking in April 2025).

In this study a naive comparison of toll-route peak trips before and after
gives **+8.5%** over the whole year, against a true effect of **+5%**. The gap
is growth and seasons. Over just four weeks the naive number is +5.2%, which is
right, but only by luck. Without a comparison group you cannot know which naive
number to trust.

To claim causation, you need a credible answer to: **what would ridership have
been without the change?** (the *counterfactual*). Each design here is a
different way of estimating it.

## 2. What difference-in-differences compares

Compare two groups across two periods:

|                         | Before 31 Jan | After 31 Jan | Change |
|---|---|---|---|
| **Toll-substituting pairs** (cross a gate) | A | B | B − A |
| **Control pairs** (cross no gate)          | C | D | D − C |
| **Difference-in-differences**              |   |   | **(B − A) − (D − C)** |

- `B − A` = toll effect + everything else that changed (growth, season, holidays).
- `D − C` = everything else that changed, without the toll effect.
- Subtracting removes "everything else" and leaves the toll effect.

With logs of trip counts, the result is a percentage change. In the regression
this is `log(trips) ~ toll × post | pair FE + date FE`. Pair fixed effects
absorb that some pairs are always busier. Date fixed effects absorb anything
that hits every pair on a given day.

**Why cluster standard errors by pair?** The same pair's trips are correlated
from day to day. Treating the 93,240 pair-days in the headline model as independent would make the
confidence interval far too narrow. Clustering treats each pair as one
independent unit.

## 3. Parallel trends and the event study

DiD has one key assumption: **without the toll change, toll and control pairs
would have moved in parallel.** They don't need the same level, only the same
trend.

This can't be proven for the after-period, but it can be checked before it.
The **event study** estimates a separate toll-vs-control gap for every week,
relative to the week just before the change:

- Before the change, the weekly gaps should sit around zero. If they drift, the
  groups were already diverging and DiD would mistake that drift for an effect.
- After the change, the gaps show the effect and how it develops over time.

Here the pre-period gaps are all near zero. A joint test that they are all
zero gives **p = 0.98** (target p > 0.10). After the change they jump to about
+5% (`report/figures/event_study.png`). A unit test also checks that the test
*fails* when trends really diverge (`tests/test_analysis.py`).

## 4. Why Sundays and off-peak hours are built-in controls

The price rose **only at weekday peak hours**. On Sundays and off-peak, the
toll stayed at AED 4. So on the *same* toll-route pairs:

- if peak trips rose but off-peak trips didn't, that points to the price;
- if both rose equally, something else is going on (e.g. a new mall on that
  route), and it isn't the toll.

The **triple difference** (toll × peak × after) uses this. It compares the
toll-vs-control gap at peak with the same gap off-peak. Anything that affects
a route at all hours cancels out, such as the new gates, which here raised
toll-route trips at all hours. Result: **+4.8% (95% CI 4.3% to 5.3%)**.

The late-evening placebo uses the same logic: late-evening trips weren't
repriced, so the "effect" there should be zero. It is: +0.1%, p = 0.69.

## 5. Why the windows were fixed before looking at results

Every analysis involves choices: which dates, which controls, which outcome.
If you choose after seeing results, you can (even without meaning to) pick the
version that gives the answer you hoped for. This is called *p-hacking*, or
the *garden of forking paths*.

So `config.yaml` (windows, models, thresholds, headline) was **committed to
git before any analysis ran**. The commit history proves the order. Anything
added later is labelled *exploratory* in the results.

That rule mattered here. The pre-registered counterfactual model **missed** the
truth (+5.7%, CI 5.4% to 6.1%). It is reported as it came out, and the fix is
shown separately as exploratory.

## 6. Confounders and how each was handled

| Confounder | Problem | How it was handled |
|---|---|---|
| **New Salik gates** (Business Bay, Al Safa South, 24 Nov 2024) | Raised Metro use on the routes crossing them: the same routes as the treatment group | Main window starts 1 Dec 2024, after they opened. The long window adds a `new_gate_post` control. Leaving it out biases the estimate to +6.1% |
| **Ramadan** (Mar 2025) | Different travel pattern and different Salik peak hours (9 am–5 pm) | Main window ends 28 Feb. Peak slots follow Ramadan hours. Robustness windows add a toll × Ramadan term |
| **School holidays** | Fewer peak trips | Hit toll and control pairs alike, so date fixed effects absorb them. The ITS and counterfactual include a school-holiday term |
| **Parking tariff** (Apr 2025) | Pushes trips towards the Metro at peak into central stations, many of them toll routes | Main window ends before it. A pre-parking robustness window too |
| **Growth and seasons** | Make every before/after comparison look like an effect | Control pairs and date fixed effects |
| **Outage, missing day, station rename** | Fake drops and fake new stations | Found by `check_data.py`. The outage day is excluded and the rename merged, both in `config.yaml` |

## 7. What passing the checks does and doesn't mean

- Passing pre-trend and placebo tests makes the design **more credible**, but
  can't *prove* it. A confounder that starts exactly on 31 Jan and hits only
  toll routes at peak would pass every test.
- An accurate forecast is not an unbiased forecast. The counterfactual model
  was 99.3% accurate on held-out weeks, yet still biased, because the
  pre-registered predictors left out a break in November.
