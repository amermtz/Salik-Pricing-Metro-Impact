"""Download RTA metro ridership day by day and aggregate it to OD pair x date x hour.

The raw daily transaction files are very large, so each day is processed on its
own: fetch (or pick up) the raw file, aggregate it with DuckDB, write one Parquet
file, record stats in a manifest, and delete the raw file.

The script is resumable: a day that already has a Parquet file and a manifest
entry is skipped.

Usage
-----
1. Inspect the schema of one raw file and fill in schema.yaml:

       python scripts/download_and_aggregate.py inspect data/raw/<file>.csv

2. Process a date range. Either point it at a folder of files you downloaded
   by hand (file names must contain the date as YYYY-MM-DD or YYYYMMDD):

       python scripts/download_and_aggregate.py run --start 2024-07-01 --end 2025-06-30

   or give it a URL template with a {date} placeholder (and optionally
   {yyyymmdd}) to download each day automatically:

       python scripts/download_and_aggregate.py run --start 2024-07-01 --end 2025-06-30 \
           --url-template "https://.../metro_ridership_{date}.csv"

   If the source needs a token, set the environment variable DUBAI_PULSE_TOKEN;
   it is sent as a Bearer token. Never commit tokens.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb
import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RAW = REPO / "data" / "raw"
DEFAULT_OUT = REPO / "data" / "processed"
DEFAULT_SCHEMA = REPO / "schema.yaml"

MANIFEST_FIELDS = [
    "file_date",
    "status",
    "raw_file",
    "raw_rows",
    "dropped_null_od",
    "dropped_bad_time",
    "dropped_filter",
    "kept_rows",
    "n_od_pairs",
    "total_trips",
    "min_trip_date",
    "max_trip_date",
    "processed_at",
    "note",
]

# A day is flagged if more than this share of raw rows is dropped for bad
# station or time values (usually a sign that schema.yaml is wrong).
MAX_DROP_SHARE = 0.05


# --------------------------------------------------------------------------- #
# Schema handling
# --------------------------------------------------------------------------- #
def load_schema(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    cols = schema.get("columns", {})
    missing = [k for k in ("origin", "destination") if not cols.get(k)]
    has_ts = bool(cols.get("timestamp"))
    has_dt = bool(cols.get("date")) and bool(cols.get("time"))
    if missing or not (has_ts or has_dt):
        raise SystemExit(
            f"schema.yaml is incomplete ({path}). Set columns.origin, "
            "columns.destination and either columns.timestamp or columns.date + "
            "columns.time. Run the `inspect` command on a raw file first."
        )
    return schema


def q(name: str) -> str:
    """Quote a column identifier for DuckDB."""
    return '"' + name.replace('"', '""') + '"'


def time_exprs(schema: dict) -> tuple[str, str]:
    """Return SQL expressions for (trip_date, trip_hour). NULL when unparseable."""
    c = schema["columns"]
    if c.get("timestamp"):
        col = q(c["timestamp"])
        fmt = schema.get("timestamp_format")
        ts = (
            f"try_strptime(CAST({col} AS VARCHAR), '{fmt}')"
            if fmt
            else f"TRY_CAST({col} AS TIMESTAMP)"
        )
        return f"CAST({ts} AS DATE)", f"hour({ts})"

    dcol, tcol = q(c["date"]), q(c["time"])
    dfmt, tfmt = schema.get("date_format"), schema.get("time_format")
    d = (
        f"CAST(try_strptime(CAST({dcol} AS VARCHAR), '{dfmt}') AS DATE)"
        if dfmt
        else f"TRY_CAST({dcol} AS DATE)"
    )
    t = (
        f"CAST(try_strptime(CAST({tcol} AS VARCHAR), '{tfmt}') AS TIME)"
        if tfmt
        else f"TRY_CAST({tcol} AS TIME)"
    )
    return d, f"hour({t})"


# --------------------------------------------------------------------------- #
# Raw file handling
# --------------------------------------------------------------------------- #
def read_expr(path: Path) -> str:
    p = str(path).replace("\\", "/").replace("'", "''")
    if path.suffix.lower() == ".parquet":
        return f"read_parquet('{p}')"
    # Read every column as text: type auto-detection can silently misread dates
    # (e.g. dd/mm vs mm/dd). Dates and times are parsed explicitly in time_exprs.
    return f"read_csv('{p}', header=true, all_varchar=true)"


def unzip_if_needed(path: Path) -> tuple[Path, list[Path]]:
    """If path is a zip, extract its single data file. Returns (data_file, temp_files)."""
    if path.suffix.lower() != ".zip":
        return path, []
    out_dir = path.parent / (path.stem + "_unzipped")
    with zipfile.ZipFile(path) as z:
        members = [m for m in z.namelist() if m.lower().endswith((".csv", ".parquet"))]
        if len(members) != 1:
            raise RuntimeError(f"{path}: expected one csv/parquet inside zip, found {members}")
        z.extract(members[0], out_dir)
    return out_dir / members[0], [out_dir]


def find_raw_file(raw_dir: Path, day: dt.date) -> Path | None:
    keys = (day.isoformat(), day.strftime("%Y%m%d"))
    hits = sorted(
        p
        for p in raw_dir.glob("*")
        if p.is_file()
        and any(k in p.name for k in keys)
        and p.suffix.lower() in (".csv", ".gz", ".zip", ".parquet")
    )
    if len(hits) > 1:
        raise RuntimeError(f"More than one raw file for {day}: {[h.name for h in hits]}")
    return hits[0] if hits else None


def download(url_template: str, raw_dir: Path, day: dt.date) -> Path | None:
    import requests

    url = url_template.format(date=day.isoformat(), yyyymmdd=day.strftime("%Y%m%d"))
    headers = {}
    token = os.environ.get("DUBAI_PULSE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    suffix = Path(url.split("?")[0]).suffix or ".csv"
    dest = raw_dir / f"metro_{day.isoformat()}{suffix}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        if r.status_code == 404:
            return None
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def manifest_path(out_dir: Path) -> Path:
    return out_dir / "manifest.csv"


def read_manifest(out_dir: Path) -> dict[str, dict]:
    path = manifest_path(out_dir)
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {row["file_date"]: row for row in csv.DictReader(f)}


def write_manifest(out_dir: Path, rows: dict[str, dict]) -> None:
    path = manifest_path(out_dir)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for key in sorted(rows):
            w.writerow({k: rows[key].get(k, "") for k in MANIFEST_FIELDS})
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def aggregate_file(raw: Path, out_file: Path, schema: dict) -> dict:
    """Aggregate one raw file to OD x date x hour trip counts. Returns stats."""
    c = schema["columns"]
    o, d = q(c["origin"]), q(c["destination"])
    date_e, hour_e = time_exprs(schema)
    filt = schema.get("row_filter")
    src = read_expr(raw)

    con = duckdb.connect()
    try:
        con.execute(f"CREATE TEMP VIEW raw AS SELECT * FROM {src}")
        keep_filter = f"({filt})" if filt else "TRUE"
        con.execute(
            f"""
            CREATE TEMP TABLE staged AS
            SELECT
                NULLIF(trim(CAST({o} AS VARCHAR)), '') AS origin,
                NULLIF(trim(CAST({d} AS VARCHAR)), '') AS destination,
                {date_e} AS trip_date,
                {hour_e} AS trip_hour,
                COALESCE({keep_filter}, FALSE) AS keep
            FROM raw
            """
        )
        stats = con.execute(
            """
            SELECT
                count(*) AS raw_rows,
                count(*) FILTER (WHERE NOT keep) AS dropped_filter,
                count(*) FILTER (WHERE keep AND (origin IS NULL OR destination IS NULL))
                    AS dropped_null_od,
                count(*) FILTER (WHERE keep AND origin IS NOT NULL AND destination IS NOT NULL
                                 AND (trip_date IS NULL OR trip_hour IS NULL))
                    AS dropped_bad_time
            FROM staged
            """
        ).fetchone()
        raw_rows, dropped_filter, dropped_null_od, dropped_bad_time = stats

        out_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_file.with_suffix(".parquet.tmp")
        tmp_sql = str(tmp).replace("\\", "/").replace("'", "''")
        con.execute(
            f"""
            COPY (
                SELECT origin, destination, trip_date AS date,
                       CAST(trip_hour AS TINYINT) AS hour,
                       count(*) AS trips
                FROM staged
                WHERE keep AND origin IS NOT NULL AND destination IS NOT NULL
                      AND trip_date IS NOT NULL AND trip_hour IS NOT NULL
                GROUP BY ALL
                ORDER BY date, hour, origin, destination
            ) TO '{tmp_sql}' (FORMAT parquet, COMPRESSION zstd)
            """
        )
        agg = con.execute(
            f"""
            SELECT count(*), COALESCE(sum(trips), 0), min(date), max(date),
                   count(DISTINCT (origin, destination))
            FROM read_parquet('{tmp_sql}')
            """
        ).fetchone()
    finally:
        con.close()
    tmp.replace(out_file)

    _, total_trips, min_d, max_d, n_pairs = agg
    return {
        "raw_rows": raw_rows,
        "dropped_null_od": dropped_null_od,
        "dropped_bad_time": dropped_bad_time,
        "dropped_filter": dropped_filter,
        "kept_rows": total_trips,
        "n_od_pairs": n_pairs,
        "total_trips": total_trips,
        "min_trip_date": min_d.isoformat() if min_d else "",
        "max_trip_date": max_d.isoformat() if max_d else "",
    }


def daterange(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def run(
    start: dt.date,
    end: dt.date,
    raw_dir: Path = DEFAULT_RAW,
    out_dir: Path = DEFAULT_OUT,
    schema_path: Path = DEFAULT_SCHEMA,
    url_template: str | None = None,
    keep_raw: bool = False,
    retry_missing: bool = False,
) -> dict[str, dict]:
    schema = load_schema(schema_path)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(out_dir)

    for day in daterange(start, end):
        key = day.isoformat()
        out_file = out_dir / "od_hourly" / f"date={key}.parquet"
        prev = manifest.get(key)
        if prev and prev["status"] == "ok" and out_file.exists():
            print(f"{key}  skip (already processed)")
            continue
        if prev and prev["status"] == "missing" and not retry_missing:
            print(f"{key}  skip (marked missing; use --retry-missing to try again)")
            continue

        raw = find_raw_file(raw_dir, day)
        if raw is None and url_template:
            raw = download(url_template, raw_dir, day)
        if raw is None:
            print(f"{key}  MISSING raw file")
            manifest[key] = {"file_date": key, "status": "missing",
                             "processed_at": dt.datetime.now().isoformat(timespec="seconds")}
            write_manifest(out_dir, manifest)
            continue

        data_file, temps = unzip_if_needed(raw)
        try:
            stats = aggregate_file(data_file, out_file, schema)
        except Exception as exc:  # keep going; record the failure
            print(f"{key}  ERROR {exc}", file=sys.stderr)
            manifest[key] = {"file_date": key, "status": "error", "raw_file": raw.name,
                             "processed_at": dt.datetime.now().isoformat(timespec="seconds")}
            write_manifest(out_dir, manifest)
            for t in temps:
                shutil.rmtree(t, ignore_errors=True)
            continue

        bad = stats["dropped_null_od"] + stats["dropped_bad_time"]
        considered = stats["raw_rows"] - stats["dropped_filter"]
        if stats["total_trips"] == 0:
            status, note = "error", "no usable trips; check schema.yaml formats"
        elif considered and bad / considered > MAX_DROP_SHARE:
            status, note = "suspect", f"{bad / considered:.1%} of rows dropped"
        else:
            status, note = "ok", ""
        manifest[key] = {"file_date": key, "status": status, "raw_file": raw.name, **stats,
                         "processed_at": dt.datetime.now().isoformat(timespec="seconds"),
                         "note": note}
        write_manifest(out_dir, manifest)
        for t in temps:
            shutil.rmtree(t, ignore_errors=True)
        if status != "ok":
            # Keep the raw file so the day can be re-run after fixing schema.yaml.
            out_file.unlink(missing_ok=True)
            print(f"{key}  {status.upper()}: {note} (raw file kept)", file=sys.stderr)
            continue
        if not keep_raw:
            raw.unlink()
        print(f"{key}  ok  trips={stats['total_trips']:,}  pairs={stats['n_od_pairs']:,}  "
              f"dropped(null_od={stats['dropped_null_od']}, bad_time={stats['dropped_bad_time']}, "
              f"filter={stats['dropped_filter']})")
    return manifest


# --------------------------------------------------------------------------- #
# Inspect
# --------------------------------------------------------------------------- #
def inspect(path: Path, n: int = 5) -> None:
    data_file, temps = unzip_if_needed(path)
    con = duckdb.connect()
    try:
        src = read_expr(data_file)
        print(f"File: {path}\n")
        print("Columns and detected types:")
        print(con.execute(f"DESCRIBE SELECT * FROM {src}").df()[["column_name", "column_type"]]
              .to_string(index=False))
        print(f"\nFirst {n} rows:")
        print(con.execute(f"SELECT * FROM {src} LIMIT {n}").df().to_string(index=False))
        print(f"\nRow count: {con.execute(f'SELECT count(*) FROM {src}').fetchone()[0]:,}")
        print("\nDistinct values (up to 15) for low-cardinality text columns:")
        cols = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
        for name, ctype, *_ in cols:
            if "VARCHAR" not in ctype:
                continue
            k = con.execute(f"SELECT count(DISTINCT {q(name)}) FROM {src}").fetchone()[0]
            if k <= 15:
                vals = [r[0] for r in con.execute(
                    f"SELECT DISTINCT {q(name)} FROM {src} ORDER BY 1").fetchall()]
                print(f"  {name}: {vals}")
            else:
                print(f"  {name}: {k:,} distinct values")
    finally:
        con.close()
        for t in temps:
            shutil.rmtree(t, ignore_errors=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="print the schema and sample rows of one raw file")
    pi.add_argument("path", type=Path)

    pr = sub.add_parser("run", help="download/aggregate a date range (resumable)")
    pr.add_argument("--start", type=dt.date.fromisoformat, required=True)
    pr.add_argument("--end", type=dt.date.fromisoformat, required=True)
    pr.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    pr.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    pr.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    pr.add_argument("--url-template", default=None)
    pr.add_argument("--keep-raw", action="store_true", help="do not delete raw files")
    pr.add_argument("--retry-missing", action="store_true")

    a = p.parse_args(argv)
    if a.cmd == "inspect":
        inspect(a.path)
    else:
        run(a.start, a.end, a.raw_dir, a.out_dir, a.schema, a.url_template,
            a.keep_raw, a.retry_missing)


if __name__ == "__main__":
    main()
