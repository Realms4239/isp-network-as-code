# Contributing to ISP Network as Code

Thank you for helping improve this project. Contributions are welcome, especially changes that make the lab more reproducible, observable, and safe to operate.

## Before you start

- Read `docs/ARCHITECTURE.md`, `docs/EVIDENCE.md`, and `docs/EXTENDING.md`.
- Search existing issues and pull requests before opening a duplicate.
- For a new node type or protocol, start with a short design note describing the plan, evidence, and rollback behavior.
- Never include credentials, private keys, tokens, or real customer data in an issue, pull request, log, or fixture.

## Development setup

Use Linux or a Linux VM with Docker Engine. The live lab is not supported on native Windows for the Containerlab lifecycle.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --requirement pyats/requirements.txt
python -m pip install ansible-lint==26.9.0 flake8==7.4.1
```

Copy no secrets into the repository. Export `SRL_PASSWORD` only in the shell or CI secret store when a live run is authorized.

## Required checks

Run the offline gates before opening a pull request:

```bash
python scripts/validate_contract.py
python -m pytest -q tests
yamllint data/ topology/ ansible/ observability/ pyats/ .github/workflows/pipeline.yml .github/ISSUE_TEMPLATE/ .github/dependabot.yml
flake8 pyats/test_network.py pyats/test_job.py scripts/*.py ansible/plugins/callback/*.py tests/*.py --max-line-length=120
python -m py_compile pyats/test_network.py pyats/test_job.py scripts/*.py ansible/plugins/callback/*.py tests/*.py
```

Run the live lifecycle only when the images, credentials, and Docker host are available:

```bash
bash scripts/run_local.sh
```

Do not run a live lifecycle merely to validate a documentation or unit-test change.

## Change guidelines

- Keep `data/lab.yml` as the source of truth for the lab plan.
- Add a negative test for every new contract rule.
- Keep changes idempotent and deterministic.
- Prefer explicit failure messages and machine-readable evidence.
- Do not weaken a security check merely to make a local environment pass.
- Keep node-specific behavior in roles or a node-type definition, not scattered through validators.
- Keep generated collections, logs, artifacts, and lab keys out of Git.
- Update documentation and the changelog for behavior changes.

## Pull request expectations

A pull request should include:

1. A concise problem and solution statement.
2. The files or contracts changed.
3. Offline test results.
4. Live-run results, if the change affects runtime behavior.
5. Security and rollback notes.
6. Evidence or screenshots only after redaction.

Use the pull request template. Maintainers may request changes when a contract, dependency pin, image tag, or security boundary changes without corresponding tests and documentation.

## Commits and reviews

Use small, focused commits with imperative subjects. One logical change should be easy to review and revert. Do not mix formatting-only churn with functional changes.

All changes require review by a maintainer. Changes to credentials, CI permissions, pinned images, Ansible callbacks, or evidence handling require explicit security-focused review.
