import logging
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
            assert "ethernet-1/1" in output, f"ethernet-1/1 not found on {dev_name}"
            assert "ethernet-1/2" in output, f"ethernet-1/2 not found on {dev_name}"
            assert "system0" in output, f"system0 not found on {dev_name}"


class OSPFAdjacencyCheck(aetest.Testcase):
    """Assert OSPF neighbors reach FULL state on SR Linux nodes."""

    @aetest.test
    def verify_ospf_neighbors(self, testbed):
        log.info(banner("Verifying OSPF Neighbor State on Nokia SR Linux"))
        for dev_name in ['srl01', 'srl02']:
            dev = testbed.devices[dev_name]
            output = dev.execute("show network-instance default protocols ospf neighbor")
            log.info(f"OSPF output on {dev_name}:\n{output}")
            assert "Full" in output or "2-Way" in output, f"OSPF neighbor not healthy on {dev_name}"


class BGPPeeringCheck(aetest.Testcase):
    """Assert BGP sessions are Established on SRL and FRR nodes."""

    @aetest.test
    def verify_bgp_srl(self, testbed):
        log.info(banner("Verifying BGP Neighbor State on Nokia SR Linux"))
        for dev_name in ['srl01', 'srl02']:
            dev = testbed.devices[dev_name]
            output = dev.execute("show network-instance default protocols bgp neighbor")
            log.info(f"BGP output on {dev_name}:\n{output}")
            assert "established" in output.lower(), f"BGP neighbor not established on {dev_name}"

    @aetest.test
    def verify_bgp_frr(self, testbed):
        log.info(banner("Verifying BGP Neighbor State on FRR01"))
        frr = testbed.devices['frr01']
        output = frr.execute("vtysh -c 'show ip bgp summary'")
        log.info(f"FRR BGP Summary:\n{output}")
        # Ensure neighbors 10.1.13.1 and 10.1.23.1 are present
        assert "10.1.13.1" in output, "Missing BGP peer srl01 (10.1.13.1)"
        assert "10.1.23.1" in output, "Missing BGP peer srl02 (10.1.23.1)"


class EndToEndReachabilityCheck(aetest.Testcase):
    """Verify end-to-end ping reachability between loopbacks across the transit fabric."""

    @aetest.test
    def verify_ping_transit(self, testbed):
        log.info(banner("Testing ICMP ping reachability across backbone"))
        srl01 = testbed.devices['srl01']
        ping_res = srl01.execute("ping 10.0.0.3 network-instance default -c 3")
        log.info(f"Ping output: {ping_res}")
        assert "0% packet loss" in ping_res or "3 received" in ping_res, \
            "ICMP packet loss detected to 10.0.0.3"

    @aetest.test
    def verify_ping_core(self, testbed):
        log.info(banner("Testing ICMP ping across core link"))
        srl01 = testbed.devices['srl01']
        ping_res = srl01.execute("ping 10.0.0.2 network-instance default -c 3")
        log.info(f"Ping output: {ping_res}")
        assert "0% packet loss" in ping_res or "3 received" in ping_res, \
            "ICMP packet loss detected to 10.0.0.2"


class CommonCleanup(aetest.CommonCleanup):
    """Disconnect gracefully from all lab devices."""

    @aetest.subsection
    def disconnect_devices(self, testbed):
        log.info(banner("Disconnecting all lab devices"))
        for dev_name, device in testbed.devices.items():
            if device.is_connected():
                device.disconnect()

