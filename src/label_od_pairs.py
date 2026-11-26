"""Label metro OD pairs as toll-substituting or not.

For each Salik gate a short "screen line" is drawn across the road at the gate
(perpendicular to the road). An OD pair is toll-substituting if the straight
segment between its two stations crosses at least one screen line (optionally
with a small buffer around the segment).

Outputs
-------
data/od_labels.csv           one row per ordered OD pair
report/figures/od_map.html   folium review map
report/figures/od_map.png    static map for the README / memo

Usage:
    python src/label_od_pairs.py [--buffer-m 0]
"""

from __future__ import annotations

import argparse
import math
from itertools import permutations
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
FIG = REPO / "report" / "figures"
CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:32640"  # UTM zone 40N, metres; covers Dubai

# Gates that opened in late 2024: a confounder for the pricing change.
NEW_GATE_DATE = "2024-11-01"


def load_inputs(data_dir: Path = DATA) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    st = pd.read_csv(data_dir / "stations.csv")
    gt = pd.read_csv(data_dir / "gates.csv", parse_dates=["opened"])
    st = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=CRS_WGS84)
    gt = gpd.GeoDataFrame(gt, geometry=gpd.points_from_xy(gt.lon, gt.lat), crs=CRS_WGS84)
    return st.to_crs(CRS_METRIC), gt.to_crs(CRS_METRIC)


def screen_lines(gates: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """A line of length screen_length_m through each gate, perpendicular to the road."""
    lines = []
    for g in gates.itertuples():
        # Road bearing is degrees clockwise from north. The screen line runs at +90 deg.
        b = math.radians(g.road_bearing_deg + 90)
        dx, dy = math.sin(b), math.cos(b)  # east, north components
        h = g.screen_length_m / 2
        x, y = g.geometry.x, g.geometry.y
        lines.append(LineString([(x - dx * h, y - dy * h), (x + dx * h, y + dy * h)]))
    out = gates.copy()
    out["geometry"] = lines
    return out.set_geometry("geometry")


def label_pairs(stations: gpd.GeoDataFrame, screens: gpd.GeoDataFrame,
                buffer_m: float = 0.0) -> pd.DataFrame:
    pos = {s.station: s.geometry for s in stations.itertuples()}
    new_gate = screens["opened"] >= pd.Timestamp(NEW_GATE_DATE)
    rows = []
    for o, d in permutations(pos, 2):
        seg = LineString([pos[o], pos[d]])
        test = seg.buffer(buffer_m) if buffer_m > 0 else seg
        hit = screens[screens.intersects(test)]
        rows.append({
            "origin": o,
            "destination": d,
            "distance_km": round(seg.length / 1000, 2),
            "gates_crossed": "|".join(hit["gate"]),
            "n_gates": len(hit),
            "toll_substituting": int(len(hit) > 0),
            "crosses_new_gate": int(new_gate[hit.index].any()) if len(hit) else 0,
        })
    return pd.DataFrame(rows)


def build_maps(stations: gpd.GeoDataFrame, screens: gpd.GeoDataFrame,
               labels: pd.DataFrame, fig_dir: Path = FIG) -> None:
    import folium
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)
    st = stations.to_crs(CRS_WGS84)
    sc = screens.to_crs(CRS_WGS84)
    ll = {s.station: (s.geometry.y, s.geometry.x) for s in st.itertuples()}
    # One line per unordered pair is enough for review.
    und = labels[labels.origin < labels.destination]

    m = folium.Map(location=[25.20, 55.27], zoom_start=12, tiles="OpenStreetMap")
    fg_toll = folium.FeatureGroup(name="Toll-substituting pairs", show=True)
    fg_ctrl = folium.FeatureGroup(name="Control pairs", show=False)
    for r in und.itertuples():
        line = folium.PolyLine(
            [ll[r.origin], ll[r.destination]],
            color="#d62728" if r.toll_substituting else "#7f7f7f",
            weight=1.2, opacity=0.45,
            tooltip=f"{r.origin} - {r.destination}: "
                    f"{r.gates_crossed or 'no gate'} ({r.distance_km} km)",
        )
        line.add_to(fg_toll if r.toll_substituting else fg_ctrl)
    fg_toll.add_to(m)
    fg_ctrl.add_to(m)
    for g in sc.itertuples():
        xy = [(y, x) for x, y in g.geometry.coords]
        folium.PolyLine(xy, color="#000000", weight=5,
                        tooltip=f"Gate: {g.gate} (opened {g.opened.date()})").add_to(m)
    for s in st.itertuples():
        folium.CircleMarker((s.geometry.y, s.geometry.x), radius=4, color="#1f77b4",
                            fill=True, tooltip=f"{s.station} ({s.line})").add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(fig_dir / "od_map.html"))

    fig, ax = plt.subplots(figsize=(8, 8))
    for r in und.itertuples():
        (y1, x1), (y2, x2) = ll[r.origin], ll[r.destination]
        ax.plot([x1, x2], [y1, y2], lw=0.4, alpha=0.35,
                color="#d62728" if r.toll_substituting else "#bbbbbb",
                zorder=2 if r.toll_substituting else 1)
    sc.plot(ax=ax, color="black", linewidth=3, zorder=3)
    for g in sc.itertuples():
        c = g.geometry.centroid
        ax.annotate(g.gate, (c.x, c.y), fontsize=7, xytext=(4, 4),
                    textcoords="offset points", zorder=5)
    st.plot(ax=ax, color="#1f77b4", markersize=12, zorder=4)
    ax.set_title("OD pairs: toll-substituting (red) vs control (grey)\n"
                 "Simulated study; approximate station and gate positions", fontsize=10)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(fig_dir / "od_map.png", dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> pd.DataFrame:
    p = argparse.ArgumentParser()
    p.add_argument("--buffer-m", type=float, default=0.0)
    p.add_argument("--no-maps", action="store_true")
    a = p.parse_args(argv)

    stations, gates = load_inputs()
    screens = screen_lines(gates)
    labels = label_pairs(stations, screens, a.buffer_m)
    labels.to_csv(DATA / "od_labels.csv", index=False)
    if not a.no_maps:
        build_maps(stations, screens, labels)

    n = len(labels)
    t = labels.toll_substituting.sum()
    print(f"{n} ordered OD pairs; {t} toll-substituting ({t / n:.0%}); "
          f"{labels.crosses_new_gate.sum()} cross a gate opened in late 2024")
    print("\nPairs crossing each gate:")
    print(labels.gates_crossed.str.split("|").explode().replace("", pd.NA).dropna()
          .value_counts().to_string())
    return labels


if __name__ == "__main__":
    main()
