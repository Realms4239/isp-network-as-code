import json
import logging
import re
from pyats import aetest
from pyats.log.utils import banner

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
            expected = {"ethernet-1/1", "ethernet-1/2"}
            for interface in expected:
                match = re.search(
                    rf"\|\s*{re.escape(interface)}\s*\|\s*enable\s*\|\s*up\s*\|",
                    output,
                    re.IGNORECASE,
                )
                assert match, f"{interface} is not administratively and operationally up on {dev_name}"
            assert re.search(
                r"\|\s*system0(?:\.0)?\s*\|\s*enable\s*\|\s*up\s*\|",
                output,
                re.IGNORECASE,
            ), f"system0 is not up on {dev_name}"


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
            pattern = rf"\|\s*ethernet-1/1\.0\s*\|\s*{re.escape(expected_router_id)}\s*\|\s*full\s*\|"
            assert re.search(pattern, output, re.IGNORECASE), (
                f"OSPF neighbor {expected_router_id} is not FULL on {dev_name}"
            )
            assert re.search(r"Bad Neighbors\s*:\s*0", output, re.IGNORECASE)


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
            output = dev.execute("show network-instance default protocols bgp neighbor")
            log.info(f"BGP output on {dev_name}:\n{output}")
            for peer_ip, remote_as in peers.items():
                detail = dev.execute(
                    f"show network-instance default protocols bgp neighbor {peer_ip} detail"
                )
                assert re.search(
                    rf"Peer\s*:\s*{re.escape(peer_ip)},\s*remote AS:\s*{remote_as},",
                    detail,
                    re.IGNORECASE,
                ), f"Missing BGP peer {peer_ip} AS{remote_as} on {dev_name}"
                assert re.search(
                    r"session-state is established", detail, re.IGNORECASE
                ), f"BGP peer {peer_ip} is not established on {dev_name}"

    @aetest.test
    def verify_bgp_frr(self, testbed):
        log.info(banner("Verifying BGP Neighbor State on FRR01"))
        frr = testbed.devices['frr01']
        output = frr.execute("vtysh -c 'show ip bgp summary json'")
        log.info(f"FRR BGP Summary JSON:\n{output}")
        try:
            summary = json.loads(output)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"FRR did not return valid BGP summary JSON: {exc}") from exc
        peers = summary.get("peers", {})
        expected_peers = {
            "10.1.13.1": {"remoteAs": 65001, "state": "Established"},
            "10.1.23.1": {"remoteAs": 65001, "state": "Established"},
        }
        assert set(peers) == set(expected_peers), f"Unexpected FRR BGP peer set: {sorted(peers)}"
        for peer_ip, expected in expected_peers.items():
            peer = peers[peer_ip]
            assert peer.get("remoteAs") == expected["remoteAs"]
            assert peer.get("state") == expected["state"]
            assert int(peer.get("pfxRcd", 0)) > 0, f"FRR received no routes from {peer_ip}"
            assert int(peer.get("pfxSnt", 0)) > 0, f"FRR advertised no routes to {peer_ip}"


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
                    f"show network-instance default route-table ipv4-unicast prefix {prefix} detail"
                )
                log.info(f"Route {prefix} on {dev_name}:\n{output}")
                assert prefix in output, f"Missing route {prefix} on {dev_name}"

    @aetest.test
    def verify_frr_routes(self, testbed):
        output = testbed.devices["frr01"].execute("vtysh -c 'show ip route 10.0.0.1/32 json'")
        log.info(f"FRR route 10.0.0.1/32:\n{output}")
        try:
            route = json.loads(output)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"FRR did not return valid route JSON: {exc}") from exc
        assert "10.0.0.1/32" in route, "Missing route 10.0.0.1/32 on frr01"
        output = testbed.devices["frr01"].execute("vtysh -c 'show ip route 10.0.0.2/32 json'")
        log.info(f"FRR route 10.0.0.2/32:\n{output}")
        try:
            route = json.loads(output)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"FRR did not return valid route JSON: {exc}") from exc
        assert "10.0.0.2/32" in route, "Missing route 10.0.0.2/32 on frr01"


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
        assert re.search(r"3 received|0% packet loss", result, re.IGNORECASE), (
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
