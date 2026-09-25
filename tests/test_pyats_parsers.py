"""Offline tests for the pyATS assertions' parsing logic.

`pyats/test_network.py` can only be exercised against a live lab, which is
exactly why real defects survived in it. All parsing now lives in
`pyats/parsers.py`, so the behaviour of every assertion is verifiable here with
no containers, no Docker, and no credentials.

Each test names the defect it prevents from returning.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pyats"))

from parsers import (  # noqa: E402
    frr_bgp_peers,
    frr_peer_is_healthy,
    ping_succeeded,
    prefix_present,
    srl_bgp_peer_established,
    srl_interface_is_up,
    srl_ospf_neighbor_is_full,
)

# --- fixtures modelled on real vendor output ------------------------------

SRL_INTERFACE_BRIEF = """
+-------------------------------+-----------+------------------+
| Interface                     | Admin     | Oper             |
+-------------------------------+-----------+------------------+
| ethernet-1/1                  | enable    | up               |
| ethernet-1/1.0                | enable    | up               |
| ethernet-1/2                  | enable    | up               |
| ethernet-1/2.0                | enable    | up               |
| system0                       | enable    | up               |
| system0.0                     | enable    | up               |
+-------------------------------+-----------+------------------+
"""

SRL_INTERFACE_DOWN = """
+-------------------------------+-----------+------------------+
| Interface                     | Admin     | Oper             |
+-------------------------------+-----------+------------------+
| ethernet-1/1                  | enable    | down             |
| ethernet-1/2                  | enable    | up               |
+-------------------------------+-----------+------------------+
"""

SRL_OSPF_FULL = """
+-------------------------------+------------------+----------+
| Interface                     | Neighbor ID      | State    |
+-------------------------------+------------------+----------+
| ethernet-1/1.0                | 10.1.12.2        | full     |
+-------------------------------+------------------+----------+
 OSPF Instance default
    Router ID : 10.0.0.1
    Number of neighbors : 1
    Full adjacencies : 1
    Bad Neighbors : 0
"""

SRL_OSPF_NOT_FULL = """
+-------------------------------+------------------+----------+
| Interface                     | Neighbor ID      | State    |
+-------------------------------+------------------+----------+
| ethernet-1/1.0                | 10.1.12.2        | exstart  |
+-------------------------------+------------------+----------+
 OSPF Instance default
    Bad Neighbors : 1
"""

SRL_OSPF_FULL_BUT_BAD_NEIGHBOR = SRL_OSPF_FULL.replace("Bad Neighbors : 0", "Bad Neighbors : 1")

SRL_BGP_ESTABLISHED = """
 BGP neighbor detail
    Peer : 10.1.13.2, remote AS : 65002, description : eBGP to FRR01
    BGP state : Established, ...
    session-state is established
"""

SRL_BGP_ACTIVE = """
 BGP neighbor detail
    Peer : 10.1.13.2, remote AS : 65002, description : eBGP to FRR01
    BGP state : Active, ...
    session-state is active
"""

# Real FRR 10.x `show ip bgp summary json`: peers are nested under ipv4Unicast.
FRR_SUMMARY_NESTED = json.dumps(
    {
        "ipv4Unicast": {
            "routerId": "10.0.0.3",
            "as": 65002,
            "peerCount": 2,
            "peers": {
                "10.1.13.1": {
                    "hostname": "srl01",
                    "remoteAs": 65001,
                    "pfxRcd": 1,
                    "pfxSnt": 1,
                    "state": "Established",
                },
                "10.1.23.1": {
                    "hostname": "srl02",
                    "remoteAs": 65001,
                    "pfxRcd": 1,
                    "pfxSnt": 1,
                    "state": "Established",
                },
            },
        }
    }
)

FRR_SUMMARY_TOP_LEVEL = json.dumps(
    {
        "peers": {
            "10.1.13.1": {
                "remoteAs": 65001,
                "pfxRcd": 1,
                "pfxSnt": 1,
                "state": "Established",
            }
        }
    }
)

FRR_SUMMARY_NO_PEERS = json.dumps({"ipv4Unicast": {"routerId": "10.0.0.3", "peerCount": 0}})


# --- SR Linux -------------------------------------------------------------

def test_interface_up_is_detected_for_every_expected_interface():
    for interface in ("ethernet-1/1", "ethernet-1/2", "system0"):
        assert srl_interface_is_up(SRL_INTERFACE_BRIEF, interface), interface


def test_interface_down_is_rejected():
    assert not srl_interface_is_up(SRL_INTERFACE_DOWN, "ethernet-1/1")


def test_ospf_full_with_zero_bad_neighbors():
    assert srl_ospf_neighbor_is_full(SRL_OSPF_FULL, "10.1.12.2")


def test_ospf_exstart_is_rejected():
    assert not srl_ospf_neighbor_is_full(SRL_OSPF_NOT_FULL, "10.1.12.2")


def test_ospf_full_row_but_a_bad_neighbor_still_fails():
    """A 'full' row is not enough while the node also reports a bad neighbor."""
    assert not srl_ospf_neighbor_is_full(SRL_OSPF_FULL_BUT_BAD_NEIGHBOR, "10.1.12.2")


def test_ospf_wrong_neighbor_id_is_rejected():
    assert not srl_ospf_neighbor_is_full(SRL_OSPF_FULL, "10.9.9.9")


def test_bgp_established_peer_is_accepted():
    assert srl_bgp_peer_established(SRL_BGP_ESTABLISHED, "10.1.13.2", "65002")


def test_bgp_active_peer_is_rejected():
    assert not srl_bgp_peer_established(SRL_BGP_ACTIVE, "10.1.13.2", "65002")


def test_bgp_wrong_remote_as_is_rejected():
    """The AS is part of the assertion: a peer on the wrong AS is not healthy."""
    assert not srl_bgp_peer_established(SRL_BGP_ESTABLISHED, "10.1.13.2", "65001")


def test_bgp_wrong_peer_ip_is_rejected():
    assert not srl_bgp_peer_established(SRL_BGP_ESTABLISHED, "10.0.0.2", "65002")


# --- FRRouting ------------------------------------------------------------

def test_frr_peers_are_found_under_the_address_family_block():
    """Regression: peers live under ipv4Unicast, not at the top level.

    The original code called summary.get('peers', {}), which returned {} for a
    perfectly healthy lab and failed the assertion for the wrong reason.
    """
    peers = frr_bgp_peers(FRR_SUMMARY_NESTED)
    assert set(peers) == {"10.1.13.1", "10.1.23.1"}


def test_frr_peers_at_top_level_are_still_supported():
    peers = frr_bgp_peers(FRR_SUMMARY_TOP_LEVEL)
    assert set(peers) == {"10.1.13.1"}


def test_frr_no_peers_is_an_empty_map_not_an_error():
    assert frr_bgp_peers(FRR_SUMMARY_NO_PEERS) == {}


def test_frr_invalid_json_raises_a_named_assertion():
    with pytest.raises(AssertionError, match="valid BGP summary JSON"):
        frr_bgp_peers("not json at all")


def test_frr_non_object_json_is_rejected():
    with pytest.raises(AssertionError, match="should be an object"):
        frr_bgp_peers("[1, 2, 3]")


def test_frr_healthy_peer_passes():
    ok, reasons = frr_peer_is_healthy(
        {"state": "Established", "pfxRcd": 1, "pfxSnt": 1}
    )
    assert ok, reasons


@pytest.mark.parametrize(
    "peer,bad_field",
    [
        ({"state": "Idle", "pfxRcd": 1, "pfxSnt": 1}, "state"),
        ({"state": "Established", "pfxRcd": 0, "pfxSnt": 1}, "pfxRcd"),
        ({"state": "Established", "pfxRcd": 1, "pfxSnt": 0}, "pfxSnt"),
    ],
)
def test_frr_unhealthy_peer_names_the_field(peer, bad_field):
    ok, reasons = frr_peer_is_healthy(peer)
    assert not ok
    assert any(bad_field in reason for reason in reasons), reasons


def test_frr_missing_counters_are_treated_as_zero_not_a_crash():
    ok, reasons = frr_peer_is_healthy({"state": "Established"})
    assert not ok
    assert any("pfxRcd" in r for r in reasons)
    assert any("pfxSnt" in r for r in reasons)


def test_frr_non_numeric_counters_do_not_raise():
    ok, _ = frr_peer_is_healthy(
        {"state": "Established", "pfxRcd": "n/a", "pfxSnt": None}
    )
    assert not ok


# --- routes and reachability ---------------------------------------------

def test_prefix_present_finds_an_installed_route():
    assert prefix_present("10.0.0.2/32  unicast  via 10.1.12.2", "10.0.0.2/32")


def test_prefix_absent_is_reported():
    assert not prefix_present("no routes", "10.0.0.2/32")


def test_ping_srl_style_summary():
    assert ping_succeeded("3 packets transmitted, 3 received, 0% packet loss")


def test_ping_frr_busybox_style_summary():
    assert ping_succeeded("3 packets transmitted, 3 packets received, 0% packet loss")


def test_ping_zero_percent_loss_without_received_counter():
    assert ping_succeeded("rtt min/avg/max = 0.1/0.2/0.3 ms, 0% loss")


def test_ping_failure_is_detected():
    assert not ping_succeeded("3 packets transmitted, 0 received, 100% packet loss")
