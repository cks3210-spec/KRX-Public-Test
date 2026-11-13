#!/usr/bin/env python3
"""Stage60 orchestrator: reuse existing Stage56-59 scripts, never fabricate grades.
Runs only existing stages, records missing dependencies as BLOCKED.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'stage60_output'
STAGES = [
    (56, 'scripts/v5_stage56_existing_data_audit.py', 'stage56_output/status.json'),
    (56, 'scripts/v5_stage56_financial_basis_audit.py', 'stage56_financial_basis_output/status.json'),
    (57, 'scripts/v5_stage57_provisional_regrade.py', 'stage57_output/status.json'),
    (58, 'scripts/v5_stage58_price_scenarios.py', 'stage58_output/status.json'),
    (59, 'scripts/v5_stage59_performance_tracker.py', 'stage59_output/status.json'),
]

def main():
    OUT.mkdir(exist_ok=True)
    status = {'stage': 60, 'mode': 'EXISTING_COMPONENT_ORCHESTRATION',
              'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'stages': [], 'pipeline_complete': False,
              'official_valuation_verified': False, 'trade_signals_released': 0,
              'warnings': ['Development integration only; no final investment-grade certification.']}
    gate_path = OUT / 'market_gate_status.json'
    if not gate_path.exists():
        status['state'] = 'BLOCKED_MARKET_GATE_NOT_RUN'
        (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        raise SystemExit(1)
    gate = json.loads(gate_path.read_text(encoding='utf-8'))
    if gate.get('state') == 'KRX_CLOSED':
        status['state'] = 'SKIPPED_KRX_HOLIDAY'
        (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        return
    if gate.get('state') != 'FRESH_KRX_SNAPSHOT_VALIDATED' or not gate.get('market_data_fresh'):
        status['state'] = 'BLOCKED_STALE_OR_UNVERIFIED_MARKET_DATA'
        (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        raise SystemExit(1)
    status['market_data_date'] = gate['target_date']
    blocked = False
    for stage, script, result in STAGES:
        path = ROOT / script
        item = {'stage': stage, 'script': script, 'status_file': result}
        if not path.is_file():
            item['state'] = 'BLOCKED_MISSING_SCRIPT'
            blocked = True
        else:
            try:
                run = subprocess.run([sys.executable, str(path)], cwd=ROOT,
                                     capture_output=True, text=True, timeout=180)
                item['exit_code'] = run.returncode
                item['stdout_tail'] = run.stdout[-1000:]
                item['stderr_tail'] = run.stderr[-1000:]
                result_path = ROOT / result
                if run.returncode == 0 and result_path.exists():
                    data = json.loads(result_path.read_text(encoding='utf-8'))
                    item['state'] = 'EXECUTED' if not data.get('error') else 'FAILED_RESULT'
                    item['result_error'] = data.get('error')
                else:
                    item['state'] = 'FAILED'
                if item['state'] != 'EXECUTED':
                    blocked = True
            except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
                item['state'] = 'FAILED'
                item['error'] = str(exc)[:300]
                blocked = True
        status['stages'].append(item)
    status['pipeline_complete'] = not blocked
    status['state'] = 'DEVELOPMENT_CHAIN_EXECUTED' if not blocked else 'BLOCKED_INCOMPLETE_CHAIN'
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'state': status['state'], 'stages': [(x['stage'], x['state']) for x in status['stages']]}, ensure_ascii=False))
    if blocked:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
