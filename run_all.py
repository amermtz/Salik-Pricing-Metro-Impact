"""Run the whole study end to end.

    python run_all.py              # everything
    python run_all.py --from did   # resume from a step
    python run_all.py --skip-sim   # use existing data/processed (e.g. real data)

Steps: labels -> simulate -> checks -> did -> its -> counterfactual -> placebo
       -> recovery -> memo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = sys.executable

STEPS = [
    ("labels", ["src/label_od_pairs.py"]),
    ("simulate", ["scripts/simulate_ridership.py"]),
    ("checks", ["scripts/check_data.py", "--start", "2024-07-01", "--end", "2025-06-30"]),
    ("did", ["src/did.py"]),
    ("its", ["src/its.py"]),
    ("counterfactual", ["src/counterfactual.py"]),
    ("placebo", ["src/placebo.py"]),
    ("recovery", ["src/recovery.py"]),
    ("memo", ["report/build_memo.py"]),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", choices=[s for s, _ in STEPS])
    ap.add_argument("--skip-sim", action="store_true")
    a = ap.parse_args()

    names = [s for s, _ in STEPS]
    first = names.index(a.start) if a.start else 0
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO / "src"),
           "PYTHONWARNINGS": "ignore::FutureWarning,ignore::UserWarning"}
    for name, cmd in STEPS[first:]:
        if a.skip_sim and name == "simulate":
            continue
        print(f"\n=== {name} ===", flush=True)
        t0 = time.time()
        r = subprocess.run([PY, *cmd], cwd=REPO, env=env)
        if r.returncode != 0:
            sys.exit(f"Step '{name}' failed (exit {r.returncode}). "
                     f"Fix it and resume with: python run_all.py --from {name}")
        print(f"--- {name} done in {time.time() - t0:.0f}s", flush=True)
    print("\nAll steps finished. See results/summary.md and report/memo.md")


if __name__ == "__main__":
    main()
