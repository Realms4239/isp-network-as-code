# ISP Network as Code (Flagship)

> **Autonomous Backbone as Code**: Declare backbone topology, configure OSPF & BGP via Ansible with strict idempotency, assert operational health with Cisco pyATS / Genie in CI/CD, and provide optional Prometheus/Grafana observability configuration.

[![NetDevOps CI/CD Pipeline](https://github.com/Realms4239/isp-network-as-code/actions/workflows/pipeline.yml/badge.svg)](https://github.com/Realms4239/isp-network-as-code/actions/workflows/pipeline.yml)
[![Containerlab](https://img.shields.io/badge/Containerlab-0.71.0-blue.svg)](https://containerlab.dev)
[![Nokia SR Linux](https://img.shields.io/badge/Nokia-SR%20Linux-24.10.1-183660.svg)](https://learn.srlinux.dev)
[![FRRouting](https://img.shields.io/badge/FRR-10.7.1-orange.svg)](https://frrouting.org)
[![Ansible](https://img.shields.io/badge/Ansible-2.21.4-EE0000.svg)](https://docs.ansible.com)
[![Cisco pyATS](https://img.shields.io/badge/pyATS-Genie-26.8-049fd9.svg)](https://developer.cisco.com/pyats/)
[![Prometheus](https://img.shields.io/badge/Prometheus-config-available-e6522c.svg)](https://prometheus.io)

---

## ðŸŽ¯ Architecture & Overview

Network engineers at ISPs traditionally configure routers by hand over SSH. Human mistakes surface during customer outages, not before deployment. 

**ISP Network as Code** solves this by treating the ISP backbone like software:
1. **Topology as Code**: Declared in declarative YAML via [Containerlab](https://containerlab.dev).
2. **Infrastructure as Code**: Multi-vendor automation (Nokia SR Linux + FRRouting) via [Ansible](https://ansible.com) with guaranteed **0 changed** idempotency.
3. **Automated Pre/Post Flight Verification**: Rigorous state testing with [Cisco pyATS / Genie](https://developer.cisco.com/pyats/) asserting:
   - Line protocol up/up across all backbone interfaces.
   - OSPF adjacencies reaching `FULL` state.
   - BGP peering reaching `ESTABLISHED` state.
   - Expected route tables: SRL nodes must have the remote loopback via BGP/OSPF, and FRR must have both SRL loopbacks.
   - Bidirectional ICMP: `srl01 <-> srl02`, `srl01 <-> frr01`, and `srl02 <-> frr01`.
4. **Deterministic Evidence**: `scripts/lab_evidence.py` emits stage events, redacts secret material, and produces a SHA-256 artifact manifest.
5. **CI/CD**: Cloud runners lint, spin up the virtual lab, deploy configurations, run pyATS test suites, verify telemetry, and teardown cleanly in under 5 minutes.
6. **Optional Observability**: Prometheus and Grafana provisioning examples are provided under `observability/`; exporters are not part of the Phase 0 container topology.

---
## Two jobs, and what each one proves

| Job | Runs when | Proves |
|---|---|---|
| `Code Quality & Contract Validation` | every push and PR | cross-file contract holds, negative tests fail correctly, YAML/Ansible/Python lint clean, Ansible can resolve the pinned collections |
| `Containerlab, Ansible, and pyATS Verification` | push, same-repo PR, **and only when `SRL_PASSWORD` exists** | the lab actually deploys, converges, and passes protocol assertions |

The first job needs no secrets and no Docker, so it is the authoritative gate and
it must stay green. The second is optional live proof: it is **skipped, not
failed**, when the lab credential is absent, because reporting a missing secret
as a broken lab is a misleading signal. To enable it:

```sh
gh secret set SRL_PASSWORD --repo Realms4239/isp-network-as-code
```

The lab password is never committed; see [docs/EVIDENCE.md](docs/EVIDENCE.md).

## Project governance


## Project governance

- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Changelog](CHANGELOG.md)
- [Evidence contract](docs/EVIDENCE.md)
- [Extension guide](docs/EXTENDING.md)

## ðŸ—‚ï¸ Repository Map

- **Data and contract**: `data/lab.yml` is the declarative plan; `scripts/validate_contract.py` checks every projection against it.
- **Topology**: `topology/topology.clab.yml` is the Containerlab projection.
- **Configuration**: `ansible/` contains inventory, group variables, host variables, and role-specific protocol configuration.
- **Verification**: `pyats/parsers.py` holds pure output parsers, `pyats/test_job.py` the job entry point, `pyats/testbed.yml` the device map, and `pyats/test_network.py` the assertions. Parsing is deliberately separated from device I/O so that all of it is covered by offline tests — see [docs/EXTENDING.md](docs/EXTENDING.md).
- **Operations**: `scripts/` contains preparation, local lifecycle, contract validation, and result validation.
- **CI**: `.github/workflows/pipeline.yml` runs offline quality gates before the live lab stage.

## ðŸ“ Topology Diagram

```
                 +---------------------------------+
                 |          frr01 (FRR)            |
                 |      AS 65002 (Transit Core)    |
                 |        Loopback: 10.0.0.3       |
                 +----------------+----------------+
                                 / \
         eth1: 10.1.23.2/24     /   \   eth2: 10.1.13.2/24
                               /     \
                              /       \
      eth2: 10.1.23.1/24     /         \     eth2: 10.1.13.1/24
    +-----------------------+           +-----------------------+
    |      srl02 (Nokia)    |           |      srl01 (Nokia)    |
    |  AS 65001 / OSPF A0   |           |  AS 65001 / OSPF A0   |
    |  Loopback: 10.0.0.2   |           |  Loopback: 10.0.0.1   |
    +-----------+-----------+           +-----------+-----------+
                 \                                 /
   e1-1: 10.1.12.2\                               /e1-1: 10.1.12.1
                   \============================= /
                     OSPF Area 0 (Backbone Link)
```

- **srl01 & srl02**: Nokia SR Linux core routers running OSPF Area 0 and iBGP (AS 65001).
- **frr01**: FRRouting upstream transit router running eBGP peering to srl01 and srl02.

---

## âš¡ Quick Start (Local Run)

### Requirements
- Linux (Ubuntu 22.04 LTS or Debian 12 recommended) or Linux VM.
- Docker Engine 24+
- Python 3.12+ with `venv` (pinned by `ansible-core` 2.21)
- Containerlab 0.71.0 with the `linux` kind for FRR
- Ansible Core 2.21.4
- pyATS/Genie 26.8

> **Why Linux, concretely:** pyATS 26.8 and Genie 26.8 publish wheels for
> Linux and macOS only. There is no Windows wheel, so on a native Windows
> host `pip install -r pyats/requirements.txt` fails with
> `Could not find a version that satisfies the requirement pyats==26.8
> (from versions: none)` even when the network is fine and the version
> definitely exists. That message reads like an outage or a typo, and it is
> neither. The offline test suite does not need pyATS, so it still runs on
> Windows; only the live lab and `pyats/` do not. Use WSL2, a Linux VM, or
> Linux CI.

```bash
# 1. Clone repository
git clone https://github.com/Realms4239/isp-network-as-code.git
cd isp-network-as-code

# 2. Install dependencies and run the guarded lifecycle
python -m venv .venv
source .venv/bin/activate
python -m pip install --requirement pyats/requirements.txt
export SRL_PASSWORD='<set-in-your-environment>'
bash ./scripts/run_local.sh
```

---

## ðŸ”¬ CI/CD Pipeline Stages

Every push triggers GitHub Actions (`.github/workflows/pipeline.yml`):
1. **Static gates**: cross-file contract validation, negative contract tests, YAML lint, Ansible lint, Python lint, and unit tests.
2. **Deploy**: Containerlab 0.71.0 starts the pinned SR Linux 24.10.1 and FRR 10.7.1 topology.
3. **Configure**: Ansible applies a validated candidate configuration and persists it.
4. **Idempotency Gate**: the JSON callback result requires zero failed/unreachable hosts and exactly zero changes on the second run.
5. **pyATS Validation**: exact interface, OSPF, BGP, route, and bidirectional reachability assertions run against the live lab.
6. **Diagnostics & Teardown**: inspect state, logs, Ansible output, and Docker state are uploaded; topology teardown runs with `if: always()`.

The local runner uses the same lifecycle and emits artifacts under `artifacts/` in the repository checkout. Only redacted evidence is suitable for sharing.

## Contract and runtime gates

`data/lab.yml` is the declarative source of truth for node types, management addresses, links, host variables, and pyATS expectations. `scripts/validate_contract.py` verifies every projection against that plan; see `docs/EXTENDING.md` before adding a node or node type.

`scripts/check_ansible_result.py` consumes the Ansible JSON callback rather than parsing recap text. The second run must report `changed=0`, `failed=0`, and `unreachable=0` for every expected host summary, aggregating all plays for each host.

The pinned FRR image is a Containerlab SSH-capable image running through the `linux` kind, with `/etc/frr/daemons` and `/etc/frr/vtysh.conf` supplied by the topology. The runner creates a short-lived host key and writes only the public key into the lab bind directory; Ansible/pyATS use the private key directly.

## Credentials

Do not use the historical default SR Linux password in an untrusted environment. Export `SRL_PASSWORD` and, optionally, `FRR_SSH_KEY` before running locally. GitHub Actions reads `SRL_PASSWORD` from repository secrets. The FRR private key is ephemeral and is never committed.
