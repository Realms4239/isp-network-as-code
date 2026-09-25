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

### Fixed
- Python 3.11 → 3.12 in CI: `ansible-core` 2.21 declares `requires_python >=3.12`, so the previous pin failed the first install step and skipped every later one.
- `srlinux_ospf/vars/main.yml` was a top-level list; Ansible requires role vars to be a mapping, so the role had never been valid. The candidate list is now nested under `srlinux_ospf_candidate`, the name `tasks/main.yml` already consumed.
- `ansible.cfg` no longer pins `collections_path`, which silently overrode `ANSIBLE_COLLECTIONS_PATH` and made `nokia.srlinux` unresolvable.
- Lint no longer walks `ansible/collections/` (third-party Galaxy code we cannot restyle); Ansible YAML is linted by explicit source path.
- Role and registered variables are prefixed (`srlinux_ospf_candidate`, `frr_bgp_reload`) per `var-naming[no-role-prefix]`.

### Changed
- The live lab job is gated on `secrets.SRL_PASSWORD` existing. Without it the job is skipped, not failed — a missing secret must not read as a broken lab. The offline `lint` job remains the authoritative gate.
- The single opaque lint step is split into named YAML / Ansible / Python steps, and each reports its effective config or limit on failure, so a red step names its own cause.
- Added `.ansible-lint` (production profile, `offline: true`, documented `skip_list`).
- Added an offline "Verify Ansible can resolve the installed collections" step (`ansible-config dump`, collection list, `--syntax-check`) ahead of linting.
- Added five offline regression tests covering role-vars shape, the candidate contract, role variable prefixes, and the `collections_path` rule.
- README states the real Python floor (3.12+) and explains the two-job split.

### Known limitations

- Live Containerlab, Ansible, and pyATS verification requires a Linux/Docker host, cached images, and `SRL_PASSWORD`. It has never completed a passing run; the offline gates are the only green evidence so far.
- The project does not rewrite Git history automatically when a credential has previously been committed.
