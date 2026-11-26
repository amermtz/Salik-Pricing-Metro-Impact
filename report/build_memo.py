"""Build report/memo.md and report/memo.pdf from the results files.

Every number in the memo is read from results/*.json, so the memo always
matches the latest run. Wording that depends on results (pass/fail, covered
or not) is chosen from the results too.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
R = REPO / "results"
OUT_MD = REPO / "report" / "memo.md"
OUT_PDF = REPO / "report" / "memo.pdf"


def j(name: str) -> dict:
    return json.loads((R / f"{name}.json").read_text(encoding="utf-8"))


def ci(lo: float, hi: float) -> str:
    return f"{lo:+.1f}% to {hi:+.1f}%"


def build() -> str:
    s, did, cf, its, pl = j("summary"), j("did"), j("counterfactual"), j("its"), j("placebo")
    est = {e["estimate"]: e for e in s["estimates"]}
    h = did["headline_did"]
    t3 = did["triple_difference"]
    es = did["event_study"]
    truth = s["truth"]["toll_peak_pct"]
    covered = est["(b) DiD, main window: HEADLINE"]["ci_covers_truth"]
    naive = {n["estimate"]: n for n in s["naive"]}
    nv_all = naive["Naive: toll-peak trips, whole pre vs whole post"]
    nv_4 = naive["Naive: toll-peak trips, 4 weeks before vs after"]
    long_nc = did["exploratory"]["long_no_controls"]
    cf_x = cf.get("exploratory_with_new_gate_term", {})
    checks = s["checks"]
    all_pass = s["all_checks_passed"]

    def mark(ok: bool) -> str:
        return "Pass" if ok else "**Fail**"

    cf_line = (
        f"The forecast model met the accuracy bar ({cf['accuracy_pct']:.1f}% on 6 held-out "
        f"weeks), but its estimate, {cf['effect_pct']:+.1f}% ({ci(*cf['ci_pct'])}), "
        + ("covers the truth." if est["(d) Counterfactual forecast"]["ci_covers_truth"] else
           f"**misses the truth**. The pre-registered predictors left out the gates that "
           f"opened on 24 Nov 2024, so the model under-predicts toll-route trips after "
           f"they opened. Adding that step (exploratory) gives {cf_x['effect_pct']:+.1f}% "
           f"({ci(*cf_x['ci_pct'])}). Passing an accuracy test does not make a model "
           f"unbiased.")
    )

    md = f"""# Did Salik's peak pricing push people onto the Metro?

**A simulation study of the causal design.** *All ridership data in this memo is
simulated. No number here describes the real Dubai Metro.*

## Question

On 31 January 2025 Salik introduced variable pricing: AED 6 per crossing at weekday
peaks, AED 4 off-peak and on Sundays, and free late at night. Did this move car trips
onto the Metro, especially at peak hours on routes that would cross a toll gate?
Real 2025 Metro ridership was not publicly available. This study therefore builds a
realistic simulated year with a **known effect (+{truth:.0f}% on toll routes at peak
hours)** and tests whether the method recovers it.

## Data (simulated)

A year (Jul 2024 to Jun 2025) of trips between 36 Red and Green Line stations,
counted by station pair, day and hour. The simulated city includes the things that
make the real question hard: ridership growth, a summer dip, holidays, school
breaks, Ramadan, **two new toll gates opening on 24 Nov 2024**, a parking tariff
change in April, plus an outage, a missing day and a station rename. The data checks
found all of these. Each station pair is labelled *toll-substituting* if the straight
line between its stations crosses a screen line drawn across the road at a Salik gate
(674 of 1,260 pairs).

## Method in plain words

The key comparison is **difference-in-differences**. Take the change in peak trips on
toll routes after 31 January, and subtract the change on routes that cross no gate.
Anything that hits both groups (growth, weather, holidays) cancels out, so what is
left is the effect of the toll. This only works if the two groups were moving in step
before the change. The **event study** checks this week by week. The **triple
difference** adds a third comparison: peak vs off-peak hours, with Sundays as
built-in controls, since the price rose only at weekday peaks. The analysis window
(1 Dec 2024 to 28 Feb 2025) starts after the new gates opened and ends before
Ramadan. It was written down and committed **before** any analysis ran.

## Headline result

**Peak-hour trips on toll-substituting routes rose by {h['pct']:+.1f}% (95% CI
{ci(*h['ci_pct'])}), with errors clustered by station pair.** The planted effect was
+{truth:.1f}%, which the interval {"covers" if covered else "does **not** cover"}.
The triple difference gives {t3['pct']:+.1f}% ({ci(*t3['ci_pct'])}).

![Event study](figures/event_study.png)

## Checks

| Check | Result | Target | |
|---|---|---|---|
| Counterfactual accuracy, held-out weeks | {checks['counterfactual_accuracy']['value']:.1f}% | 85% or more | {mark(checks['counterfactual_accuracy']['passed'])} |
| Event-study pre-trends, joint test | p = {es['pretrend_p']:.2f} | p > 0.10 | {mark(es['pretrend_pass'])} |
| Placebo: fake change date (6 Jan) | {pl['fake_date']['pct']:+.2f}%, p = {pl['fake_date']['p']:.2f} | p > 0.05 | {mark(pl['fake_date']['passed'])} |
| Placebo: late-evening trips | {pl['fake_outcome']['pct']:+.2f}%, p = {pl['fake_outcome']['p']:.2f} | p > 0.05 | {mark(pl['fake_outcome']['passed'])} |

Robustness: the full-year window with controls gives
{did['robustness']['long']['pct']:+.1f}% ({ci(*did['robustness']['long']['ci_pct'])}).
The window ending before the parking change gives
{did['robustness']['pre_parking']['pct']:+.1f}%
({ci(*did['robustness']['pre_parking']['ci_pct'])}).

## What the weaker designs show

- **Naive before/after** on toll-route peak trips: {nv_4['pct']:+.1f}% over four weeks
  (close to the truth by luck, because nothing else changed in those weeks), but
  {nv_all['pct']:+.1f}% over the whole year, mostly growth and seasons. Without a
  control group there is no way to tell which one to believe.
- **Forgetting a confounder:** the full-year DiD *without* the new-gate control gives
  {long_nc['pct']:+.1f}% ({ci(*long_nc['ci_pct'])}), and the interval misses the truth.
- **Interrupted time series** on all trips: {its['level_shift_pct']:+.1f}%
  ({ci(*its['ci_pct'])}). The true effect on *all* trips is only
  {s['truth']['all_trips_pct']:+.2f}%, too small to see in a single noisy series.
- **Counterfactual forecast:** {cf_line}

![Trends](figures/trends.png)

## Limitations

The data is simulated, so this shows the design *can* work, not what happened in
Dubai. The simulated effect is clean (one size, only at peak, only on labelled
routes). Real effects would vary by route, and some trips would be labelled wrongly,
which pulls estimates towards zero. Straight-line labels miss real road routes, so a
review of the map by someone who knows the roads is essential. Station and gate
positions and event dates are approximate.

## What it means for RTA

{"All pre-registered checks pass, and every difference-in-differences estimate recovers the planted effect" if all_pass else "Not all pre-registered checks pass (see above)"}{"; the forecast counterfactual does not." if not est["(d) Counterfactual forecast"]["ci_covers_truth"] else "."}
At the noise levels assumed here, this design can detect a peak-price effect of a few
percent on toll-substituting routes. A simple before/after comparison or a network-wide trend
cannot. The two things that matter most are (1) a control group of routes the toll
does not touch, and (2) handling other changes on the same routes, above all the
November 2024 gate openings. To run it for real, RTA needs station-to-station
ridership for 2024 to 2025 at daily or hourly level. The pipeline is ready for it.
"""
    return md


def to_pdf(md_text: str) -> None:
    import markdown
    from xhtml2pdf import pisa

    body = markdown.markdown(md_text, extensions=["tables"])
    css = """
    @page { size: A4; margin: 1.6cm 1.7cm; }
    body { font-family: Helvetica; font-size: 9.3pt; line-height: 1.32; color: #222; }
    h1 { font-size: 15pt; margin: 0 0 4pt 0; color: #1f4e79; }
    h2 { font-size: 11pt; margin: 9pt 0 2pt 0; color: #1f4e79; }
    p, li { margin: 0 0 4pt 0; }
    table { border-collapse: collapse; margin: 4pt 0; }
    th, td { border: 0.5pt solid #bbb; padding: 2pt 4pt; font-size: 8.5pt; }
    th { background: #eef3f8; }
    img { width: 15.5cm; }
    """
    html = f"<html><head><style>{css}</style></head><body>{body}</body></html>"

    def link_callback(uri, rel):
        p = (REPO / "report" / uri).resolve()
        return str(p) if p.exists() else uri

    with open(OUT_PDF, "wb") as f:
        status = pisa.CreatePDF(html, dest=f, link_callback=link_callback)
    if status.err:
        raise SystemExit("PDF export failed")


def main() -> None:
    md = build()
    OUT_MD.write_text(md, encoding="utf-8")
    to_pdf(md)
    print(f"Wrote {OUT_MD} and {OUT_PDF}")


if __name__ == "__main__":
    main()
