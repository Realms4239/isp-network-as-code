# Extending the Phase 0 lab

`data/lab.yml` is the declarative contract for the lab. It is the first file to change when adding a node type or node. The validator, Ansible host gate, and documentation should be extended together rather than adding new hardcoded branches to Python.

## Add a node type

1. Add an entry under `node_types` with:
   - `topology_group`
   - `ansible_group`
   - `role`
   - `kind`, pinned `image`, and optional `type`
   - `allowed_interfaces`
   - `interface_map`
   - `required_host_vars`
   - `as_number` when the node participates in BGP
2. Add a node under `nodes` with `type`, `group`, `mgmt_ipv4`, and `host_vars`.
3. Add the node to the matching topology group and node list.
4. Add the node to the matching Ansible inventory group and create `ansible/host_vars/<node>.yml`.
5. Add the node to the pyATS testbed with the same management address.
6. Add interface, route, and reachability expectations under `data/lab.yml.pyats`.
7. Add the node to the relevant role or create a new role. Keep node-type-specific behavior in the role, not in `validate_contract.py`.
8. Add a negative contract test for every new cross-file dependency.

Offline gates must always pass before a live run:

```bash
python scripts/validate_contract.py
python -m pytest -q tests
yamllint data/ topology/ ansible/ observability/ pyats/ .github/workflows/pipeline.yml .github/ISSUE_TEMPLATE/ .github/dependabot.yml
flake8 pyats/*.py scripts/*.py ansible/plugins/callback/*.py tests/*.py --max-line-length=120
```

## Evidence and security

Each lifecycle run emits `artifacts/events.jsonl` and a SHA-256 manifest. Raw artifacts are never uploaded directly: `scripts/lab_evidence.py` redacts secret assignments, secret environment values, and private-key material into `artifacts-redacted/`.

The lab deliberately uses isolated Containerlab networks, ephemeral keys, cleartext HTTP for SR Linux JSON-RPC, disabled SSH host-key checking, and a root FRR SSH user. These are acceptable only for this disposable, isolated lab and must not be copied into production.

If a credential has ever been committed to Git history, rotate it immediately. Removing historical content requires an explicit repository-history rewrite and coordinated force-push decision; ordinary file edits do not remove the secret from prior commits.

## Release checklist

Before tagging a release:

- [ ] `CHANGELOG.md` has a dated release section.
- [ ] `data/lab.yml` topology and image versions are intentional.
- [ ] Offline contract, unit, YAML, Python, and shell gates pass.
- [ ] The live lifecycle passes on a supported Linux/Docker host.
- [ ] Redacted evidence and manifest are archived privately or attached to the release record.
- [ ] CI has no unreviewed security, permission, or dependency changes.
- [ ] Release notes call out lab-only security boundaries.
- [ ] The release is reproducible from a clean checkout.

## Versioning policy

- `PATCH`: bug fixes that do not change the lab contract or evidence schema.
- `MINOR`: new node types, protocols, evidence fields, or supported platform versions.
- `MAJOR`: incompatible contract, topology, callback, or evidence schema changes.

Do not publish a release with an unredacted credential, private key, or customer data.

- Keep images pinned to an immutable tag or digest.
- Keep management addresses inside the declared management network.
- Keep topology endpoint interfaces inside the node type's `allowed_interfaces`.
- Keep the plan, topology, inventory, host variables, testbed, and pyATS expectations synchronized.
- Use explicit failure messages; do not rely on human interpretation of CI output.
- Do not make idempotency depend on a recap line or on the last play for a host. `scripts/check_ansible_result.py` aggregates all host statistics.
- Do not embed credentials in the plan, topology, inventory, or documentation.

## 6. Add or change a pyATS assertion

Never write an inline `re.search` against device output in
`pyats/test_network.py`. Assertions there are unreachable without a live lab,
which is how three real defects survived: the FRR peer map was read from the
wrong JSON level, one peer's output was asserted against every peer, and the
route check passed whenever vtysh echoed the queried prefix back.

Instead:

1. Add a pure function to `pyats/parsers.py` that takes output text and returns
   a verdict.
2. Cover it in `tests/test_pyats_parsers.py` with a fixture modelled on real
   vendor output, including at least one negative case.
3. Call it from `test_network.py` and turn the verdict into an assertion whose
   message names the device and the value.

`tests/test_contract.py::test_pyats_suite_has_no_bare_regex_assertions` enforces
this mechanically, so an inline regex fails the build.

`test_guard_teeth.py` exists for the same reason in the other direction: it
reintroduces each past defect and asserts the guard still fires, because a guard
that cannot fail is worse than no guard.

## Offline versus live verification

The contract, unit, YAML, Python, and shell checks are offline and require no container images. Live Containerlab, Ansible, and pyATS verification is a separate stage because it requires Docker, the pinned images, and the `SRL_PASSWORD` secret.
