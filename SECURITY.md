# Security Policy

## Scope

This project is a disposable network lab. It is not a production network and must not be exposed to untrusted networks or used with production credentials.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use the repository’s private security-advisory mechanism or contact the maintainers privately. Include:

- Affected file or workflow.
- Reproduction steps.
- Impact and prerequisites.
- Whether a credential or private key may be exposed.
- Suggested remediation if available.

Do not include real passwords, private keys, tokens, or customer data in the report. Redact them before sharing.

## Security boundaries

The lab intentionally uses:

- Isolated Containerlab networks.
- Ephemeral FRR SSH keys.
- Cleartext HTTP for SR Linux JSON-RPC.
- Disabled SSH host-key checking.
- A root FRR SSH user.

These settings are acceptable only inside the disposable lab. They are not production defaults.

## Credential response

If a credential is exposed:

1. Revoke or rotate it immediately.
2. Remove it from the working tree and CI configuration.
3. Preserve only the minimum evidence needed for investigation.
4. Coordinate a Git history rewrite if the credential ever entered a commit.
5. Review CI logs and artifacts for secondary exposure.

A normal file edit does not remove a secret from Git history.
