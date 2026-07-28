#!/usr/bin/env python3
"""Validate an Encore test report against its plan and emit JSON/JUnit."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--json", required=True, dest="json_output", type=Path)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("reports", nargs="+", type=Path)
    return parser.parse_args()


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = parse_args()
    planned = load_json(args.plan)
    if not isinstance(planned, list) or not all(isinstance(item, str) for item in planned):
        raise ValueError("test plan must be a JSON array of test IDs")
    if len(planned) != len(set(planned)):
        raise ValueError("test plan contains duplicate IDs")

    records: list[dict[str, object]] = []
    if len(args.reports) != 1:
        raise ValueError(f"expected one complete test report, got {len(args.reports)}")
    for path in args.reports:
        report = load_json(path)
        if not isinstance(report, dict) or report.get("schema") != 1:
            raise ValueError(f"{path}: unsupported report schema")
        tests = report.get("tests")
        if not isinstance(tests, list):
            raise ValueError(f"{path}: malformed test report")
        for record in tests:
            if not isinstance(record, dict):
                raise ValueError(f"{path}: malformed test record")
            records.append(record)

    observed_ids = [record.get("id") for record in records]
    if not all(isinstance(item, str) for item in observed_ids):
        raise ValueError("test record has a non-string ID")
    duplicates = sorted({item for item in observed_ids if observed_ids.count(item) > 1})
    missing = sorted(set(planned) - set(observed_ids))
    unexpected = sorted(set(observed_ids) - set(planned))
    if duplicates or missing or unexpected:
        raise ValueError(
            f"test-set mismatch: duplicates={duplicates}, missing={missing}, "
            f"unexpected={unexpected}"
        )

    records.sort(key=lambda record: str(record["id"]))
    failures = sum(record.get("status") != "passed" for record in records)
    duration_ms = sum(int(record.get("duration_ms", 0)) for record in records)
    merged = {
        "schema": 1,
        "summary": {
            "selected": len(records),
            "passed": len(records) - failures,
            "failed": failures,
            "duration_ms": duration_ms,
        },
        "tests": records,
    }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    suite = ET.Element(
        "testsuite",
        {
            "name": "encore",
            "tests": str(len(records)),
            "failures": str(failures),
            "time": f"{duration_ms / 1000:.3f}",
        },
    )
    for record in records:
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "name": str(record["id"]),
                "classname": "encore",
                "time": f"{int(record.get('duration_ms', 0)) / 1000:.3f}",
            },
        )
        if record.get("status") != "passed":
            failure = ET.SubElement(case, "failure", {"message": str(record.get("message", ""))})
            failure.text = str(record.get("message", ""))
    tree = ET.ElementTree(suite)
    ET.indent(tree, space="  ")
    args.junit.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.junit, encoding="utf-8", xml_declaration=True)

    if failures:
        print(f"{failures} test(s) failed", file=sys.stderr)
        return 1
    print(f"validated {len(records)} tests")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
