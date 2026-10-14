#!/usr/bin/env python3
"""Summarize VERIFIED V/G/VG follow-ups; never fabricate missing results."""
import csv
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANDIDATES = ROOT / "candidate_history.csv"
FOLLOWUP = ROOT / "trade_followup.csv"
OUT = ROOT / "trade_performance_summary.csv"
FIELDS = ["asof_date", "source_group", "judgment", "sample_size", "horizon",
          "win_rate_pct", "avg_return_pct", "avg_excess_return_pp",
          "avg_max_drawdown_pct", "notes"]
GROUPS = ("V", "G", "VG")
HORIZONS = (5, 10, 20)

def numeric(value):
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None

def read_csv(path):
    if not path.is_file():
        raise SystemExit(f"Missing required file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))

def write_atomic(rows):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="",
                                         dir=ROOT, prefix=".performance-", suffix=".csv",
                                         delete=False) as file:
            temporary = file.name
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, OUT)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)

def main():
    candidates = read_csv(CANDIDATES)
    followups = read_csv(FOLLOWUP)
    groups_by_id = {}
    dates = []
    for candidate in candidates:
        record_id = candidate.get("record_id", "").strip()
        group = candidate.get("source_group", "").strip()
        day = candidate.get("snapshot_date", "").strip()
        if not record_id or group not in GROUPS:
            raise SystemExit(f"Invalid candidate identity/group: {record_id}")
        if record_id in groups_by_id:
            raise SystemExit(f"Duplicate candidate record_id: {record_id}")
        groups_by_id[record_id] = group
        if len(day) == 8 and day.isdigit():
            dates.append(day)
    asof = max(dates, default="")
    buckets = defaultdict(list)
    observed = set()
    verified_count = 0
    for item in followups:
        if item.get("status", "").strip() != "VERIFIED":
            continue
        rid = item.get("recommendation_id", "").strip()
        if rid not in groups_by_id:
            raise SystemExit(f"VERIFIED follow-up missing candidate: {rid}")
        try:
            horizon = int(item.get("horizon_trading_days", ""))
        except ValueError:
            raise SystemExit(f"Invalid horizon for {rid}")
        if horizon not in HORIZONS:
            raise SystemExit(f"Unsupported horizon {horizon} for {rid}")
        key = (rid, horizon)
        if key in observed:
            raise SystemExit(f"Duplicate VERIFIED follow-up: {key}")
        observed.add(key)
        raw = numeric(item.get("raw_return_pct"))
        drawdown = numeric(item.get("max_drawdown_pct"))
        excess = numeric(item.get("excess_return_pp"))
        if raw is None or drawdown is None or not item.get("evaluation_date", "").strip():
            raise SystemExit(f"Incomplete VERIFIED follow-up: {key}")
        buckets[(groups_by_id[rid], horizon)].append((raw, drawdown, excess))
        verified_count += 1
    output = []
    for group in GROUPS:
        for horizon in HORIZONS:
            data = buckets[(group, horizon)]
            if not data:
                continue
            n = len(data)
            excesses = [x[2] for x in data if x[2] is not None]
            output.append({
                "asof_date": asof,
                "source_group": group,
                "judgment": "OBSERVATION_ONLY",
                "sample_size": n,
                "horizon": horizon,
                "win_rate_pct": f"{sum(x[0] > 0 for x in data) / n * 100:.2f}",
                "avg_return_pct": f"{sum(x[0] for x in data) / n:.4f}",
                "avg_excess_return_pp": (f"{sum(excesses) / n:.4f}" if len(excesses) == n else ""),
                "avg_max_drawdown_pct": f"{sum(x[1] for x in data) / n:.4f}",
                "notes": "Close-based drawdown; gross returns; no trade costs. "
                         "Excess return blank unless verified for every sample. "
                         "G includes trend-maintained candidates; not a buy recommendation."
            })
    write_atomic(output)
    print(f"candidate_records={len(candidates)}; verified_followups={verified_count}; "
          f"summary_rows={len(output)}; asof_date={asof or 'unknown'}")
    if not output:
        print("No VERIFIED follow-ups: header-only summary retained (no invented metrics).")

if __name__ == "__main__":
    main()
