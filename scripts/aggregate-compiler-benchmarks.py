#!/usr/bin/env python3
"""Combine complete CI repetition pairs without pairing different runners."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import statistics

spec = importlib.util.spec_from_file_location("compiler_benchmarks", Path(__file__).with_name("benchmark-compiler-tests.py"))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def aggregate(documents, repetitions):
    if len(documents) != repetitions:
        raise ValueError(f"expected {repetitions} repetition reports, found {len(documents)}")
    first = documents[0]
    if set(first["variants"]) != {"baseline", "candidate"}:
        raise ValueError("each report must contain both baseline and candidate")
    result = copy.deepcopy(first)
    result.update(schema=3, completed=True, first_repetition=1, repetitions=repetitions,
                  samples=[], environments=[], summary=[], paired_speedups=[])
    result.pop("environment", None)
    result["pairing_policy"] = (
        "Each repetition measures both variants on one runner. CI repetitions use independent runners; "
        "the primary speedup is the median of within-runner baseline/candidate ratios."
    )
    seen = set()
    ratios = {}
    for document in documents:
        repetition = document["first_repetition"]
        if repetition in seen or repetition not in range(1, repetitions + 1):
            raise ValueError("duplicate or unexpected repetition ID")
        seen.add(repetition)
        if document["schema"] != 2 or document["repetitions"] != 1 or not document.get("completed") or document["failed"]:
            raise ValueError("cannot aggregate a failed or incomplete repetition")
        for key in ("benchmark_script_sha256", "profile", "scenario", "warm", "jobs", "test_catalogs"):
            if document[key] != first[key]:
                raise ValueError("repetition inputs or selected tests changed: " + key)
        if set(document["variants"]) != set(first["variants"]):
            raise ValueError("compiler variants changed")
        for variant in first["variants"]:
            for key in ("compiler_sha256", "compiler_version", "source_commit", "source_snapshot_sha256"):
                if document["variants"][variant][key] != first["variants"][variant][key]:
                    raise ValueError("compiler/source identity changed: " + variant + "/" + key)
        for key in ("architecture", "logical_cpus"):
            if document["environment"][key] != first["environment"][key]:
                raise ValueError("runner architecture or worker budget changed: " + key)
        keys = [benchmark.sample_key(sample) for sample in document["samples"]]
        if len(keys) != len(set(keys)) or set(keys) != benchmark.expected_sample_keys(document):
            raise ValueError("missing or duplicated samples in repetition")
        if not all(benchmark.sample_complete(sample, document["warm"]) for sample in document["samples"]):
            raise ValueError("incomplete cold/warm pair")
        result["samples"].extend(copy.deepcopy(document["samples"]))
        result["environments"].append({"repetition": repetition, **document["environment"]})
        indexed = {(sample["effective_jobs"], sample["case"], sample["variant"]): sample
                   for sample in document["samples"]}
        for (jobs, case, variant), candidate in indexed.items():
            if variant != "candidate":
                continue
            baseline = indexed[jobs, case, "baseline"]
            for kind in (("cold", "warm") if document["warm"] else ("cold",)):
                before, after = baseline[kind]["wall_seconds"], candidate[kind]["wall_seconds"]
                if before <= 0 or after <= 0:
                    raise ValueError("non-positive elapsed time")
                ratios.setdefault((case, jobs, kind), []).append(before / after)
    result["summary"] = benchmark.summarize(result["samples"])
    for (case, jobs, kind), values in sorted(ratios.items()):
        result["paired_speedups"].append({
            "case": case, "jobs": jobs, "cache": kind, "repetitions": len(values),
            "median_speedup": statistics.median(values), "min_speedup": min(values),
            "max_speedup": max(values), "stdev_speedup": statistics.stdev(values) if len(values) > 1 else None,
        })
    for row in result["summary"]:
        row["selected_tests"] = len(result["test_catalogs"].get(row["variant"] + "/" + row["case"], []))
        if "speedup_vs_baseline" in row:
            row["ratio_of_time_medians"] = row.pop("speedup_vs_baseline")
            row["speedup_vs_baseline"] = statistics.median(ratios[row["case"], row["jobs"], row["cache"]])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, help="Root containing each repetition's results.json")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = sorted(args.inputs.glob("**/results.json"))
    try:
        result = aggregate([json.loads(path.read_text(encoding="utf-8")) for path in files], args.repetitions)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    result["input_reports"] = [str(path) for path in files]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    markdown = benchmark.markdown_report(result)
    markdown += "\n" + result["pairing_policy"] + "\n"
    args.output.with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
