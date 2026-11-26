"""Compare every estimate with the simulation's ground truth.

This is the ONLY analysis step that reads simulation.yaml. It runs after all
estimates are made, and writes results/summary.json and results/summary.md.
"""

from __future__ import annotations

import json

import pandas as pd
import yaml

from panel import REPO, daily_od_panel, load_config, window

R = REPO / "results"


def load(name: str) -> dict:
    return json.loads((R / f"{name}.json").read_text(encoding="utf-8"))


def implied_total_effect(truth: dict, cfg: dict) -> float:
    """The planted effect expressed as a % of ALL trips (what ITS estimates):
    planted extra trips / counterfactual total trips, post-period of the ITS window."""
    full = daily_od_panel()
    d = window(full, cfg["windows"][cfg["its"]["window"]])
    post = d[d.post == 1]
    e = truth["effect"]["toll_peak"]
    toll_peak = post.loc[(post.toll == 1) & (post.priced_day == 1), "peak"].sum()
    extra = toll_peak * e / (1 + e)
    return float(extra / (post["total"].sum() - extra) * 100)


def main() -> dict:
    truth = yaml.safe_load((REPO / "simulation.yaml").read_text(encoding="utf-8"))
    cfg = load_config()
    did, its, cf, pl = load("did"), load("its"), load("counterfactual"), load("placebo")
    true_peak = truth["effect"]["toll_peak"] * 100
    true_total = implied_total_effect(truth, cfg)

    rows = [
        ("(b) DiD, main window: HEADLINE", "pre-registered", did["headline_did"], true_peak),
        ("(c) Triple difference, main window", "pre-registered", did["triple_difference"],
         true_peak),
        ("DiD, long window + controls", "pre-registered", did["robustness"]["long"], true_peak),
        ("DiD, pre-parking window", "pre-registered", did["robustness"]["pre_parking"],
         true_peak),
        ("(d) Counterfactual forecast", "pre-registered",
         {"pct": cf.get("effect_pct"), "ci_pct": cf.get("ci_pct")}, true_peak),
        ("(a) ITS, all trips", "pre-registered",
         {"pct": its["level_shift_pct"], "ci_pct": its["ci_pct"]}, true_total),
        ("Placebo: fake date", "pre-registered", pl["fake_date"], 0.0),
        ("Placebo: late-evening outcome", "pre-registered", pl["fake_outcome"], 0.0),
        ("DiD, long window, NO controls", "exploratory", did["exploratory"]["long_no_controls"],
         true_peak),
        ("DiD, long window + parking control", "exploratory",
         did["exploratory"]["long_with_parking_control"], true_peak),
        ("Counterfactual + new-gate term", "exploratory",
         {"pct": cf.get("exploratory_with_new_gate_term", {}).get("effect_pct"),
          "ci_pct": cf.get("exploratory_with_new_gate_term", {}).get("ci_pct")}, true_peak),
    ]
    table = []
    for name, kind, r, t in rows:
        if r.get("pct") is None:
            continue
        lo, hi = r["ci_pct"]
        table.append({"estimate": name, "type": kind, "pct": r["pct"], "ci_lo": lo,
                      "ci_hi": hi, "truth_pct": t, "error_pp": r["pct"] - t,
                      "ci_covers_truth": bool(lo <= t <= hi)})
    nv = did["naive"]
    naive = [
        {"estimate": "Naive: toll-peak trips, 4 weeks before vs after", "pct":
            nv["toll_peak_4wk_before_after_pct"], "truth_pct": true_peak},
        {"estimate": "Naive: toll-peak trips, whole pre vs whole post", "pct":
            nv["toll_peak_all_pre_vs_post_pct"], "truth_pct": true_peak},
        {"estimate": "Naive: all trips, whole pre vs whole post", "pct":
            nv["all_trips_pre_vs_post_pct"], "truth_pct": true_total},
    ]
    for n in naive:
        n["error_pp"] = n["pct"] - n["truth_pct"]

    checks = {
        "counterfactual_accuracy": {"value": cf["accuracy_pct"], "target": ">= 85%",
                                    "passed": cf["passed"]},
        "event_study_pretrend_p": {"value": did["event_study"]["pretrend_p"],
                                   "target": "> 0.10",
                                   "passed": did["event_study"]["pretrend_pass"]},
        "placebo_fake_date_p": {"value": pl["fake_date"]["p"], "target": "> 0.05",
                                "passed": pl["fake_date"]["passed"]},
        "placebo_fake_outcome_p": {"value": pl["fake_outcome"]["p"], "target": "> 0.05",
                                   "passed": pl["fake_outcome"]["passed"]},
    }
    summary = {"truth": {"toll_peak_pct": true_peak, "all_trips_pct": true_total},
               "estimates": table, "naive": naive, "checks": checks,
               "all_checks_passed": all(c["passed"] for c in checks.values())}
    (R / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    t = pd.DataFrame(table)
    md = ["# Results summary (SIMULATED DATA)\n",
          f"Planted effect: **{true_peak:+.1f}%** on toll-substituting pairs at priced peak "
          f"hours, equal to **{true_total:+.2f}%** of all trips after the change.\n",
          "## Validity checks\n",
          "| Check | Value | Target | Result |", "|---|---|---|---|"]
    for k, c in checks.items():
        v = f"{c['value']:.1f}%" if k == "counterfactual_accuracy" else f"{c['value']:.3f}"
        md.append(f"| {k} | {v} | {c['target']} | {'PASS' if c['passed'] else 'FAIL'} |")
    md += ["\n## Estimates vs truth\n",
           "| Estimate | Type | Estimate (95% CI) | Truth | Error | CI covers truth |",
           "|---|---|---|---|---|---|"]
    for r in t.itertuples():
        md.append(f"| {r.estimate} | {r.type} | {r.pct:+.2f}% ({r.ci_lo:+.2f} to "
                  f"{r.ci_hi:+.2f}) | {r.truth_pct:+.2f}% | {r.error_pp:+.2f} pp | "
                  f"{'yes' if r.ci_covers_truth else '**no**'} |")
    md += ["\n## Naive comparisons (no control group)\n",
           "| Comparison | Estimate | Truth | Error |", "|---|---|---|---|"]
    for n in naive:
        md.append(f"| {n['estimate']} | {n['pct']:+.2f}% | {n['truth_pct']:+.2f}% | "
                  f"{n['error_pp']:+.2f} pp |")
    (R / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return summary


if __name__ == "__main__":
    main()
