"""Tests for the download/aggregate and data-check scripts, on synthetic data."""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_data  # noqa: E402
import download_and_aggregate as dag  # noqa: E402


def write_schema(path: Path, **over) -> Path:
    schema = {
        "columns": {"origin": "entry_station", "destination": "exit_station",
                    "timestamp": "txn_time", "date": None, "time": None},
        "row_filter": None, "date_format": None, "time_format": None,
        "timestamp_format": None,
    }
    schema.update(over)
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    return path


def write_raw(raw_dir: Path, day: dt.date, rows: list[tuple]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["entry_station", "exit_station", "txn_time", "mode"])
    p = raw_dir / f"metro_{day.strftime('%Y%m%d')}.csv"
    df.to_csv(p, index=False)
    return p


@pytest.fixture
def setup(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    schema = write_schema(tmp_path / "schema.yaml")
    d1, d2 = dt.date(2025, 1, 6), dt.date(2025, 1, 7)
    write_raw(raw, d1, [
        ("Union", "BurJuman", "2025-01-06 07:15:00", "metro"),
        ("Union", "BurJuman", "2025-01-06 07:45:00", "metro"),
        ("Union", "BurJuman", "2025-01-06 18:05:00", "metro"),
        (" Union ", "Mall of the Emirates", "2025-01-06 07:30:00", "metro"),
        ("", "BurJuman", "2025-01-06 08:00:00", "metro"),          # null origin
        ("Union", "BurJuman", "not a time", "metro"),               # bad time
        ("Union", "BurJuman", "2025-01-06 09:00:00", "tram"),
    ] + [("Rigga", "Deira City Centre", "2025-01-06 12:00:00", "metro")] * 40)
    # d2 has no raw file -> should be recorded as missing
    return tmp_path, raw, out, schema, d1, d2


def read_out(out: Path) -> pd.DataFrame:
    return pd.concat(pd.read_parquet(p) for p in (out / "od_hourly").glob("*.parquet"))


def test_aggregates_counts_and_drops(setup):
    _, raw, out, schema, d1, d2 = setup
    manifest = dag.run(d1, d2, raw, out, schema)
    df = read_out(out)
    got = {(r.origin, r.destination, r.hour): r.trips for r in df.itertuples()}
    assert got[("Union", "BurJuman", 7)] == 2
    assert got[("Union", "BurJuman", 18)] == 1
    assert got[("Union", "Mall of the Emirates", 7)] == 1   # whitespace trimmed
    assert got[("Union", "BurJuman", 9)] == 1               # tram kept: no filter set
    m = manifest[d1.isoformat()]
    assert m["status"] == "ok"
    assert m["raw_rows"] == 47
    assert got[("Rigga", "Deira City Centre", 12)] == 40
    assert m["dropped_null_od"] == 1
    assert m["dropped_bad_time"] == 1
    assert manifest[d2.isoformat()]["status"] == "missing"


def test_row_filter(setup):
    tmp, raw, out, _, d1, _ = setup
    schema = write_schema(tmp / "schema_f.yaml", row_filter="mode = 'metro'")
    manifest = dag.run(d1, d1, raw, out, schema)
    df = read_out(out)
    assert 9 not in set(df["hour"])
    assert manifest[d1.isoformat()]["dropped_filter"] == 1


def test_raw_deleted_and_resume_skips(setup, capsys):
    _, raw, out, schema, d1, _ = setup
    dag.run(d1, d1, raw, out, schema)
    assert not list(raw.glob("*.csv")), "raw file should be deleted after processing"
    capsys.readouterr()
    dag.run(d1, d1, raw, out, schema)
    assert "skip (already processed)" in capsys.readouterr().out


def test_keep_raw(setup):
    _, raw, out, schema, d1, _ = setup
    dag.run(d1, d1, raw, out, schema, keep_raw=True)
    assert list(raw.glob("*.csv"))


def test_date_and_time_columns(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    day = dt.date(2025, 2, 3)
    pd.DataFrame({"o": ["A", "A"], "d": ["B", "B"],
                  "txn_date": ["03/02/2025", "03/02/2025"],
                  "txn_hm": ["06:59:59", "07:00:00"]}).to_csv(
        raw / f"x_{day.isoformat()}.csv", index=False)
    schema = write_schema(
        tmp_path / "s.yaml",
        columns={"origin": "o", "destination": "d", "timestamp": None,
                 "date": "txn_date", "time": "txn_hm"},
        date_format="%d/%m/%Y")
    dag.run(day, day, raw, out, schema)
    df = read_out(out)
    assert sorted(df["hour"]) == [6, 7]
    assert set(pd.to_datetime(df["date"]).dt.date) == {day}


def test_wrong_format_is_flagged_and_raw_kept(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    day = dt.date(2025, 1, 6)
    write_raw(raw, day, [("A", "B", "06/01/2025 08:00", "metro")] * 10)
    schema = write_schema(tmp_path / "s.yaml")  # ISO assumed: wrong for this file
    manifest = dag.run(day, day, raw, out, schema)
    assert manifest[day.isoformat()]["status"] == "error"
    assert list(raw.glob("*.csv")), "raw file must be kept so the day can be re-run"
    assert not list((out / "od_hourly").glob("*.parquet"))

    schema = write_schema(tmp_path / "s.yaml", timestamp_format="%d/%m/%Y %H:%M")
    manifest = dag.run(day, day, raw, out, schema)  # retried automatically
    assert manifest[day.isoformat()]["status"] == "ok"
    assert read_out(out)["trips"].sum() == 10


def test_high_drop_share_is_suspect(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    day = dt.date(2025, 1, 6)
    write_raw(raw, day, [("A", "B", "2025-01-06 08:00:00", "metro")] * 8
              + [("", "B", "2025-01-06 08:00:00", "metro")] * 2)
    manifest = dag.run(day, day, raw, out, write_schema(tmp_path / "s.yaml"))
    assert manifest[day.isoformat()]["status"] == "suspect"


def test_incomplete_schema_fails(tmp_path):
    p = write_schema(tmp_path / "s.yaml",
                     columns={"origin": None, "destination": None, "timestamp": None})
    with pytest.raises(SystemExit):
        dag.load_schema(p)


def test_check_data_flags_drop_and_missing(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    schema = write_schema(tmp_path / "schema.yaml")
    start = dt.date(2025, 1, 1)
    end = start + dt.timedelta(days=41)
    outage = start + dt.timedelta(days=35)
    gap = start + dt.timedelta(days=20)
    for i in range((end - start).days + 1):
        day = start + dt.timedelta(days=i)
        if day == gap:
            continue
        n = 2 if day == outage else 10
        ts = f"{day.isoformat()} 08:00:00"
        rows = [("A", "B", ts, "metro")] * n
        if i < 30:
            rows.append(("OldName", "B", ts, "metro"))
        else:
            rows.append(("NewName", "B", ts, "metro"))
        write_raw(raw, day, rows)
    dag.run(start, end, raw, out, schema)

    report = tmp_path / "checks.md"
    check_data.main(["--start", start.isoformat(), "--end", end.isoformat(),
                     "--out-dir", str(out), "--report", str(report)])
    text = report.read_text(encoding="utf-8")
    assert gap.isoformat() in text
    assert outage.isoformat() in text
    assert "OldName" in text and "NewName" in text
