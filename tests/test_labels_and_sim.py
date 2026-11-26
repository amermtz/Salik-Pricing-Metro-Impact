"""Tests for OD-pair labelling, the calendar and the simulator."""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import yaml
from shapely.geometry import Point

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import calendar_utils as cu  # noqa: E402
import label_od_pairs as lab  # noqa: E402


def _gdf(rows, crs=lab.CRS_METRIC):
    df = pd.DataFrame(rows)
    return gpd.GeoDataFrame(df, geometry=[Point(x, y) for x, y in zip(df.x, df.y)], crs=crs)


def test_screen_line_is_perpendicular_to_road():
    gates = _gdf([{"gate": "G", "x": 0, "y": 0, "road_bearing_deg": 0,
                   "screen_length_m": 1000, "opened": pd.Timestamp("2020-01-01")}])
    line = lab.screen_lines(gates).geometry.iloc[0]
    (x1, y1), (x2, y2) = line.coords
    assert abs(y1) < 1e-6 and abs(y2) < 1e-6      # north-south road -> east-west line
    assert abs(abs(x2 - x1) - 1000) < 1e-6


def test_pairs_crossing_gate_are_labelled():
    st = _gdf([{"station": "S", "x": 0, "y": -2000}, {"station": "N", "x": 0, "y": 2000},
               {"station": "E", "x": 3000, "y": -2000}])
    gates = _gdf([{"gate": "G", "x": 0, "y": 0, "road_bearing_deg": 0,
                   "screen_length_m": 1000, "opened": pd.Timestamp("2024-11-24")}])
    out = lab.label_pairs(st, lab.screen_lines(gates)).set_index(["origin", "destination"])
    assert out.loc[("S", "N"), "toll_substituting"] == 1
    assert out.loc[("N", "S"), "toll_substituting"] == 1
    assert out.loc[("S", "N"), "crosses_new_gate"] == 1
    assert out.loc[("S", "E"), "toll_substituting"] == 0
    assert out.loc[("E", "N"), "toll_substituting"] == 0  # passes east of the short line


def test_priced_peak_rules():
    cal = cu.daily_calendar("2025-01-26", "2025-03-04").set_index("date")
    hours = np.arange(24)
    mon = cal.loc["2025-01-27"]
    sun = cal.loc["2025-02-02"]
    ram = cal.loc["2025-03-03"]
    pk = lambda r: set(hours[cu.priced_peak(np.array(r.priced_day), np.array(r.ramadan), hours)])
    assert pk(mon) == set(cu.PEAK_HOURS)
    assert pk(sun) == set()
    assert pk(ram) == set(cu.RAMADAN_PEAK_HOURS)


@pytest.fixture(scope="module")
def world():
    if not (REPO / "data" / "od_labels.csv").exists():
        pytest.skip("run src/label_od_pairs.py first")
    import simulate_ridership as sim
    cfg = yaml.safe_load((REPO / "simulation.yaml").read_text(encoding="utf-8"))
    return sim, cfg


def test_simulation_is_deterministic(world):
    sim, cfg = world
    w = sim.World(cfg)
    a = w.simulate_day(pd.Timestamp("2025-02-10"))
    b = w.simulate_day(pd.Timestamp("2025-02-10"))
    pd.testing.assert_frame_equal(a, b)


def test_planted_effect_shows_in_expectation(world):
    """With noise switched off, toll-pair peak trips rise by exactly the planted effect."""
    sim, cfg = world
    quiet = {**cfg, "daily_shock_sd": 0.0, "od_trend_sd": 0.0, "od_day_sd": 0.0,
             "cell_dispersion": 1e9, "daily_trips": 5e7}
    big = {**quiet, "effect": {**cfg["effect"], "toll_peak": 0.5}}
    day = pd.Timestamp("2025-02-10")  # Monday, after the change
    a = sim.World(quiet).simulate_day(day)
    b = sim.World(big).simulate_day(day)
    labels = pd.read_csv(REPO / "data" / "od_labels.csv")
    toll = set(map(tuple, labels.loc[labels.toll_substituting == 1, ["origin", "destination"]]
                   .values))

    def peak_toll(df):
        m = df.apply(lambda r: (r.origin, r.destination) in toll, axis=1) & \
            df.hour.isin(cu.PEAK_HOURS)
        return df.loc[m, "trips"].sum()

    ratio = peak_toll(b) / peak_toll(a)
    assert abs(ratio - 1.5 / 1.05) < 0.01


def test_rename_after_date(world):
    sim, cfg = world
    w = sim.World(cfg)
    before = w.simulate_day(pd.Timestamp("2025-04-30"))
    after = w.simulate_day(pd.Timestamp("2025-05-02"))
    assert "Sharaf DG" in set(before.origin) and "Sharaf DG Metro" not in set(before.origin)
    assert "Sharaf DG Metro" in set(after.origin) and "Sharaf DG" not in set(after.origin)
