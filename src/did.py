"""Difference-in-differences, event study and triple difference.

All specifications are taken from config.yaml (committed before analysis).
Outcome: log(trips + 1) at OD pair x date x slot. Standard errors are
clustered by OD pair.

Writes results/did.json and report/figures/event_study.png, trends.png.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyfixest as pf  # noqa: E402
from scipy import stats  # noqa: E402

from panel import REPO, daily_od_panel, load_config, slot_panel, window  # noqa: E402

RESULTS = REPO / "results"
FIG = REPO / "report" / "figures"
warnings.filterwarnings("ignore", category=FutureWarning)


def pct(b: float) -> float:
    return float(np.expm1(b) * 100)


def coef_summary(fit, term: str) -> dict:
    b = float(fit.coef()[term])
    se = float(fit.se()[term])
    lo, hi = b - 1.96 * se, b + 1.96 * se
    return {"term": term, "beta": b, "se": se, "p": float(fit.pvalue()[term]),
            "pct": pct(b), "ci_pct": [pct(lo), pct(hi)], "n_obs": int(fit._N)}


def peak_panel(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df.priced_day == 1].copy()
    d["y"] = np.log1p(d["peak"])
    return d


def did(df: pd.DataFrame, controls: list[str] | None = None) -> dict:
    d = peak_panel(df)
    d["treat"] = d["toll"] * d["post"]
    rhs = ["treat"]
    for c in controls or []:
        if c == "new_gate_post":
            rhs.append("new_gate_post")
        elif c == "ramadan_peak_shift":
            d["toll_ramadan"] = d["toll"] * d["ramadan"]
            rhs.append("toll_ramadan")
        elif c == "parking":
            d["cbd_parking"] = d["dest_cbd"] * d["parking_post"]
            rhs.append("cbd_parking")
        else:
            raise ValueError(c)
    # Drop terms with no variation in this window (e.g. Ramadan in the main window).
    rhs = [r for r in rhs if d[r].nunique() > 1]
    fit = pf.feols(f"y ~ {' + '.join(rhs)} | od + date", data=d, vcov={"CRV1": "od"})
    out = coef_summary(fit, "treat")
    out["controls"] = rhs[1:]
    return out


def event_study(df: pd.DataFrame, cfg: dict) -> dict:
    es = cfg["event_study"]
    treat_date = pd.Timestamp(cfg["treatment_date"])
    d = peak_panel(df)
    d["rel_week"] = ((d["date"] - treat_date).dt.days // 7).astype(int)
    ref = es["reference_week"]
    weeks = sorted(d["rel_week"].unique())
    names = []
    for w in weeks:
        if w == ref:
            continue
        n = f"w_{'m' if w < 0 else 'p'}{abs(w)}"
        d[n] = ((d["rel_week"] == w) & (d["toll"] == 1)).astype(int)
        names.append((w, n))
    fit = pf.feols(f"y ~ {' + '.join(n for _, n in names)} | od + date", data=d,
                   vcov={"CRV1": "od"})
    b, se = fit.coef(), fit.se()
    rows = [{"week": int(w), "beta": float(b[n]), "se": float(se[n]),
             "pct": pct(b[n]), "lo_pct": pct(b[n] - 1.96 * se[n]),
             "hi_pct": pct(b[n] + 1.96 * se[n])} for w, n in names]
    rows.append({"week": ref, "beta": 0.0, "se": 0.0, "pct": 0.0, "lo_pct": 0.0,
                 "hi_pct": 0.0})
    rows.sort(key=lambda r: r["week"])

    # Joint Wald test that all pre-period coefficients are zero (cluster-robust vcov).
    pre = [n for w, n in names if w < 0]
    idx = [list(fit.coef().index).index(n) for n in pre]
    V = np.asarray(fit._vcov)[np.ix_(idx, idx)]
    bb = b[pre].to_numpy()
    wald = float(bb @ np.linalg.solve(V, bb))
    k = len(pre)
    G = d["od"].nunique()
    F = wald / k
    p = float(1 - stats.f.cdf(F, k, G - 1))
    return {"weeks": rows, "pretrend_F": F, "pretrend_df": [int(k), int(G - 1)],
            "pretrend_p": p, "pretrend_pass": bool(p > es["pretrend_test_p_min"])}


def triple_difference(df: pd.DataFrame) -> dict:
    d = slot_panel(df)
    d["ddd"] = d["toll"] * d["post"] * d["is_peak"]
    d["od_slot"] = d["od"] + "|" + d["slot"]
    d["date_slot"] = d["date"].astype(str) + "|" + d["slot"]
    d["od_post"] = d["od"] + "|" + d["post"].astype(str)
    fit = pf.feols("y ~ ddd | od_slot + date_slot + od_post", data=d, vcov={"CRV1": "od"})
    return coef_summary(fit, "ddd")


def naive(df_full: pd.DataFrame, cfg: dict) -> dict:
    """Comparisons a careless analyst might make. Shown to explain why the design matters."""
    t = pd.Timestamp(cfg["treatment_date"])
    pk = df_full[(df_full.toll == 1) & (df_full.priced_day == 1)]
    daily = pk.groupby("date")["peak"].sum()
    four_b = daily[(daily.index >= t - pd.Timedelta(days=28)) & (daily.index < t)].mean()
    four_a = daily[(daily.index >= t) & (daily.index < t + pd.Timedelta(days=28))].mean()
    tot = df_full.groupby("date")["total"].sum()
    yr_b = tot[tot.index < t].mean()
    yr_a = tot[tot.index >= t].mean()
    return {
        "toll_peak_4wk_before_after_pct": float((four_a / four_b - 1) * 100),
        "toll_peak_all_pre_vs_post_pct": float(
            (daily[daily.index >= t].mean() / daily[daily.index < t].mean() - 1) * 100),
        "all_trips_pre_vs_post_pct": float((yr_a / yr_b - 1) * 100),
    }


def plot_event_study(es: dict, path: Path) -> None:
    w = pd.DataFrame(es["weeks"])
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.axhline(0, color="#888", lw=0.8)
    ax.axvline(-0.5, color="#c33", lw=1, ls="--")
    ax.errorbar(w.week, w.pct, yerr=[w.pct - w.lo_pct, w.hi_pct - w.pct], fmt="o",
                color="#1f4e79", ecolor="#7aa6d1", capsize=3, ms=5)
    ax.set_xlabel("Weeks relative to 31 Jan 2025 (reference: week -1)")
    ax.set_ylabel("Toll vs control pairs,\npriced-peak trips (%)")
    ax.set_title(f"Event study (simulated data). Pre-trend joint test p = "
                 f"{es['pretrend_p']:.2f}", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_trends(df: pd.DataFrame, cfg: dict, path: Path) -> None:
    """Weekly ratio of toll to control trips, peak vs off-peak, indexed to pre-period."""
    t = pd.Timestamp(cfg["treatment_date"])
    d = df.copy()
    d["week"] = d["date"] - pd.to_timedelta((d["date"] - t).dt.days % 7, unit="D")
    g = d.groupby(["week", "toll"])[["peak", "offpeak"]].sum().unstack("toll")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for slot, color in (("peak", "#c0392b"), ("offpeak", "#7f8c8d")):
        r = g[(slot, 1)] / g[(slot, 0)]
        r = r / r[r.index < t].mean() * 100
        ax.plot(r.index, r.values, color=color, lw=1.6,
                label="Priced peak" if slot == "peak" else "Off-peak")
    ax.axvline(t, color="#333", ls="--", lw=1)
    ax.text(t, ax.get_ylim()[1], " 31 Jan 2025", va="top", fontsize=8)
    for name, col in (("New gates", "2024-11-24"), ("Ramadan", "2025-03-01"),
                      ("Parking", "2025-04-04")):
        ax.axvline(pd.Timestamp(col), color="#aaa", ls=":", lw=1)
        ax.text(pd.Timestamp(col), ax.get_ylim()[0], f" {name}", va="bottom", fontsize=7,
                color="#666")
    ax.set_ylabel("Toll / control trips\n(pre-period mean = 100)")
    ax.set_title("Toll-substituting vs control pairs, weekly (simulated data)", fontsize=10)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> dict:
    cfg = load_config()
    full = daily_od_panel()
    W = cfg["windows"]
    main_df = window(full, W["main"])

    res = {
        "headline_did": did(main_df),
        "event_study": event_study(main_df, cfg),
        "triple_difference": triple_difference(main_df),
        "robustness": {
            "long": did(window(full, W["long"]), W["long"].get("controls")),
            "pre_parking": did(window(full, W["pre_parking"]), W["pre_parking"].get("controls")),
        },
        "exploratory": {
            # Not pre-registered: shows what a missed confounder does.
            "long_no_controls": did(window(full, W["long"])),
            "long_with_parking_control": did(window(full, W["long"]),
                                             W["long"].get("controls", []) + ["parking"]),
        },
        "naive": naive(full, cfg),
    }
    RESULTS.mkdir(exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    (RESULTS / "did.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    plot_event_study(res["event_study"], FIG / "event_study.png")
    plot_trends(full, cfg, FIG / "trends.png")

    h, t3 = res["headline_did"], res["triple_difference"]
    print(f"Headline DiD:   {h['pct']:+.2f}% (95% CI {h['ci_pct'][0]:+.2f} to "
          f"{h['ci_pct'][1]:+.2f}), p={h['p']:.3g}")
    print(f"Triple diff:    {t3['pct']:+.2f}% (95% CI {t3['ci_pct'][0]:+.2f} to "
          f"{t3['ci_pct'][1]:+.2f})")
    print(f"Pre-trend test: p={res['event_study']['pretrend_p']:.3f}")
    for k, v in {**res["robustness"], **res["exploratory"]}.items():
        print(f"{k:28s} {v['pct']:+.2f}% (CI {v['ci_pct'][0]:+.2f} to {v['ci_pct'][1]:+.2f})"
              f" controls={v['controls']}")
    print("Naive:", {k: round(v, 2) for k, v in res["naive"].items()})
    return res


if __name__ == "__main__":
    main()
