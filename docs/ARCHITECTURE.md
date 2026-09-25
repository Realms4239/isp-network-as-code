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
  │── yamllint (validates YAML schema across topology/ and ansible/)
  │── ansible-lint (enforces idempotency and best practices)
  └── flake8 (ensures pyATS test script hygiene)
       │
[Execution Stage (Free Ubuntu 22.04 Runner)]
  │── Install Containerlab binary
  │── Deploy Containerlab topology (Nokia SR Linux + FRR containers)
  │── Ansible Run 1: Apply baseline configurations
  │── Ansible Run 2: Verify idempotency (assert changed=0, failed=0)
  │── pyATS Run: Execute automated test suite (asserts protocol states & reachability)
  └── Teardown: Clean up containers and virtual interfaces
```

---

## 3. pyATS Test Assertions

1. `InterfaceOperationalCheck`: Checks interface operational status.
2. `OSPFAdjacencyCheck`: Checks OSPF neighbor table for `Full` adjacency between core nodes.
3. `BGPPeeringCheck`: Confirms BGP peers reach `Established` state and prefixes are exchanged.
4. `EndToEndReachabilityCheck`: Performs bidirectional ping validation between nodes across the fabric.
