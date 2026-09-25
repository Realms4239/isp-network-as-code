## Summary

<!-- What changed and why? -->

## Contract and scope

- [ ] `data/lab.yml` is updated, or the change does not affect the lab plan.
- [ ] Topology, inventory, host variables, roles, and pyATS expectations remain synchronized.
- [ ] No hardcoded node names or addresses were added where plan-driven behavior is appropriate.

## Verification

- [ ] `python scripts/validate_contract.py`
- [ ] `python -m pytest -q tests`
- [ ] YAML, flake8, and `py_compile` gates pass.
- [ ] Live lifecycle was run, or the change is documented as offline-only.

## Evidence and security

- [ ] No credentials, private keys, tokens, or customer data are included.
- [ ] Any new evidence output is redacted and documented.
- [ ] Security, CI, image, or dependency changes are called out explicitly.

## Review notes

<!-- Compatibility, rollback, and reviewer focus -->
