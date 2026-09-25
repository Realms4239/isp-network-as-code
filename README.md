# ISP Network as Code (Flagship)

> **Autonomous Backbone as Code**: Declare backbone topology, configure OSPF & BGP via Ansible with strict idempotency, assert operational health with Cisco pyATS / Genie in CI/CD, and stream real-time telemetry to Prometheus & Grafana.

[![NetDevOps CI/CD Pipeline](https://github.com/Realms4239/isp-network-as-code/actions/workflows/pipeline.yml/badge.svg)](https://github.com/Realms4239/isp-network-as-code/actions/workflows/pipeline.yml)
[![Containerlab](https://img.shields.io/badge/Containerlab-0.50%2B-blue.svg)](https://containerlab.dev)
[![Nokia SR Linux](https://img.shields.io/badge/Nokia-SR%20Linux-183660.svg)](https://learn.srlinux.dev)
[![FRRouting](https://img.shields.io/badge/FRR-9.x-orange.svg)](https://frrouting.org)
[![Ansible](https://img.shields.io/badge/Ansible-2.15%2B-EE0000.svg)](https://docs.ansible.com)
[![Cisco pyATS](https://img.shields.io/badge/pyATS-Genie-049fd9.svg)](https://developer.cisco.com/pyats/)
[![Prometheus](https://img.shields.io/badge/Prometheus-Monitoring-e6522c.svg)](https://prometheus.io)

---

## 🎯 Architecture & Overview

Network engineers at ISPs traditionally configure routers by hand over SSH. Human mistakes surface during customer outages, not before deployment. 

**ISP Network as Code** solves this by treating the ISP backbone like software:
1. **Topology as Code**: Declared in declarative YAML via [Containerlab](https://containerlab.dev).
2. **Infrastructure as Code**: Multi-vendor automation (Nokia SR Linux + FRRouting) via [Ansible](https://ansible.com) with guaranteed **0 changed** idempotency.
3. **Automated Pre/Post Flight Verification**: Rigorous state testing with [Cisco pyATS / Genie](https://developer.cisco.com/pyats/) asserting:
   - Line protocol up/up across all backbone interfaces.
   - OSPF adjacencies reaching `FULL` state.
   - BGP peering reaching `ESTABLISHED` state.
   - End-to-end packet reachability across the transit fabric.
4. **End-to-End CI/CD**: Cloud runners lint, spin up the virtual lab, deploy configurations, run pyATS test suites, verify telemetry, and teardown cleanly in under 5 minutes.
5. **Real-time Observability**: Prometheus scraping exporter metrics + Grafana operational dashboards for router CPU, interface traffic, and routing protocol health.

---

## 📐 Topology Diagram

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

## ⚡ Quick Start (Local Run)

### Requirements
- Linux (Ubuntu 22.04 LTS or Debian 12 recommended) or Linux VM.
- Docker CE (`>= 24.0`)
- Containerlab (`>= 0.50.0`)
- Python 3.10+ with `venv`

```bash
# 1. Clone repository
git clone https://github.com/Realms4239/isp-network-as-code.git
cd isp-network-as-code

# 2. Deploy virtual network topology
sudo clab deploy -t topology/topology.clab.yml

# 3. Apply configurations via Ansible
cd ansible
ansible-playbook -i inventories/hosts.ini site.yml

# 4. Verify idempotency (should show changed=0)
ansible-playbook -i inventories/hosts.ini site.yml

# 5. Run pyATS automated tests
cd ../pyats
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pyats run job test_job.py --testbed-file testbed.yml

# 6. Destroy lab
sudo clab destroy -t ../topology/topology.clab.yml
```

---

## 🔬 CI/CD Pipeline Stages

Every push triggers GitHub Actions (`.github/workflows/pipeline.yml`):
1. **Lint**: YAML lint, Ansible lint, Flake8 python test validation.
2. **Deploy**: Containerlab deploys SR Linux and FRR nodes in a runner container.
3. **Configure**: Ansible pushes baseline network configurations.
4. **Idempotency Gate**: Ansible re-runs; fails pipeline if any tasks produce changes.
5. **pyATS Validation**: Automated test suites assert protocol state and fail fast if reachability or BGP drops.
6. **Telemetry & Teardown**: Export Prometheus metrics, take test artifacts snapshot, and teardown.
