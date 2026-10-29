#!/usr/bin/env python3
"""Deterministic differential and paired benchmarks for idna #279 and #287.

All versions are imported from actual Git worktrees at the same historical base.
No package from site-packages is benchmarked. Comparisons are within one runner,
never between runner types.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import statistics
import sys
import time


VARIANTS = ("base", "pr279", "pr287", "combined")
RANDOM_SEED = 20261029


def load_variant(root: Path, name: str):
    pkg_path = root / name / "idna"
    assert (pkg_path / "__init__.py").is_file(), pkg_path
    package = "_research_idna_" + name
    spec = importlib.util.spec_from_file_location(
        package, pkg_path / "__init__.py",
        submodule_search_locations=[str(pkg_path)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


def signature(fn, value):
    try:
        result = fn(value)
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc), getattr(exc, "code", None),
                getattr(exc, "text", None), getattr(exc, "codepoint", None),
                getattr(exc, "position", None))
    return ("ok", result)


def correctness(pkgs):
    rng = random.Random(RANDOM_SEED)
    labels = ["", "a", "example", "EXAMPLE", "api-v2", "A-B", "xn--",
              "xn--zckzah", "xn---bbk", "ab--cd", "-bad", "bad-", "bad_label",
              "a" * 63, "a" * 64, "-" + "a" * 254,
              "münchen", "日本語", "שלום", "مثال", "faß",
              "e\u0301", "\u200c", "\u200d", "\x00", "\ud800",
              "a" * 1024, "a" * 1025]
    letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_!"
    labels.extend(a+b for a in letters for b in letters)
    for n in range(0, 1026):
        labels.extend(("a" * n, "a" + "-" * max(0, n - 2) + ("b" if n > 1 else ""),
                       ("xn--" + "a" * max(0, n - 4))[:n]))
    symbols = letters + "éöß日本字אבسم\u200c\u200d\u0301\u202e."
    for _ in range(3500):
        labels.append("".join(rng.choices(symbols, k=rng.randrange(0, 80))))
    operations = ("alabel", "ulabel", "check_label")
    checks = 0
    for op in operations:
        base = getattr(pkgs["base"], op)
        for label in labels:
            expected = signature(base, label)
            for name in VARIANTS[1:]:
                actual = signature(getattr(pkgs[name], op), label)
                if expected != actual:
                    raise AssertionError(f"{op} {name} {label!r}\nbase={expected!r}\nactual={actual!r}")
            checks += 1

    domains = ["example.com", "EXAMPLE.COM", "api-v2.example-service.com",
               "münchen.de", "日本語.jp", "faß.de", "xn--zckzah.jp",
               "a..com", "bad_label.com", "-bad.com", "a" * 64 + ".com"]
    domains.extend(
        ".".join(rng.choice(labels) for _ in range(rng.randrange(1, 4)))
        for _ in range(2500)
    )
    for op in ("encode", "decode"):
        for val in domains:
            expected = signature(getattr(pkgs["base"], op), val)
            for name in VARIANTS[1:]:
                actual = signature(getattr(pkgs[name], op), val)
                if expected != actual:
                    raise AssertionError(f"{op} {name} {val!r}\nbase={expected!r}\nactual={actual!r}")
            checks += 1

    for value in (b"example", b"EXAMPLE", b"xn--zckzah", b"\xff", bytearray(b"example")):
        for op in ("ulabel", "check_label", "decode"):
            expected = signature(getattr(pkgs["base"], op), value)
            for name in VARIANTS[1:]:
                actual = signature(getattr(pkgs[name], op), value)
                if expected != actual:
                    raise AssertionError(f"{op} {name} {value!r}: {expected!r} != {actual!r}")
            checks += 1
    return {"cases": checks, "candidate_comparisons": checks * 3, "mismatches": 0}


ASCII = [f"mail{i}.example{i % 13}.com" for i in range(32)]
ASCII += ["example.com", "api-v2.example-service.com", "EXAMPLE.COM", "Mail.EXAMPLE.net"]
UNICODE = ["münchen.de", "日本語.jp", "faß.de", "Königsgäßchen.example",
           "пример.рф", "שלום.co.il", "مثال.إختبار", "école.fr"]
INVALID = ["bad_label.com", "bad..com", "-bad.com", "ab--cd.com",
           "a" * 64 + ".com", "xn---bbk.com"]
MIXED = ASCII[:28] + UNICODE + INVALID[:4]


def workload(pkg, name):
    if name == "encode_ascii":
        return pkg.encode, ASCII
    if name == "encode_uts46":
        return lambda s: pkg.encode(s, uts46=True), ASCII
    if name == "encode_mixed":
        return pkg.encode, MIXED
    if name == "encode_unicode":
        return lambda s: pkg.encode(s, uts46=True), UNICODE
    if name == "encode_invalid":
        return pkg.encode, INVALID
    if name == "decode_ascii":
        return pkg.decode, ASCII
    if name == "encode_decode_ascii":
        return lambda s: pkg.decode(pkg.encode(s)), ASCII
    if name == "alabel_ascii":
        return pkg.alabel, [x.split(".")[0] for x in ASCII]
    if name == "check_label_ascii":
        return pkg.check_label, [x.split(".")[0].lower() for x in ASCII]
    if name == "check_label_unicode":
        return pkg.check_label, [x.split(".")[0] for x in UNICODE]
    raise ValueError(name)


WORKLOADS = (
    "encode_ascii", "encode_uts46", "encode_mixed", "encode_unicode",
    "encode_invalid", "decode_ascii", "encode_decode_ascii",
    "alabel_ascii", "check_label_ascii", "check_label_unicode",
)


def run_batch(fn, values, repetitions):
    tally = 0
    start = time.perf_counter_ns()
    for _ in range(repetitions):
        for value in values:
            try:
                r = fn(value)
                tally += len(r) if r is not None else 1
            except Exception:
                tally += 1
    elapsed = time.perf_counter_ns() - start
    assert tally >= 0
    return elapsed / (repetitions * len(values))


def benchmark(pkgs):
    rng = random.Random(RANDOM_SEED + 1)
    results = {}
    for case in WORKLOADS:
        arms = {name: workload(pkgs[name], case) for name in VARIANTS}
        # Warm every code path to avoid cold import/regular-expression effects.
        for _ in range(3):
            for fn, vals in arms.values():
                run_batch(fn, vals, 30)
        fn, vals = arms["base"]
        calibration = run_batch(fn, vals, 80) * len(vals)
        target_repetitions = min(50000, max(40, int(125_000_000 / max(1, calibration))))
        samples = {name: [] for name in VARIANTS}
        for _ in range(7):
            order = list(VARIANTS)
            rng.shuffle(order)
            for name in order:
                fn, vals = arms[name]
                samples[name].append(run_batch(fn, vals, target_repetitions))
        medians = {name: statistics.median(samples[name]) for name in VARIANTS}
        results[case] = {
            "median_ns_per_input": {name: round(medians[name], 2) for name in VARIANTS},
            "speedup_vs_base": {name: round(medians["base"] / medians[name], 3) for name in VARIANTS},
            "pr279_speedup_over_pr287": round(medians["pr287"] / medians["pr279"], 3),
            "combined_speedup_over_pr287": round(medians["pr287"] / medians["combined"], 3),
            "samples_ns_per_input": {name: [round(v, 2) for v in values]
                                     for name, values in samples.items()},
            "repetitions": target_repetitions,
            "items_per_repetition": len(vals),
        }
    return results


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python compare_idna.py /path/to/worktrees")
    root = Path(sys.argv[1])
    pkgs = {name: load_variant(root, name) for name in VARIANTS}
    outcome = correctness(pkgs)
    results = benchmark(pkgs)
    report = {
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "machine": platform.machine(), "runner": os.environ.get("RUNNER_NAME", "")},
        "commits": {"base": "7c55529db07b94781037703199f57fc9b7c0dc40",
                    "pr279": "ebaaa7175134bb9247e19ebf177e51356e897a17",
                    "pr287": "4367172084872ef951a2485af332ac55ec7b65e4"},
        "correctness": outcome, "benchmarks": results,
    }
    output = Path(os.environ.get("IDNA_REPORT_PATH", "idna-report.json"))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ("base", "pr279", "pr287", "combined")
    table = ["| Workload | Base ns | #279 ns | #287 ns | Both ns | #279 / #287 |",
             "|---|---:|---:|---:|---:|---:|"]
    for key, record in results.items():
        v = record["median_ns_per_input"]
        table.append("| " + key + " | " +
                     " | ".join(f"{v[name]:,.1f}" for name in columns) + " | " +
                     f"{record['pr279_speedup_over_pr287']:.3f}x |")
    body = ("\n".join(["## IDNA actual-commit comparison",
             f"Runner: {platform.platform()} / Python {sys.version.split()[0]}",
             f"Differential checks: {outcome['candidate_comparisons']:,}; mismatches: 0",
             "Within-runner paired medians of 7 shuffled rounds; lower ns is better.",
             "#279/#287 > 1 means #279 faster.", "", *table, ""]))
    print(body)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(body + "\n")


if __name__ == "__main__":
    main()
