"""Unit tests for the analysis code on small synthetic panels with a known effect."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import did  # noqa: E402


def make_panel(effect: float, n_pairs: int = 80, n_days: int = 70, seed: int = 0,
               pre_trend_gap: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n_days, freq="D")
    treat_date = dates[n_days // 2]
    rows = []
    base = rng.uniform(200, 800, n_pairs)
    day_fx = np.exp(rng.normal(0, 0.05, n_days))
    for i in range(n_pairs):
        toll = int(i < n_pairs // 2)
        for t, d in enumerate(dates):
            post = int(d >= treat_date)
            mu = base[i] * day_fx[t] * (1 + effect * toll * post)
            mu *= np.exp(pre_trend_gap * toll * (t - n_days // 2) / n_days)
            pk = rng.poisson(mu)
            rows.append({"od": f"p{i}", "date": d, "priced_day": 1, "toll": toll, "post": post,
                         "peak": pk, "offpeak": rng.poisson(mu), "dow": d.dayofweek})
    return pd.DataFrame(rows), treat_date


def test_did_recovers_known_effect():
    df, _ = make_panel(effect=0.10)
    r = did.did(df)
    assert r["ci_pct"][0] < 10 < r["ci_pct"][1]
    assert abs(r["pct"] - 10) < 2


def test_did_finds_nothing_when_no_effect():
    df, _ = make_panel(effect=0.0, seed=1)
    r = did.did(df)
    assert r["ci_pct"][0] < 0 < r["ci_pct"][1]


def test_event_study_flags_diverging_pretrends():
    df, t = make_panel(effect=0.0, seed=2, pre_trend_gap=0.30)
    cfg = {"treatment_date": t, "event_study": {"reference_week": -1,
                                                 "pretrend_test_p_min": 0.10}}
    es = did.event_study(df, cfg)
    assert not es["pretrend_pass"]


def test_event_study_passes_parallel_trends():
    df, t = make_panel(effect=0.10, seed=3)
    cfg = {"treatment_date": t, "event_study": {"reference_week": -1,
                                                 "pretrend_test_p_min": 0.10}}
    es = did.event_study(df, cfg)
    assert es["pretrend_pass"]
