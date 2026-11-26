"""Placebo tests, as fixed in config.yaml.

1. Fake date: run the headline DiD inside the pre-period with a made-up change
   date. There should be no "effect".
2. Fake outcome: run the DiD on weekday late-evening (20:00-23:59) off-peak
   trips, which the peak price should not move.

A placebo passes if p > the significance level in config.yaml.

Writes results/placebo.json.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyfixest as pf

from did import coef_summary
from panel import REPO, daily_od_panel, load_config, window


def main() -> dict:
    cfg = load_config()
    pc = cfg["placebo"]
    alpha = pc["significance"]
    full = daily_od_panel()

    # 1. Fake date
    d = window(full, pc["fake_date"]["window"])
    d = d[d.priced_day == 1].copy()
    d["y"] = np.log1p(d["peak"])
    d["treat"] = d["toll"] * (d["date"] >= pd.Timestamp(pc["fake_date"]["date"])).astype(int)
    fake_date = coef_summary(pf.feols("y ~ treat | od + date", data=d, vcov={"CRV1": "od"}),
                             "treat")
    fake_date["passed"] = bool(fake_date["p"] > alpha)

    # 2. Fake outcome
    d = window(full, cfg["windows"][pc["fake_outcome"]["window"]])
    d = d[d.priced_day == 1].copy()
    d["y"] = np.log1p(d["late_eve"])
    d["treat"] = d["toll"] * d["post"]
    fake_outcome = coef_summary(pf.feols("y ~ treat | od + date", data=d,
                                         vcov={"CRV1": "od"}), "treat")
    fake_outcome["passed"] = bool(fake_outcome["p"] > alpha)

    res = {"fake_date": fake_date, "fake_outcome": fake_outcome}
    (REPO / "results" / "placebo.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(f"Placebo {k:13s} {v['pct']:+.2f}% (CI {v['ci_pct'][0]:+.2f} to "
              f"{v['ci_pct'][1]:+.2f}), p={v['p']:.3f} -> {'PASS' if v['passed'] else 'FAIL'}")
    return res


if __name__ == "__main__":
    main()
