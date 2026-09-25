#!/usr/bin/env python3
"""Validate the cross-file contracts for the Phase 0 ISP lab."""

from __future__ import annotations

import argparse
import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FILES = (
    "data/lab.yml",
    "topology/topology.clab.yml",
    "ansible/inventories/hosts.ini",
    "ansible/requirements.yml",
    "pyats/testbed.yml",
    "pyats/test_network.py",
    "pyats/requirements.txt",
    "ansible/plugins/callback/lab_json.py",
    "scripts/lab_evidence.py",
    "scripts/wait_for_lab.py",
    ".github/workflows/pipeline.yml",
    ".github/dependabot.yml",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
)


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_yaml_checked(path: Path, errors: list[str]) -> Any:
    try:
        return load_yaml(path)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"cannot parse YAML {path}: {exc}")
        return {}


def read_text_checked(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return ""


def as_mapping(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be a mapping")
        return {}
    return value


def _is_ip_network(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return True


def _bgp_peer_set(peers: Any, label: str, errors: list[str]) -> set[tuple[str, int]]:
    if not isinstance(peers, list):
        errors.append(f"{label}.bgp_peers must be a list")
        return set()
    result: set[tuple[str, int]] = set()
    for peer in peers:
        if not isinstance(peer, dict):
            errors.append(f"{label}: each BGP peer must be a mapping")
            continue
        peer_ip = peer.get("peer_ip")
        remote_as = peer.get("remote_as")
        description = peer.get("description", "")
        try:
            ipaddress.ip_address(str(peer_ip))
        except (TypeError, ValueError):
            errors.append(f"{label}: BGP peer_ip is not an IP address: {peer_ip!r}")
            continue
        if not isinstance(remote_as, int) or isinstance(remote_as, bool) or not 1 <= remote_as <= 4294967295:
            errors.append(f"{label}: BGP remote_as is not a valid 32-bit ASN: {remote_as!r}")
            continue
        if not isinstance(description, str) or not re.fullmatch(r"[A-Za-z0-9 ._/-]{0,64}", description):
            errors.append(f"{label}: BGP description contains unsupported characters: {description!r}")
            continue
        result.add((str(peer_ip), remote_as))
    return result


def load_inventory(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    hosts: dict[str, dict[str, str]] = {}
    groups: dict[str, set[str]] = {}
    current_group: str | None = None
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            if current_section.endswith(":vars"):
                current_group = None
                current_section = "vars"
            elif current_section.endswith(":children"):
                current_group = current_section.removesuffix(":children")
                groups.setdefault(current_group, set())
                current_section = "children"
            else:
                current_group = current_section
                groups.setdefault(current_group, set())
                current_section = "hosts"
            continue
        if current_section == "vars":
            if "=" not in line:
                raise ValueError(f"invalid inventory group variable line: {line!r}")
            continue
        if current_group is None:
            continue
        if "=" in line:
            host, assignments = line.split(maxsplit=1)
            values = {}
            for assignment in assignments.split():
                if "=" not in assignment:
                    raise ValueError(f"invalid inventory assignment on line: {line!r}")
                key, value = assignment.split("=", 1)
                if not key or not value:
                    raise ValueError(f"invalid inventory assignment on line: {line!r}")
                values[key] = value
            hosts[host] = values
            groups.setdefault(current_group, set()).add(host)
        else:
            groups.setdefault(current_group, set()).add(line.split()[0])
    return hosts, groups


def parse_link(link: dict[str, Any], nodes: set[str], errors: list[str]) -> tuple[str, str, str, str] | None:
    if not isinstance(link, dict):
        errors.append(f"link must be a mapping: {link!r}")
        return None
    endpoints = link.get("endpoints", [])
    if len(endpoints) != 2 or not all(isinstance(item, str) for item in endpoints):
        errors.append(f"link must have exactly two string endpoints: {link!r}")
        return None
    parsed: list[tuple[str, str]] = []
    for endpoint in endpoints:
        if ":" not in endpoint:
            errors.append(f"invalid link endpoint: {endpoint!r}")
            return None
        node, interface = endpoint.rsplit(":", 1)
        if not node or not interface:
            errors.append(f"invalid link endpoint: {endpoint!r}")
            return None
        if node not in nodes:
            errors.append(f"link references unknown node {node!r}")
            return None
        parsed.append((node, interface))
    return parsed[0][0], parsed[0][1], parsed[1][0], parsed[1][1]


def _check_secret_literals(root: Path, errors: list[str]) -> None:
    paths = (
        "ansible/group_vars/srlinux.yml",
        "ansible/group_vars/frr.yml",
        "pyats/testbed.yml",
        ".github/workflows/pipeline.yml",
    )
    safe_markers = (
        "lookup(",
        "%ENV{",
        "${{ secrets.",
        "<redacted>",
        "os.environ",
        "lookup('env'",
    )
    for relative in paths:
        text = read_text_checked(root / relative, errors)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not re.search(r"(?i)(password|passwd|secret|token)[A-Za-z0-9_-]*\s*[:=]", line):
                continue
            if not any(marker in line for marker in safe_markers):
                errors.append(f"{relative}:{line_number}: literal secret assignment is not allowed")


def _check_bind_mounts(root: Path, topology: dict[str, Any], errors: list[str]) -> None:
    section = as_mapping(topology.get("topology"), "topology.topology", errors)
    nodes = as_mapping(section.get("nodes"), "topology.topology.nodes", errors)
    for node_name, node_value in nodes.items():
        binds = as_mapping(node_value, f"topology node {node_name}", errors).get("binds", []) or []
        for bind in binds:
            if not isinstance(bind, str) or ":" not in bind:
                errors.append(f"{node_name}: bind mount must be a string of the form source:destination")
                continue
            source = bind.split(":", 1)[0]
            if not (source.startswith("../.lab/") or source.startswith(".lab/")):
                errors.append(f"{node_name}: bind source must stay inside .lab/: {source!r}")


def _check_ansible_requirements(root: Path, errors: list[str]) -> None:
    requirements = as_mapping(
        load_yaml_checked(root / "ansible/requirements.yml", errors),
        "ansible/requirements.yml",
        errors,
    )
    versions = {
        item.get("name"): item.get("version")
        for item in requirements.get("collections", []) or []
        if isinstance(item, dict)
    }
    if versions != {
        "nokia.srlinux": "1.1.1",
        "ansible.netcommon": "8.7.1",
        "ansible.utils": "6.1.1",
    }:
        errors.append(f"Ansible collection versions are not pinned to the tested matrix: {versions}")


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"required file is missing: {relative}")
    if errors:
        return errors

    plan = as_mapping(load_yaml_checked(root / "data/lab.yml", errors), "data/lab.yml", errors)
    if plan.get("version") != 1:
        errors.append("data/lab.yml: version must be 1")
    if not isinstance(plan.get("name"), str) or not plan.get("name"):
        errors.append("data/lab.yml: name is required")
    security = as_mapping(plan.get("security"), "data/lab.yml.security", errors)
    if security.get("lab_only") is not True:
        errors.append("data/lab.yml.security.lab_only must be true")
    if security.get("management_transport") not in {"http", "https"}:
        errors.append("data/lab.yml.security.management_transport must be http or https")
    if security.get("ssh_host_key_checking") not in {"disabled", "enabled"}:
        errors.append("data/lab.yml.security.ssh_host_key_checking must be declared")
    topology = as_mapping(load_yaml_checked(root / "topology/topology.clab.yml", errors), "topology", errors)
    topology_section = as_mapping(topology.get("topology"), "topology.topology", errors)
    nodes = as_mapping(topology_section.get("nodes"), "topology.topology.nodes", errors)
    node_names = set(nodes)
    if not node_names:
        errors.append("topology must define nodes")

    try:
        inventory, groups = load_inventory(root / "ansible/inventories/hosts.ini")
    except (OSError, ValueError) as exc:
        errors.append(f"cannot read ansible inventory: {exc}")
        inventory, groups = {}, {}
    if set(inventory) != node_names:
        errors.append(f"inventory/topology host mismatch: inventory={sorted(inventory)} topology={sorted(node_names)}")

    node_types = as_mapping(plan.get("node_types"), "data/lab.yml.node_types", errors)
    plan_nodes = as_mapping(plan.get("nodes"), "data/lab.yml.nodes", errors)
    if set(plan_nodes) != node_names:
        errors.append(f"plan/topology host mismatch: plan={sorted(plan_nodes)} topology={sorted(node_names)}")

    mgmt = as_mapping(topology.get("mgmt"), "topology.mgmt", errors)
    plan_mgmt = as_mapping(plan.get("management"), "data/lab.yml.management", errors)
    try:
        management_network = ipaddress.ip_network(mgmt["ipv4-subnet"], strict=True)
        if str(management_network) != plan_mgmt.get("ipv4_subnet"):
            errors.append("topology management subnet does not match data/lab.yml")
        if mgmt.get("network") != plan_mgmt.get("network"):
            errors.append("topology management network does not match data/lab.yml")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid management subnet: {exc}")
        management_network = None

    topology_groups = as_mapping(topology_section.get("groups"), "topology.topology.groups", errors)
    expected_groups: dict[str, dict[str, Any]] = {}
    for type_name, spec_value in node_types.items():
        spec = as_mapping(spec_value, f"node type {type_name}", errors)
        for field in ("topology_group", "ansible_group", "role", "kind", "image"):
            if not isinstance(spec.get(field), str) or not spec.get(field):
                errors.append(f"node type {type_name}: {field} is required")
        if "latest" in str(spec.get("image", "")).lower():
            errors.append(f"node type {type_name}: image must be pinned, not latest")
        for field in ("allowed_interfaces", "required_host_vars"):
            if not isinstance(spec.get(field), list) or not spec.get(field):
                errors.append(f"node type {type_name}: {field} must be a non-empty list")
        group_name = spec.get("topology_group")
        if not isinstance(group_name, str) or not group_name:
            continue
        expected_groups[group_name] = {
            "kind": spec.get("kind"),
            "image": spec.get("image"),
            **({"type": spec["type"]} if "type" in spec else {}),
        }

    dynamic_files: set[str] = set()
    for type_name, spec_value in node_types.items():
        spec = as_mapping(spec_value, f"node type {type_name}", errors)
        group_name = spec.get("ansible_group")
        role_name = spec.get("role")
        if isinstance(group_name, str) and group_name:
            dynamic_files.add(f"ansible/group_vars/{group_name}.yml")
        if isinstance(role_name, str) and role_name:
            dynamic_files.add(f"ansible/roles/{role_name}/tasks/main.yml")
            if role_name == "srlinux_ospf":
                dynamic_files.add("ansible/roles/srlinux_ospf/vars/main.yml")
            if role_name == "frr_bgp":
                dynamic_files.update(
                    {
                        "ansible/roles/frr_bgp/templates/daemons",
                        "ansible/roles/frr_bgp/templates/vtysh.conf",
                        "ansible/roles/frr_bgp/templates/frr.conf.j2",
                    }
                )
    dynamic_files.update(
        f"ansible/host_vars/{name}.yml" for name in plan_nodes
    )
    for relative in sorted(dynamic_files):
        if not (root / relative).is_file():
            errors.append(f"required file is missing: {relative}")

    for group_name, expected in expected_groups.items():
        actual = as_mapping(topology_groups.get(group_name), f"topology group {group_name}", errors)
        for key, value in expected.items():
            if actual.get(key) != value:
                errors.append(f"topology group {group_name} does not match data/lab.yml node type")

    frr_types = {
        name: spec for name, spec in node_types.items()
        if as_mapping(spec, f"node type {name}", errors).get("ansible_group") == "frr"
    }
    frr_type_names = set(frr_types)
    frr_nodes = {
        name: as_mapping(node, f"plan node {name}", errors)
        for name, node in plan_nodes.items()
        if as_mapping(node, f"plan node {name}", errors).get("type") in frr_type_names
    }
    required_frr_bind_targets = {"/etc/frr/daemons", "/etc/frr/frr.conf", "/etc/frr/vtysh.conf"}
    for frr_name, frr_node in frr_nodes.items():
        frr_binds = as_mapping(nodes.get(frr_name), f"topology node {frr_name}", errors).get("binds", []) or []
        bound_targets = {
            item.split(":")[1]
            for item in frr_binds
            if isinstance(item, str) and len(item.split(":")) >= 2
        }
        if not required_frr_bind_targets.issubset(bound_targets):
            errors.append(f"{frr_name}: FRR node must bind daemons, frr.conf, and vtysh.conf")
        frr_spec = as_mapping(frr_types.get(frr_node.get("type")), f"node type {frr_node.get('type')}", errors)
        for required in frr_spec.get("required_binds", []) or []:
            if not any(str(required) in str(item) for item in frr_binds):
                errors.append(f"{frr_name}: topology is missing prepared lab bind: {required}")

    for name, node_value in nodes.items():
        node = as_mapping(node_value, f"topology node {name}", errors)
        planned = as_mapping(plan_nodes.get(name), f"plan node {name}", errors)
        expected_group = planned.get("group")
        if node.get("group") != expected_group:
            errors.append(f"{name}: topology group does not match data/lab.yml")
        address = node.get("mgmt-ipv4")
        if address != planned.get("mgmt_ipv4"):
            errors.append(f"{name}: management address does not match data/lab.yml")
        try:
            if management_network and ipaddress.ip_address(address) not in management_network:
                errors.append(f"{name}: management address {address!r} is outside {management_network}")
        except (TypeError, ValueError) as exc:
            errors.append(f"{name}: invalid management address {address!r}: {exc}")
        if address != inventory.get(name, {}).get("ansible_host"):
            errors.append(f"{name}: topology management address does not match inventory ansible_host")

    expected_group_members: dict[str, set[str]] = {}
    for planned_name, planned_node_value in plan_nodes.items():
        planned = as_mapping(planned_node_value, f"plan node {planned_name}", errors)
        type_spec = as_mapping(node_types.get(planned.get("type")), f"node type {planned.get('type')}", errors)
        group_name = type_spec.get("ansible_group")
        if isinstance(group_name, str):
            expected_group_members.setdefault(group_name, set()).add(planned_name)
    for group_name, type_spec_value in node_types.items():
        type_spec = as_mapping(type_spec_value, f"node type {group_name}", errors)
        group_name = type_spec.get("ansible_group")
        if (
            isinstance(group_name, str)
            and groups.get(group_name, set()) != expected_group_members.get(group_name, set())
        ):
            errors.append(f"inventory group {group_name} does not match data/lab.yml nodes")

    topology_links = topology_section.get("links", []) or []
    plan_links = plan.get("links", []) or []
    if not isinstance(topology_links, list) or not isinstance(plan_links, list):
        errors.append("topology and plan links must be lists")
        topology_links = topology_links if isinstance(topology_links, list) else []
        plan_links = plan_links if isinstance(plan_links, list) else []
    if len(topology_links) != len(plan_links):
        errors.append(f"topology/plan link count mismatch: topology={len(topology_links)} plan={len(plan_links)}")
    supported_protocols = {"ospf", "bgp"}
    for index, plan_link in enumerate(plan_links):
        link_spec = as_mapping(plan_link, f"plan link {index}", errors)
        protocols = link_spec.get("protocols")
        if not isinstance(protocols, list) or not protocols or not set(protocols).issubset(supported_protocols):
            errors.append(f"data/lab.yml.links[{index}].protocols must be a non-empty list of ospf/bgp")

    link_pairs: set[frozenset[str]] = set()
    used_interfaces: set[tuple[str, str]] = set()
    for index, link in enumerate(topology_links):
        if not isinstance(link, dict):
            errors.append(f"topology link {index} must be a mapping")
            continue
        parsed = parse_link(link, node_names, errors)
        if not parsed:
            continue
        left_node, left_if, right_node, right_if = parsed
        if left_node == right_node:
            errors.append(f"a link cannot connect two interfaces on {left_node}")
        pair = frozenset((left_node, right_node))
        if pair in link_pairs:
            errors.append(f"duplicate topology link between {sorted(pair)}")
        link_pairs.add(pair)
        for node_name, interface in ((left_node, left_if), (right_node, right_if)):
            if (node_name, interface) in used_interfaces:
                errors.append(f"interface {interface} is used more than once on {node_name}")
            used_interfaces.add((node_name, interface))
            planned = as_mapping(plan_nodes.get(node_name), f"plan node {node_name}", errors)
            type_spec = as_mapping(node_types.get(planned.get("type")), f"node type {planned.get('type')}", errors)
            if interface not in (type_spec.get("allowed_interfaces", []) or []):
                errors.append(f"{node_name}: interface {interface!r} is not allowed by its node type")
        if index < len(plan_links):
            plan_link = as_mapping(plan_links[index], f"plan link {index}", errors)
            if link.get("endpoints") != plan_link.get("endpoints"):
                errors.append(f"topology link {index} does not match data/lab.yml")

    group_vars = {
        group: as_mapping(
            load_yaml_checked(root / "ansible/group_vars" / f"{group}.yml", errors),
            f"group vars {group}.yml",
            errors,
        )
        for group in {
            as_mapping(spec, "node type", errors).get("ansible_group")
            for spec in node_types.values()
        }
        if isinstance(group, str)
    }
    for type_name, type_spec_value in node_types.items():
        type_spec = as_mapping(type_spec_value, f"node type {type_name}", errors)
        group_name = type_spec.get("ansible_group")
        variables = group_vars.get(group_name, {})
        expected_as = type_spec.get("as_number")
        if expected_as is not None and variables.get("as_number") != expected_as:
            errors.append(f"group vars {group_name}.yml: as_number does not match data/lab.yml")
        required_group_vars = ["as_number"] + (["ospf_area"] if type_spec.get("role") == "srlinux_ospf" else [])
        for required in required_group_vars:
            if required not in variables:
                errors.append(f"group vars {group_name}.yml: {required!r} is missing")

    testbed = as_mapping(load_yaml_checked(root / "pyats/testbed.yml", errors), "pyats/testbed.yml", errors)
    devices = as_mapping(testbed.get("devices"), "pyats.testbed.devices", errors)
    if set(devices) != set(plan_nodes):
        errors.append(f"testbed/plan host mismatch: testbed={sorted(devices)} plan={sorted(plan_nodes)}")
    for name, planned_value in plan_nodes.items():
        planned = as_mapping(planned_value, f"plan node {name}", errors)
        device = as_mapping(devices.get(name), f"testbed device {name}", errors)
        connections = as_mapping(device.get("connections"), f"testbed device {name}.connections", errors)
        cli = as_mapping(connections.get("cli"), f"testbed device {name}.connections.cli", errors)
        if cli.get("protocol") != "ssh" or cli.get("ip") != planned.get("mgmt_ipv4") or cli.get("port") != 22:
            errors.append(f"testbed device {name}: SSH connection does not match data/lab.yml")

    pyats_plan = as_mapping(plan.get("pyats"), "data/lab.yml.pyats", errors)
    for section in ("interfaces", "ospf_neighbors", "routes", "reachability"):
        if section not in pyats_plan:
            errors.append(f"data/lab.yml.pyats: {section} is required")
    for section in ("interfaces", "routes"):
        section_data = as_mapping(pyats_plan.get(section), f"data/lab.yml.pyats.{section}", errors)
        if set(section_data) != set(plan_nodes):
            errors.append(f"data/lab.yml.pyats.{section} must cover every planned node")
        for name, expected in section_data.items():
            if not isinstance(expected, list) or not expected:
                errors.append(f"data/lab.yml.pyats.{section}.{name} must be a non-empty list")
            for item in expected if isinstance(expected, list) else []:
                if section == "routes" and not _is_ip_network(item):
                    errors.append(f"data/lab.yml.pyats.routes.{name} contains an invalid prefix: {item!r}")
                if section == "interfaces" and not isinstance(item, str):
                    errors.append(f"data/lab.yml.pyats.interfaces.{name} contains a non-string interface")
    ospf_nodes = as_mapping(pyats_plan.get("ospf_neighbors"), "data/lab.yml.pyats.ospf_neighbors", errors)
    if not ospf_nodes or not set(ospf_nodes).issubset(plan_nodes):
        errors.append("data/lab.yml.pyats.ospf_neighbors must be a non-empty subset of planned nodes")
    for name, expected in ospf_nodes.items():
        if not isinstance(expected, str):
            errors.append(f"data/lab.yml.pyats.ospf_neighbors.{name} must be a string")
    reachability = pyats_plan.get("reachability", [])
    if not isinstance(reachability, list) or any(
        not isinstance(path, list) or len(path) != 2 or path[0] not in plan_nodes
        for path in reachability
    ):
        errors.append("data/lab.yml.pyats.reachability must contain [node, destination] pairs")

    expected_bgp: dict[str, set[tuple[str, int]]] = {}
    for name in sorted(node_names):
        planned = as_mapping(plan_nodes.get(name), f"plan node {name}", errors)
        type_spec = as_mapping(node_types.get(planned.get("type")), f"node type {planned.get('type')}", errors)
        host_vars_path = root / "ansible/host_vars" / f"{name}.yml"
        if not host_vars_path.exists():
            errors.append(f"host vars missing for {name}")
            continue
        host_vars = as_mapping(load_yaml_checked(host_vars_path, errors), f"host vars {name}.yml", errors)
        planned_vars = as_mapping(planned.get("host_vars"), f"plan node {name}.host_vars", errors)
        for variable in type_spec.get("required_host_vars", []) or []:
            if variable not in host_vars:
                errors.append(f"{name}: host var {variable!r} is missing")
        for variable, expected in planned_vars.items():
            if variable == "bgp_peers":
                continue
            actual = host_vars.get(variable)
            if actual != expected:
                errors.append(f"{name}: {variable} is {actual!r}, expected {expected!r} from data/lab.yml")
            try:
                ipaddress.ip_interface(str(actual))
            except (TypeError, ValueError) as exc:
                errors.append(f"{name}: {variable} is not a valid IP interface: {exc}")
        router_id = inventory.get(name, {}).get("router_id")
        if str(host_vars.get("loopback_ip", "")).split("/", 1)[0] != router_id:
            errors.append(f"{name}: loopback_ip does not match inventory router_id")
        actual_bgp = _bgp_peer_set(host_vars.get("bgp_peers"), name, errors)
        planned_peers = _bgp_peer_set(planned_vars.get("bgp_peers"), f"data/lab.yml node {name}", errors)
        expected_bgp[name] = planned_peers
        if actual_bgp != planned_peers:
            errors.append(f"{name}: BGP peers do not match data/lab.yml: {actual_bgp}")

    pyats_source = read_text_checked(root / "pyats/test_network.py", errors)
    all_expected_peers = set().union(*expected_bgp.values()) if expected_bgp else set()
    for peer_ip, _ in all_expected_peers:
        if peer_ip not in pyats_source:
            errors.append(f"pyATS checks are missing BGP peer {peer_ip}")

    srlinux_tasks = read_text_checked(root / "ansible/roles/srlinux_ospf/tasks/main.yml", errors)
    srlinux_candidate = read_text_checked(root / "ansible/roles/srlinux_ospf/vars/main.yml", errors)
    frr_template = read_text_checked(root / "ansible/roles/frr_bgp/templates/frr.conf.j2", errors)
    frr_tasks = read_text_checked(root / "ansible/roles/frr_bgp/tasks/main.yml", errors)
    if "atomic: false" not in frr_tasks:
        errors.append("FRR configuration template must disable atomic replacement for its bind mount")
    if "nokia.srlinux.validate" not in srlinux_tasks:
        errors.append("SR Linux role must validate intended configuration before applying it")
    for required_fragment in ("ospf:", "/protocols/bgp"):
        if required_fragment not in srlinux_candidate:
            errors.append(f"SR Linux candidate is missing required protocol fragment: {required_fragment}")
    if "bgp_peers" not in srlinux_tasks:
        errors.append("SR Linux role is missing the dynamic bgp_peers neighbor loop")
    for required_fragment in ("router bgp", "neighbor {{ peer.peer_ip }}", "address-family ipv4 unicast"):
        if required_fragment not in frr_template:
            errors.append(f"FRR template is missing required protocol fragment: {required_fragment}")

    _check_secret_literals(root, errors)
    _check_bind_mounts(root, topology, errors)
    _check_ansible_requirements(root, errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate_repository(args.root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Phase 0 cross-file contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
