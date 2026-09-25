"""Protocol and data-plane assertions for the Phase 0 ISP backbone.

All parsing lives in `parsers.py`, which is pure and covered by
tests/test_pyats_parsers.py. This module only talks to devices and turns a
verdict into an aetest assertion, so the interesting logic stays verifiable
without a live lab.
"""
import json
import logging

from pyats import aetest
from pyats.log.utils import banner

from parsers import (
    frr_bgp_peers,
    frr_peer_is_healthy,
    ping_succeeded,
    prefix_present,
    srl_bgp_peer_established,
    srl_interface_is_up,
    srl_ospf_neighbor_is_full,
)

log = logging.getLogger(__name__)


class CommonSetup(aetest.CommonSetup):
    """Connect to all testbed network devices."""

    @aetest.subsection
    def connect_to_devices(self, testbed):
        log.info(banner("Connecting to all lab devices"))
        for dev_name, device in testbed.devices.items():
            log.info(f"Connecting to {dev_name}...")
            device.connect(via='cli', log_stdout=False)
            assert device.is_connected(), f"Failed to connect to device {dev_name}"


class InterfaceOperationalCheck(aetest.Testcase):
    """Verify physical and logical interfaces are administratively and operationally UP."""

    @aetest.test
    def verify_interfaces(self, testbed):
        log.info(banner("Asserting interface oper-status"))
        for dev_name in ['srl01', 'srl02']:
            dev = testbed.devices[dev_name]
            output = dev.execute("show interface brief")
            log.info(f"Interface summary for {dev_name}:\n{output}")
            for interface in ("ethernet-1/1", "ethernet-1/2", "system0"):
                assert srl_interface_is_up(output, interface), (
                    f"{interface} is not administratively and operationally up on {dev_name}"
                )


class OSPFAdjacencyCheck(aetest.Testcase):
    """Assert OSPF neighbors reach FULL state on SR Linux nodes."""

    @aetest.test
    def verify_ospf_neighbors(self, testbed):
        log.info(banner("Verifying OSPF Neighbor State on Nokia SR Linux"))
        expected_neighbors = {"srl01": "10.1.12.2", "srl02": "10.1.12.1"}
        for dev_name, expected_router_id in expected_neighbors.items():
            dev = testbed.devices[dev_name]
            output = dev.execute("show network-instance default protocols ospf neighbor")
            log.info(f"OSPF output on {dev_name}:\n{output}")
            assert srl_ospf_neighbor_is_full(output, expected_router_id), (
                f"OSPF neighbor {expected_router_id} is not FULL on {dev_name} "
                f"(or the node reports bad neighbors)"
            )


class BGPPeeringCheck(aetest.Testcase):
    """Assert BGP sessions are Established on SRL and FRR nodes."""

    @aetest.test
    def verify_bgp_srl(self, testbed):
        log.info(banner("Verifying BGP Neighbor State on Nokia SR Linux"))
        expected_peers = {
            "srl01": {"10.1.13.2": "65002", "10.0.0.2": "65001"},
            "srl02": {"10.1.23.2": "65002", "10.0.0.1": "65001"},
        }
        for dev_name, peers in expected_peers.items():
            dev = testbed.devices[dev_name]
            for peer_ip, remote_as in peers.items():
                # Ask for this specific peer. The previous code fetched one peer's
                # detail and then asserted every peer against that same output,
                # so the iBGP peer was validated against the eBGP peer's response.
                peer_detail = dev.execute(
                    "show network-instance default protocols bgp "
                    f"neighbor {peer_ip} detail"
                )
                log.info(f"BGP detail {dev_name} -> {peer_ip}:\n{peer_detail}")
                assert srl_bgp_peer_established(peer_detail, peer_ip, remote_as), (
                    f"BGP peer {peer_ip} AS{remote_as} is not established on {dev_name}"
                )

    @aetest.test
    def verify_bgp_frr(self, testbed):
        log.info(banner("Verifying BGP Neighbor State on FRR01"))
        frr = testbed.devices['frr01']
        output = frr.execute("vtysh -c 'show ip bgp summary json'")
        log.info(f"FRR BGP Summary JSON:\n{output}")
        peers = frr_bgp_peers(output)
        expected_peers = {
            "10.1.13.1": 65001,
            "10.1.23.1": 65001,
        }
        assert set(peers) == set(expected_peers), (
            f"Unexpected FRR BGP peer set: got {sorted(peers)}, "
            f"expected {sorted(expected_peers)}"
        )
        for peer_ip, expected_as in expected_peers.items():
            peer = peers[peer_ip]
            assert peer.get("remoteAs") == expected_as, (
                f"FRR peer {peer_ip} remoteAs is {peer.get('remoteAs')!r}, "
                f"expected {expected_as}"
            )
            ok, reasons = frr_peer_is_healthy(peer)
            assert ok, f"FRR peer {peer_ip} is not healthy: {'; '.join(reasons)}"


class RouteInstallationCheck(aetest.Testcase):
    """Verify remote loopbacks are installed in every expected routing table."""

    @aetest.test
    def verify_srl_routes(self, testbed):
        expected_routes = {
            "srl01": {"10.0.0.2/32", "10.0.0.3/32"},
            "srl02": {"10.0.0.1/32", "10.0.0.3/32"},
        }
        for dev_name, prefixes in expected_routes.items():
            for prefix in prefixes:
                output = testbed.devices[dev_name].execute(
                    "show network-instance default route-table ipv4-unicast "
                    f"prefix {prefix} detail"
                )
                log.info(f"Route {prefix} on {dev_name}:\n{output}")
                assert prefix_present(output, prefix), (
                    f"Missing route {prefix} on {dev_name}"
                )

    @aetest.test
    def verify_frr_routes(self, testbed):
        frr = testbed.devices["frr01"]
        for prefix in ("10.0.0.1/32", "10.0.0.2/32"):
            output = frr.execute(f"vtysh -c 'show ip route {prefix} json'")
            log.info(f"FRR route {prefix}:\n{output}")
            # `show ip route <prefix> json` returns
            #   {"10.0.0.1/32": [{...route entries...}]}
            # so the prefix is a key in a dict. Testing `prefix in output` on the
            # raw string, or on the parsed dict, only proves the query echoed
            # back what we asked for -- not that a route exists. An unknown
            # prefix returns {} instead, so require at least one route entry.
            try:
                routes = json.loads(output)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"FRR did not return valid route JSON for {prefix}: {exc}"
                ) from exc
            entries = routes.get(prefix)
            assert entries, (
                f"No route installed for {prefix} on frr01 (vtysh returned "
                f"{routes!r})"
            )
            assert len(entries) > 0, f"Empty route list for {prefix} on frr01"


class EndToEndReachabilityCheck(aetest.Testcase):
    """Verify bidirectional loopback reachability across every backbone path."""

    @staticmethod
    def _assert_ping(device_name, device, destination):
        if device_name.startswith("frr"):
            command = f"ping -c 3 {destination}"
        else:
            command = f"ping {destination} -c 3 network-instance default"
        result = device.execute(command)
        log.info(f"Ping {destination} from {device_name}:\n{result}")
        assert ping_succeeded(result), (
            f"ICMP failure from {device_name} to {destination}"
        )

    @aetest.test
    def verify_bidirectional_reachability(self, testbed):
        paths = (
            ("srl01", "10.0.0.2"),
            ("srl02", "10.0.0.1"),
            ("srl01", "10.0.0.3"),
            ("frr01", "10.0.0.1"),
            ("srl02", "10.0.0.3"),
            ("frr01", "10.0.0.2"),
        )
        for source, destination in paths:
            self._assert_ping(source, testbed.devices[source], destination)


class CommonCleanup(aetest.CommonCleanup):
    """Disconnect gracefully from all lab devices."""

    @aetest.subsection
    def disconnect_devices(self, testbed):
        log.info(banner("Disconnecting all lab devices"))
        for dev_name, device in testbed.devices.items():
            if device.is_connected():
                device.disconnect()
