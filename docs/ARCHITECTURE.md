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

The assertions live in two places, deliberately separated:

- `pyats/parsers.py` — pure functions that take device *output text* and return a
  verdict. No device, no testbed, no network.
- `pyats/test_network.py` — talks to devices and turns a verdict into an aetest
  assertion.

That split exists because the assertions used to be written inline against
`dev.execute(...)`, which meant **none of them could be verified without a live
lab** — and three real defects survived that way:

1. **FRR peers were read from the wrong JSON level.** Real `show ip bgp summary
   json` nests the peer map under `ipv4Unicast.peers`; the code read only a
   top-level `peers` key, so a healthy lab reported *no peers* and the assertion
   failed for the wrong reason.
2. **One peer's output was checked against every peer.** The BGP loop fetched the
   first peer's detail and then asserted all peers against that single response.
3. **The route assertion could not fail.** `assert prefix in route_text` passed
   whenever vtysh echoed the queried prefix back, whether or not a route existed.

`tests/test_pyats_parsers.py` pins all three with fixtures modelled on real
vendor output, and runs with no containers and no credentials.

The four assertion groups:

1. `InterfaceOperationalCheck`: `ethernet-1/1`, `ethernet-1/2`, and `system0`
   are admin-enabled and operationally up on both SR Linux nodes.
2. `OSPFAdjacencyCheck`: the exact core router ID is `full` **and** the node
   reports zero bad neighbors.
3. `BGPPeeringCheck`: exact peer sets and remote AS values on SRL; on FRR, exact
   peer set, `Established` state, and nonzero `pfxRcd`/`pfxSnt` for each peer.
4. `RouteInstallationCheck` / `EndToEndReachabilityCheck`: remote loopbacks
   installed in every expected table, and bidirectional reachability across all
   three node pairs.

**Why no Genie parsers:** SR Linux and FRR are not Genie-supported platforms. A
Genie parser would silently return empty structures, so the output is treated as
text and the regexes are anchored on the vendors' documented column formats.

