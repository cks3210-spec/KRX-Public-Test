#!/usr/bin/env python3
"""Observational diagnostics for VERIFIED follow-ups; not causal attribution."""
import csv
import gzip
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "data" / "daily_70d.csv.gz"
CANDIDATES = ROOT / "candidate_history.csv"
FOLLOWUP = ROOT / "trade_followup.csv"
OUTPUT = ROOT / "trade_failure_analysis.csv"
FIELDS = [
    "recommendation_id", "source_group", "stock_code", "snapshot_date",
    "horizon_trading_days", "evaluation_date", "raw_return_pct",
    "outcome", "analysis_status", "entry_ma5", "entry_ma10", "entry_ma20",
    "exit_ma5", "exit_ma10", "exit_ma20", "entry_below_ma20",
    "exit_below_ma5", "exit_below_ma10", "exit_below_ma20",
    "volume_before_5d_avg", "volume_after_5d_avg", "volume_change_pct",
    "zero_volume_in_window", "early_5d_return_pct", "worst_close_drawdown_pct",
    "observed_patterns", "notes",
]

def number(value):
    try:
        n = float(str(value).replace(",", "").strip())
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None

def read_csv(path, compressed=False):
    if not path.is_file():
        raise SystemExit(f"Required input missing: {path}")
    opener = gzip.open if compressed else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def mean(vals):
    return sum(vals) / len(vals) if vals else None

def fmt(value):
    return "" if value is None else f"{value:.4f}"

def main():
    candidates = read_csv(CANDIDATES)
    followups = read_csv(FOLLOWUP)
    prices = read_csv(DATA, compressed=True)
    candidate_by_id = {}
    for c in candidates:
        rid = c.get("record_id", "").strip()
        if not rid or rid in candidate_by_id:
            raise SystemExit(f"Missing or duplicate candidate ID: {rid}")
        candidate_by_id[rid] = c

    per_stock = defaultdict(dict)
    for p in prices:
        code = p.get("ISU_CD", "").strip().zfill(6)
        day = p.get("BAS_DD", "").strip()
        close, volume = number(p.get("TDD_CLSPRC")), number(p.get("ACC_TRDVOL"))
        if not code or len(day) != 8 or close is None or close <= 0 or volume is None or volume < 0:
            continue
        if day in per_stock[code]:
            raise SystemExit(f"Duplicate price record: {code} {day}")
        per_stock[code][day] = (close, volume)
    histories = {code: sorted(days.items()) for code, days in per_stock.items()}
    seen = set()
    results = []
    for f in followups:
        if f.get("status", "").strip() != "VERIFIED":
            continue
        rid = f.get("recommendation_id", "").strip()
        if rid not in candidate_by_id:
            raise SystemExit(f"VERIFIED row has no candidate: {rid}")
        horizon_text = f.get("horizon_trading_days", "").strip()
        if horizon_text not in ("5", "10", "20"):
            raise SystemExit(f"Unexpected horizon: {rid} {horizon_text}")
        horizon = int(horizon_text)
        if (rid, horizon) in seen:
            raise SystemExit(f"Duplicate VERIFIED result: {rid} {horizon}")
        seen.add((rid, horizon))
        c = candidate_by_id[rid]
        code = c["stock_code"].strip().zfill(6)
        entry_day = c["snapshot_date"].strip()
        exit_day = f.get("evaluation_date", "").strip()
        ret = number(f.get("raw_return_pct"))
        if ret is None or not exit_day:
            raise SystemExit(f"Incomplete VERIFIED result: {rid} {horizon}")
        result = dict.fromkeys(FIELDS, "")
        result.update(recommendation_id=rid, source_group=c.get("source_group", ""),
                      stock_code=code, snapshot_date=entry_day,
                      horizon_trading_days=str(horizon), evaluation_date=exit_day,
                      raw_return_pct=fmt(ret),
                      outcome="LOSS" if ret < 0 else ("GAIN" if ret > 0 else "FLAT"))
        history = histories.get(code, [])
        dates = [d for d, _ in history]
        if entry_day not in dates or exit_day not in dates:
            result["analysis_status"] = "INSUFFICIENT_PRICE_HISTORY"
            result["notes"] = "Entry/exit date absent from rolling archive; follow-up result retained."
            results.append(result)
            continue
        i, j = dates.index(entry_day), dates.index(exit_day)
        if j - i != horizon:
            result["analysis_status"] = "SESSION_MISMATCH"
            result["notes"] = "Archive does not contain all expected trading sessions."
            results.append(result)
            continue
        closes = [x[0] for _, x in history]
        volumes = [x[1] for _, x in history]
        if i < 19 or j < 19 or i < 5 or j < 5:
            result["analysis_status"] = "INSUFFICIENT_MA_HISTORY"
            result["notes"] = "Need 20 prior closes and five pre-entry sessions."
            results.append(result)
            continue
        entry_ref = number(f.get("entry_reference"))
        exit_ref = number(f.get("exit_close"))
        if entry_ref is None or exit_ref is None or abs(entry_ref / closes[i] - 1) > 0.0001 or abs(exit_ref / closes[j] - 1) > 0.0001:
            result["analysis_status"] = "PRICE_MISMATCH"
            result["notes"] = "VERIFIED reference prices differ from historical archive."
            results.append(result)
            continue
        ma_e = {n: mean(closes[i-n+1:i+1]) for n in (5, 10, 20)}
        ma_x = {n: mean(closes[j-n+1:j+1]) for n in (5, 10, 20)}
        before = volumes[i-4:i+1]
        after = volumes[j-4:j+1]
        # Volume zero may reflect suspension, not necessarily weakening.
        has_zero = any(v == 0 for v in volumes[i:j+1])
        vol_change = (mean(after) / mean(before) - 1) * 100 if mean(before) and not has_zero else None
        early = (closes[i+5] / closes[i] - 1) * 100 if j >= i+5 else None
        worst = (min(closes[i:j+1]) / closes[i] - 1) * 100
        patterns = []
        if closes[j] < ma_x[5]:
            patterns.append("EXIT_BELOW_MA5")
        if closes[j] < ma_x[10]:
            patterns.append("EXIT_BELOW_MA10")
        if closes[j] < ma_x[20]:
            patterns.append("EXIT_BELOW_MA20")
        if vol_change is not None and vol_change <= -30:
            patterns.append("VOLUME_5D_DROP_30PCT")
        if early is not None and early <= -3:
            patterns.append("EARLY_5D_DROP_3PCT")
        result.update(
            analysis_status="ANALYZED",
            entry_ma5=fmt(ma_e[5]), entry_ma10=fmt(ma_e[10]), entry_ma20=fmt(ma_e[20]),
            exit_ma5=fmt(ma_x[5]), exit_ma10=fmt(ma_x[10]), exit_ma20=fmt(ma_x[20]),
            entry_below_ma20=str(closes[i] < ma_e[20]).lower(),
            exit_below_ma5=str(closes[j] < ma_x[5]).lower(),
            exit_below_ma10=str(closes[j] < ma_x[10]).lower(),
            exit_below_ma20=str(closes[j] < ma_x[20]).lower(),
            volume_before_5d_avg=fmt(mean(before)),
            volume_after_5d_avg=fmt(mean(after)),
            volume_change_pct=fmt(vol_change),
            zero_volume_in_window=str(has_zero).lower(),
            early_5d_return_pct=fmt(early),
            worst_close_drawdown_pct=fmt(worst),
            observed_patterns=";".join(patterns),
            notes="Observational co-occurrences only; not causal proof. "
                  "Close-based measures; no trade costs. Volume change blank when zero volume detected."
        )
        results.append(result)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="",
                                         dir=ROOT, prefix=".failure-", suffix=".csv",
                                         delete=False) as file:
            temp_path = file.name
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(results)
        os.replace(temp_path, OUTPUT)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    counts = defaultdict(int)
    for r in results:
        counts[r["analysis_status"]] += 1
    print(f"verified={len(results)}; statuses={dict(counts)}; output={OUTPUT.name}")
    if not results:
        print("No VERIFIED follow-ups; header-only file written. No failure causes inferred.")

if __name__ == "__main__":
    main()
