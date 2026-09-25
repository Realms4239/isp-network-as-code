# Evidence and security contract

The lab produces evidence for offline review and CI diagnostics. Evidence must be machine-readable, deterministic where possible, and safe to publish.

## Artifacts

- `artifacts/events.jsonl` — append-only stage lifecycle events.
- `artifacts/ansible-check-2.json` — summarized Ansible host counters and result hash.
- `artifacts-redacted/` — redacted copy of collected artifacts.
- `artifacts-redacted/manifest.json` — file size and SHA-256 for every redacted artifact.

Raw artifacts remain local. Only `artifacts-redacted/` is uploaded by CI.

## Redaction rules

`scripts/lab_evidence.py` removes:

- known secret environment values passed with `--secret-env`;
- assignments containing `password`, `passwd`, `secret`, or `token`;
- PEM private-key blocks;
- files named `authorized_keys`, `id_ed25519`, or `id_rsa`.

Redaction is not a substitute for least privilege. Credentials must not be placed in command arguments, repository files, topology files, or CI logs.

## Exit codes

- `0` — stage passed.
- `1` — contract or verification failure.
- `2` — input/read failure, such as a missing or malformed evidence file.

## Security boundary

This repository is a disposable, isolated lab. The plan explicitly records that it uses cleartext SR Linux management HTTP, disabled SSH host-key checking, and a root FRR SSH account. These settings are not production recommendations. Rotate any credential that has ever been committed to Git history; history removal requires a separately approved Git rewrite.
