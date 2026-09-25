#!/usr/bin/env python3
"""Validate machine-readable Ansible callback output."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def iter_host_stats(value: Any, host_name: str | None = None):
    if isinstance(value, dict):
        if "changed" in value and ("failed" in value or "unreachable" in value):
            yield host_name, value
        for key, child in value.items():
            child_host = key if key == "hosts" and isinstance(child, dict) else host_name
            if key == "hosts" and isinstance(child, dict):
                for name, stats in child.items():
                    if isinstance(stats, dict):
                        yield from iter_host_stats(stats, name)
            else:
                yield from iter_host_stats(child, child_host)
    elif isinstance(value, list):
        for child in value:
            yield from iter_host_stats(child, host_name)


def expected_hosts_from_plan(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as stream:
        plan = yaml.safe_load(stream) or {}
    nodes = plan.get("nodes", {}) if isinstance(plan, dict) else {}
    if not isinstance(nodes, dict) or not nodes:
        raise ValueError("data/lab.yml must define a non-empty nodes mapping")
    return set(nodes)


def write_report(path: Path | None, run_id: str, result: Path, stats: dict[str, dict[str, int]], status: str) -> None:
    if path is None:
        return
    payload = {
        "schema": "isp-lab.ansible-result/v1",
        "run_id": run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "result_file": result.name,
        "result_sha256": hashlib.sha256(result.read_bytes()).hexdigest(),
        "status": status,
        "hosts": {host: dict(values) for host, values in sorted(stats.items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--require-idempotent", action="store_true")
    parser.add_argument("--expected-hosts", default=None)
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "lab.yml",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    try:
        result = json.loads(args.result.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read Ansible JSON result: {exc}")
        return 2

    stats = list(iter_host_stats(result))
    if not stats:
        print("ERROR: Ansible JSON result contains no host statistics")
        write_report(args.report, args.run_id, args.result, {}, "failed")
        return 1
    stats_by_host: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"ok": 0, "changed": 0, "failed": 0, "unreachable": 0}
    )
    for host, item in stats:
        if not host:
            continue
        for field in stats_by_host[host]:
            try:
                stats_by_host[host][field] += int(item.get(field, 0))
            except (TypeError, ValueError):
                print(f"ERROR: Ansible JSON contains a non-integer {field!r} value for {host}")
                write_report(args.report, args.run_id, args.result, stats_by_host, "failed")
                return 1
    try:
        if args.expected_hosts:
            expected_hosts = {item.strip() for item in args.expected_hosts.split(",") if item.strip()}
        else:
            expected_hosts = expected_hosts_from_plan(args.plan)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot determine expected hosts: {exc}")
        write_report(args.report, args.run_id, args.result, stats_by_host, "failed")
        return 2
    if set(stats_by_host) != expected_hosts:
        print(
            f"ERROR: Ansible JSON host set mismatch: expected={sorted(expected_hosts)} "
            f"actual={sorted(stats_by_host)}"
        )
        write_report(args.report, args.run_id, args.result, stats_by_host, "failed")
        return 1
    legacy = any("ok" not in item for _, item in stats)
    processed = sum(int(item.get("ok", 0)) for item in stats_by_host.values())
    processed += sum(int(item.get("failed", 0)) for item in stats_by_host.values())
    processed += sum(int(item.get("unreachable", 0)) for item in stats_by_host.values())
    if legacy:
        processed += len(stats_by_host)
    if processed == 0:
        print("ERROR: Ansible JSON result contains no processed host tasks")
        write_report(args.report, args.run_id, args.result, stats_by_host, "failed")
        return 1
    changed = sum(int(item.get("changed", 0)) for item in stats_by_host.values())
    failed = sum(int(item.get("failed", 0)) for item in stats_by_host.values())
    unreachable = sum(int(item.get("unreachable", 0)) for item in stats_by_host.values())
    print(f"Ansible host statistics: changed={changed} failed={failed} unreachable={unreachable}")
    if failed or unreachable:
        write_report(args.report, args.run_id, args.result, stats_by_host, "failed")
        return 1
    if args.require_idempotent and changed:
        print("ERROR: second Ansible run changed configuration")
        write_report(args.report, args.run_id, args.result, stats_by_host, "not-idempotent")
        return 1
    write_report(args.report, args.run_id, args.result, stats_by_host, "passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
