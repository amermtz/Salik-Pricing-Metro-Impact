"""Interrupted time series on total daily Metro trips.

Segmented regression of log daily trips on a level shift and slope change at
the treatment date, with day-of-week, holiday, Ramadan and school-holiday
terms, as fixed in config.yaml. Newey-West (HAC) standard errors.

ITS has no control group, so anything else that changes around 31 Jan 2025
(growth, seasons, other policies) loads onto the level shift. It is a weak
design here and is reported for comparison.

Writes results/its.json and report/figures/its.png.
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


def daily_series(df: pd.DataFrame) -> pd.DataFrame:
    d = df.groupby("date").agg(trips=("total", "sum"), dow=("dow", "first"),
                               holiday=("holiday", "first"), ramadan=("ramadan", "first"),
                               school_holiday=("school_holiday", "first"),
                               post=("post", "first")).reset_index()
    d["y"] = np.log(d["trips"])
    return d


def fit_its(d: pd.DataFrame, treat: pd.Timestamp, lags: int):
    d = d.copy()
    d["t"] = (d["date"] - treat).dt.days / 365.25
    d["t_post"] = d["t"] * d["post"]
    model = smf.ols("y ~ post + t + t_post + C(dow) + holiday + ramadan + school_holiday",
                    data=d)
    return model.fit(cov_type="HAC", cov_kwds={"maxlags": lags}), d


def main() -> dict:
    cfg = load_config()
    c = cfg["its"]
    treat = pd.Timestamp(cfg["treatment_date"])
    full = daily_od_panel()
    d = daily_series(window(full, cfg["windows"][c["window"]]))
    fit, d = fit_its(d, treat, c["hac_lags"])

    b, se = fit.params["post"], fit.bse["post"]
    res = {
        "level_shift_pct": float(np.expm1(b) * 100),
        "ci_pct": [float(np.expm1(b - 1.96 * se) * 100), float(np.expm1(b + 1.96 * se) * 100)],
        "p": float(fit.pvalues["post"]),
        "slope_change_pct_per_year": float(np.expm1(fit.params["t_post"]) * 100),
        "n_days": int(fit.nobs),
        "r2": float(fit.rsquared),
    }
    (REPO / "results" / "its.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    # Plot: actual vs fitted, and the no-change counterfactual from the same model
    cf = d.assign(post=0, t_post=0.0)
    d["fitted"] = fit.predict(d)
    d["counterfactual"] = fit.predict(cf)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(d["date"], d["trips"] / 1e3, color="#bbb", lw=0.8, label="Actual")
    ax.plot(d["date"], np.exp(d["fitted"]) / 1e3, color="#1f4e79", lw=1.2, label="Model")
    post = d["post"] == 1
    ax.plot(d.loc[post, "date"], np.exp(d.loc[post, "counterfactual"]) / 1e3, color="#c0392b",
            lw=1.2, ls="--", label="Model without the change")
    ax.axvline(treat, color="#333", ls="--", lw=1)
    ax.set_ylabel("Daily trips (thousands)")
    ax.set_title(f"Interrupted time series, all trips (simulated data): level shift "
                 f"{res['level_shift_pct']:+.1f}%", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(REPO / "report" / "figures" / "its.png", dpi=150)
    plt.close(fig)

    print(f"ITS level shift: {res['level_shift_pct']:+.2f}% (95% CI {res['ci_pct'][0]:+.2f} to "
          f"{res['ci_pct'][1]:+.2f}), p={res['p']:.3g}")
    return res


if __name__ == "__main__":
    main()
