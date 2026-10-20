#!/usr/bin/env python3
"""Require every discovered test exactly once across successful CI shards."""
import argparse
from collections import Counter
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('inventory', type=Path)
parser.add_argument('reports', type=Path)
parser.add_argument('--count', type=int, required=True)
args = parser.parse_args()
expected = json.loads(args.inventory.read_text(encoding='utf-8'))
if not isinstance(expected, list) or len(expected) != len(set(expected)) or not expected:
    raise SystemExit('Invalid or empty test inventory')
paths = sorted(args.reports.rglob('test-report.json'))
if len(paths) != args.count:
    raise SystemExit(f'Expected {args.count} reports, got {len(paths)}')
observed = []
for path in paths:
    report = json.loads(path.read_text(encoding='utf-8'))
    summary = report['summary']
    records = report['tests']
    if (summary['failed'] != 0 or summary['selected'] != len(records) or
            summary['passed'] != len(records) or
            any(test['status'] != 'passed' for test in records)):
        raise SystemExit('Incomplete or failed test report: ' + str(path))
    observed.extend(test['id'] for test in records)
counts = Counter(observed)
missing = set(expected) - counts.keys()
unexpected = counts.keys() - set(expected)
duplicates = {name for name, count in counts.items() if count != 1}
if missing or unexpected or duplicates:
    raise SystemExit(f'Test partition mismatch: missing={sorted(missing)}, '
                     f'unexpected={sorted(unexpected)}, duplicates={sorted(duplicates)}')
print(f'Verified {len(expected)} tests exactly once in {args.count} shards')
