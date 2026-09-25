#!/usr/bin/env python3
"""Wait for planned SR Linux management endpoints without exposing credentials."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

JSONRPC_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "get",
    "params": {
        "commands": [
            {
                "path": "/system/information/version",
                "datastore": "state",
            }
        ]
    },
}


def planned_srlinux_addresses(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as stream:
        plan: Any = yaml.safe_load(stream) or {}
    node_types = plan.get("node_types", {}) if isinstance(plan, dict) else {}
    nodes = plan.get("nodes", {}) if isinstance(plan, dict) else {}
    addresses = []
    for name, node in nodes.items():
        if not isinstance(node, dict):
            continue
        node_type = node_types.get(node.get("type"), {})
        if not isinstance(node_type, dict) or node_type.get("kind") != "nokia_srlinux":
            continue
        address = node.get("mgmt_ipv4")
        if isinstance(address, str):
            addresses.append(address)
    if not addresses:
        raise ValueError("data/lab.yml contains no SR Linux management addresses")
    return sorted(set(addresses))


def auth_header(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {encoded}"


def probe(address: str, username: str, password: str, timeout: float) -> bool:
    request = urllib.request.Request(
        f"http://{address}/jsonrpc",
        data=json.dumps(JSONRPC_REQUEST).encode("utf-8"),
        headers={
            "Authorization": auth_header(username, password),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("data/lab.yml"))
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--delay", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    if args.attempts < 1 or args.delay < 0 or args.timeout <= 0:
        parser.error("attempts must be >= 1 and delay/timeout must be non-negative")
    username = os.environ.get("SRL_USER", "admin")
    password = os.environ.get("SRL_PASSWORD", "")
    if not password:
        print("ERROR: SRL_PASSWORD is required", flush=True)
        return 2
    try:
        addresses = planned_srlinux_addresses(args.plan)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot read SR Linux addresses: {exc}", flush=True)
        return 2

    for attempt in range(1, args.attempts + 1):
        pending = [address for address in addresses if not probe(address, username, password, args.timeout)]
        if not pending:
            print(f"SR Linux readiness passed on attempt {attempt}: {', '.join(addresses)}")
            return 0
        if attempt < args.attempts:
            time.sleep(args.delay)
    print(f"ERROR: SR Linux endpoints not ready after {args.attempts} attempts: {', '.join(addresses)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
