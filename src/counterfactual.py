"""Forecast-based counterfactual with an accuracy check.

Model daily priced-peak trips on toll-substituting pairs (log) from control-pair
trips and calendar terms, trained on the pre-period only. Test on the last
6 pre-period weeks, held out. The model is used for the counterfactual only if
it meets the accuracy bar in config.yaml (MAPE <= 15%).

Writes results/counterfactual.json and report/figures/counterfactual.png.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402

from panel import REPO, daily_od_panel, load_config, window  # noqa: E402

FORMULA = "y ~ log_ctrl_peak + log_ctrl_off + C(dow) + school_holiday"


def build_series(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df.priced_day == 1]
    g = d.groupby(["date", "toll"])[["peak", "offpeak"]].sum().unstack("toll")
    cal = d.groupby("date")[["dow", "holiday", "school_holiday", "post"]].first()
    s = pd.DataFrame({
        "toll_peak": g[("peak", 1)],
        "log_ctrl_peak": np.log(g[("peak", 0)]),
        "log_ctrl_off": np.log(g[("offpeak", 0)]),
    }).join(cal).reset_index()
    s["y"] = np.log(s["toll_peak"])
    gate_open = df.loc[df.new_gate_post == 1, "date"].min()
    s["new_gates_open"] = (s["date"] >= gate_open).astype(int)
    return s


def effect_after(s: pd.DataFrame, formula: str, pre_start, treat, end) -> tuple[dict, object]:
    """Fit on the pre-period, return the mean post-period gap with a HAC CI."""
    pre = s[(s.date >= pd.Timestamp(pre_start)) & (s.date < treat)]
    post = s[(s.date >= treat) & (s.date <= pd.Timestamp(end))]
    fit = smf.ols(formula, data=pre).fit()
    gap = post["y"] - fit.predict(post)
    # Uncertainty: HAC standard error of the mean post-period gap. This ignores
    # uncertainty in the fitted coefficients, so the interval is somewhat too narrow.
    g = smf.ols("gap ~ 1", data=pd.DataFrame({"gap": gap})).fit(
        cov_type="HAC", cov_kwds={"maxlags": 6})
    b, se = float(g.params.iloc[0]), float(g.bse.iloc[0])
    return {
        "effect_pct": float(np.expm1(b) * 100),
        "ci_pct": [float(np.expm1(b - 1.96 * se) * 100), float(np.expm1(b + 1.96 * se) * 100)],
        "n_post_days": int(len(post)),
    }, fit


def main() -> dict:
    cfg = load_config()
    c = cfg["counterfactual"]
    treat = pd.Timestamp(cfg["treatment_date"])
    s = build_series(daily_od_panel())

    train = window(s, c["train"])
    hold = window(s, c["holdout"])
    fit = smf.ols(FORMULA, data=train).fit()
    pred_hold = np.exp(fit.predict(hold))
    mape = float(np.mean(np.abs(hold["toll_peak"] - pred_hold) / hold["toll_peak"]))
    passed = mape <= c["accuracy_bar_mape"]

    res = {"holdout_mape": mape, "accuracy_pct": (1 - mape) * 100,
           "accuracy_bar_mape": c["accuracy_bar_mape"], "passed": bool(passed),
           "n_train_days": int(len(train)), "n_holdout_days": int(len(hold))}

    main_w = cfg["windows"]["main"]
    if passed:
        # Refit on the whole pre-period, predict the post-period in the main window.
        eff, fit2 = effect_after(s, FORMULA, c["train"]["start"], treat, main_w["end"])
        res.update(eff)
        # Exploratory, NOT pre-registered: add a step for the late-2024 gate
        # openings, which the pre-registered predictors left out.
        eff_x, _ = effect_after(s, FORMULA + " + new_gates_open", c["train"]["start"], treat,
                                main_w["end"])
        res["exploratory_with_new_gate_term"] = eff_x
        plot =s[(s.date >= pd.Timestamp("2024-10-01")) & (s.date <= pd.Timestamp(main_w["end"]))]
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(plot.date, plot.toll_peak / 1e3, color="#1f4e79", lw=1.2, label="Actual")
        ax.plot(plot.date, np.exp(fit2.predict(plot)) / 1e3, color="#c0392b", lw=1.2, ls="--",
                label="Counterfactual (no pricing change)")
        ax.axvspan(pd.Timestamp(c["holdout"]["start"]), pd.Timestamp(c["holdout"]["end"]),
                   color="#eee", label=f"Held-out weeks (MAPE {mape:.1%})")
        ax.axvline(treat, color="#333", ls="--", lw=1)
        ax.set_ylabel("Priced-peak trips on\ntoll pairs (thousands/day)")
        ax.set_title(f"Counterfactual check (simulated data): {res['effect_pct']:+.1f}% after "
                     "31 Jan", fontsize=10)
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(REPO / "report" / "figures" / "counterfactual.png", dpi=150)
        plt.close(fig)

    (REPO / "results" / "counterfactual.json").write_text(json.dumps(res, indent=2),
                                                         encoding="utf-8")
    print(f"Counterfactual: holdout MAPE {mape:.2%} -> {'PASS' if passed else 'FAIL'}"
          + (f"; effect {res['effect_pct']:+.2f}% (95% CI {res['ci_pct'][0]:+.2f} to "
             f"{res['ci_pct'][1]:+.2f})" if passed else ""))
    if passed:
        x = res["exploratory_with_new_gate_term"]
        print(f"  exploratory + new-gate term: {x['effect_pct']:+.2f}% "
              f"(95% CI {x['ci_pct'][0]:+.2f} to {x['ci_pct'][1]:+.2f})")
    return res


if __name__ == "__main__":
    main()
