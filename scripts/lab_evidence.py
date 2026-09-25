#!/usr/bin/env python3
"""Create redacted, hashed, machine-readable lab evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_ASSIGNMENT = re.compile(
    r"(?i)([A-Za-z0-9_.-]*(?:password|passwd|token|secret|private[_-]?key)[A-Za-z0-9_.-]*)"
    r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-]+ PRIVATE KEY-----.*?-----END [^-]+ PRIVATE KEY-----",
    re.DOTALL,
)
SENSITIVE_FILENAMES = {"authorized_keys", "id_ed25519", "id_rsa"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_text(text: str, secret_values: tuple[str, ...] = ()) -> str:
    """Remove common secret assignments and known secret values."""
    for value in sorted({item for item in secret_values if item}, key=len, reverse=True):
        text = text.replace(value, "<redacted>")
    text = PRIVATE_KEY_BLOCK.sub("<redacted-private-key>", text)
    return SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", text)


def redact_tree(root: Path, output: Path, secret_values: tuple[str, ...] = ()) -> None:
    """Copy a tree while redacting text and skipping private key files."""
    if output.resolve() == root.resolve():
        raise ValueError("redacted output must differ from the source artifact tree")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    for source in sorted(root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(root)
        if source.name in SENSITIVE_FILENAMES or any(
            part in SENSITIVE_FILENAMES for part in relative.parts
        ):
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"<redacted-sensitive-file>\n")
            continue
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = source.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            destination.write_bytes(source.read_bytes())
        else:
            destination.write_text(redact_text(text, secret_values), encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as stream:
        stream.write(payload)
        temporary = Path(stream.name)
    temporary.replace(path)


def record_event(path: Path, run_id: str, stage: str, status: str, **fields: Any) -> None:
    event = {"run_id": run_id, "stage": stage, "status": status, "timestamp": utc_now(), **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def build_manifest(root: Path, output: Path, run_id: str) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() == output.resolve():
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    write_json_atomic(
        output,
        {"schema": "isp-lab.manifest/v1", "run_id": run_id, "generated_at": utc_now(), "files": files},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    event = subparsers.add_parser("event")
    event.add_argument("--output", type=Path, required=True)
    event.add_argument("--run-id", required=True)
    event.add_argument("--stage", required=True)
    event.add_argument("--status", required=True, choices=("started", "passed", "failed", "skipped"))
    event.add_argument("--duration-ms", type=int)

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--run-id", required=True)

    redact = subparsers.add_parser("redact")
    redact.add_argument("--root", type=Path, required=True)
    redact.add_argument("--output", type=Path, required=True)
    redact.add_argument("--secret-env", action="append", default=[])

    args = parser.parse_args()
    if args.command == "event":
        fields = {"duration_ms": args.duration_ms} if args.duration_ms is not None else {}
        record_event(args.output, args.run_id, args.stage, args.status, **fields)
    elif args.command == "manifest":
        build_manifest(args.root, args.output, args.run_id)
    else:
        values = tuple(os.environ.get(name, "") for name in args.secret_env)
        redact_tree(args.root, args.output, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
