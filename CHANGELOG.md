# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the project uses semantic versioning for future releases.

## [Unreleased]

### Added

- Declarative `data/lab.yml` contract with plan-driven node types, links, host variables, and pyATS expectations.
- Repository-owned Ansible `lab_json` callback with machine-readable host counters.
- Redacted evidence collection, stage events, and SHA-256 artifact manifests.
- Plan-driven SR Linux readiness probing.
- Offline negative-contract tests for drift, malformed inputs, security boundaries, and result-gate failures.
- Contributor, security, code-of-conduct, issue, and pull-request governance files.

### Changed

- Ansible collection and callback paths are explicitly configured.
- FRR configuration is validated before transfer and uses safe bind-mount permissions.
- CI scopes secrets to the trusted deployment job and uploads only redacted artifacts.
- Local lifecycle validates contracts before deploying and emits stage evidence.

### Security

- Literal credential assignments and out-of-tree bind mounts are rejected by the contract validator.
- Generated collections, logs, artifacts, and lab keys are excluded from Git.
- Lab-only insecure transport and host-key settings are explicitly declared in the plan.

### Known limitations

- Live Containerlab, Ansible, and pyATS verification requires a Linux/Docker host, cached images, and `SRL_PASSWORD`.
- The project does not rewrite Git history automatically when a credential has previously been committed.
