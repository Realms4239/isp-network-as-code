# Flagship Technical Architecture & Specifications

## 1. Network Topology Specification

### Addressing Plan
| Node | Interface | IPv4 Address | Subnet Mask | Role / Connection |
|------|-----------|--------------|-------------|-------------------|
| `srl01` | `system0.0` | 10.0.0.1 | /32 | Loopback / Router ID |
| `srl01` | `ethernet-1/1.0` | 10.1.12.1 | /24 | Core link to `srl02` (OSPF A0) |
| `srl01` | `ethernet-1/2.0` | 10.1.13.1 | /24 | Transit link to `frr01` (eBGP) |
| `srl02` | `system0.0` | 10.0.0.2 | /32 | Loopback / Router ID |
| `srl02` | `ethernet-1/1.0` | 10.1.12.2 | /24 | Core link to `srl01` (OSPF A0) |
| `srl02` | `ethernet-1/2.0` | 10.1.23.1 | /24 | Transit link to `frr01` (eBGP) |
| `frr01` | `lo` | 10.0.0.3 | /32 | Loopback / Router ID |
| `frr01` | `eth1` | 10.1.13.2 | /24 | Transit link to `srl01` (eBGP) |
| `frr01` | `eth2` | 10.1.23.2 | /24 | Transit link to `srl02` (eBGP) |

### Routing Protocol Design
- **OSPFv2 (RFC 2328)**:
  - Backbone Area: `0.0.0.0`
  - Enabled on `ethernet-1/1.0` (point-to-point network type)
  - Passive interface on `system0.0` (loopback advertised into OSPF without emitting Hellos)
- **BGP-4 (RFC 4271)**:
  - ASN 65001: Internal Autonomous System (`srl01`, `srl02`)
  - ASN 65002: Upstream Transit ISP (`frr01`)
  - Peering: `frr01` establishes eBGP sessions to `10.1.13.1` and `10.1.23.1`.

---

## 2. CI/CD Pipeline Flow

The GitHub Actions workflow (`.github/workflows/pipeline.yml`) executes the following stages:

```
[Lint Stage]
  │── Cross-file contract validator and negative tests
  │── yamllint (validates YAML schema across topology/ and ansible/)
  │── ansible-lint (enforces idempotency and best practices)
  └── flake8 (ensures pyATS test script hygiene)
       │
[Execution Stage (Free Ubuntu 22.04 Runner)]
  │── Install pinned Containerlab, Python, and Ansible dependencies
  │── Deploy Containerlab topology (Nokia SR Linux + SSH-capable FRR image)
  │── Ansible Run 1: Apply and persist baseline configurations
  │── Ansible Run 2: Parse JSON callback; require changed=0, failed=0, unreachable=0
  │── pyATS Run: Assert interfaces, OSPF FULL, exact BGP peers, routes, and bidirectional ping
  ├── Collect inspect state, logs, and machine-readable Ansible output on failure
  └── Teardown with if: always(): clean up containers and virtual interfaces
```

---

## 3. pyATS Test Assertions

1. `InterfaceOperationalCheck`: Requires `ethernet-1/1`, `ethernet-1/2`, and `system0` to be admin-enabled and operationally up.
2. `OSPFAdjacencyCheck`: Requires the exact core router ID and `full` state on each SR Linux node.
3. `BGPPeeringCheck`: Requires the exact SR Linux and FRR peer sets, AS numbers, `Established` state, and nonzero prefix counts.
4. `RouteInstallationCheck`: Looks up each remote loopback in the SR Linux route table and records FRR route evidence.
5. `EndToEndReachabilityCheck`: Performs bidirectional ping validation for all three node pairs.
