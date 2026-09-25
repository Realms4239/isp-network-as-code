from pathlib import Path

import json
import yaml

from scripts.check_ansible_result import main as check_ansible_result
from scripts.lab_evidence import build_manifest, record_event, redact_text, redact_tree
from scripts.validate_contract import REQUIRED_FILES, load_inventory, load_yaml, validate_repository
from scripts.wait_for_lab import planned_srlinux_addresses


def test_readiness_addresses_are_plan_driven():
    assert planned_srlinux_addresses(ROOT / "data" / "lab.yml") == ["172.20.20.11", "172.20.20.12"]


def test_redact_text_removes_secret_values_and_assignments():
    text = "password=super-secret token: abc123 value=super-secret"

    redacted = redact_text(text, ("super-secret",))

    assert "super-secret" not in redacted
    assert "abc123" not in redacted
    assert "<redacted>" in redacted


def test_redact_tree_skips_private_key_files(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "redacted"
    source.mkdir()
    (source / "authorized_keys").write_text("ssh-ed25519 AAAA", encoding="utf-8")
    (source / "config.txt").write_text("password=secret", encoding="utf-8")

    redact_tree(source, output, ("secret",))

    assert (output / "authorized_keys").read_text(encoding="utf-8") == "<redacted-sensitive-file>\n"
    assert "secret" not in (output / "config.txt").read_text(encoding="utf-8")


def test_manifest_is_deterministic_and_hashes_files(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    build_manifest(root, first, "run-1")
    build_manifest(root, second, "run-1")
    first_data = json.loads(first.read_text(encoding="utf-8"))
    second_data = json.loads(second.read_text(encoding="utf-8"))
    first_data["generated_at"] = second_data["generated_at"] = "fixed"

    assert first_data == second_data
    assert first_data["files"][0]["path"] == "result.json"
    assert len(first_data["files"][0]["sha256"]) == 64


def test_manifest_excludes_itself(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    output = root / "manifest.json"

    build_manifest(root, output, "run-1")
    build_manifest(root, output, "run-1")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert [item["path"] for item in payload["files"]] == ["result.json"]


def test_inventory_group_vars_are_not_hosts(tmp_path):
    inventory_path = tmp_path / "hosts.ini"
    inventory_path.write_text(
        "[srlinux]\nsrl01 ansible_host=172.20.20.11\n\n[srlinux:vars]\nansible_user=admin\n",
        encoding="utf-8",
    )
    inventory, groups = load_inventory(inventory_path)
    assert set(inventory) == {"srl01"}
    assert groups["srlinux"] == {"srl01"}


def test_record_event_is_append_only_jsonl(tmp_path):
    path = Path(tmp_path) / "events.jsonl"

    record_event(path, "run-1", "ansible", "started")
    record_event(path, "run-1", "ansible", "passed", duration_ms=12)
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert [event["status"] for event in events] == ["started", "passed"]
    assert events[1]["duration_ms"] == 12


ROOT = Path(__file__).resolve().parents[1]


def copy_contract_fixture(tmp_path: Path) -> Path:
    for relative in REQUIRED_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for relative in (
        "ansible/group_vars/srlinux.yml",
        "ansible/group_vars/frr.yml",
        "ansible/roles/srlinux_ospf/tasks/main.yml",
        "ansible/roles/srlinux_ospf/vars/main.yml",
        "ansible/roles/frr_bgp/tasks/main.yml",
        "ansible/roles/frr_bgp/templates/daemons",
        "ansible/roles/frr_bgp/templates/vtysh.conf",
        "ansible/roles/frr_bgp/templates/frr.conf.j2",
        "ansible/host_vars/srl01.yml",
        "ansible/host_vars/srl02.yml",
        "ansible/host_vars/frr01.yml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def test_valid_repository_contract():
    assert validate_repository(ROOT) == []


def test_role_vars_are_mappings_not_lists():
    """Ansible requires vars/main.yml to be a dictionary.

    A top-level list fails `ansible-playbook --syntax-check` with "the
    vars/main.yml file for role '<role>' must contain a dictionary of variables",
    which surfaces only as an opaque ansible-lint `internal-error`. These checks
    run offline so the shape is verified before CI ever sees it.
    """
    for role_vars in sorted(ROOT.glob("ansible/roles/*/vars/*.yml")):
        loaded = yaml.safe_load(role_vars.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict), (
            f"{role_vars.relative_to(ROOT)} must be a mapping, got "
            f"{type(loaded).__name__}"
        )


def test_role_vars_define_the_vars_their_tasks_consume():
    """The candidate list is consumed by tasks/main.yml, so it must exist there."""
    tasks = (ROOT / "ansible/roles/srlinux_ospf/tasks/main.yml").read_text(encoding="utf-8")
    role_vars = yaml.safe_load(
        (ROOT / "ansible/roles/srlinux_ospf/vars/main.yml").read_text(encoding="utf-8")
    )
    # Role variables must carry the role prefix (ansible-lint var-naming rule).
    key = "srlinux_ospf_candidate"
    assert key in role_vars, f"vars/main.yml must define {key}"
    assert isinstance(role_vars[key], list)
    assert role_vars[key], f"{key} must not be empty"
    for entry in role_vars[key]:
        assert "path" in entry and "value" in entry, (
            "each candidate entry needs both 'path' and 'value' for nokia.srlinux.config"
        )
    assert key in tasks, f"tasks/main.yml must consume {key}"


def test_role_prefixed_variables_only():
    """Every role var and registered var carries its role name as a prefix.

    ansible-lint's var-naming[no-role-prefix] rule is fatal under the production
    profile this repo pins, and an unprefixed role variable can silently collide
    with a same-named variable defined elsewhere in the play.
    """
    for tasks_file in sorted(ROOT.glob("ansible/roles/*/{tasks,handlers}/*.yml")):
        role = tasks_file.parents[1].name
        for line in tasks_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "register:" not in stripped:
                continue
            name = stripped.split("register:", 1)[1].strip()
            if not name or name.startswith(("{{", "!")):
                continue
            assert name.startswith(f"{role}_"), (
                f"{tasks_file.relative_to(ROOT)} registers '{name}'; role variables "
                f"must be prefixed with '{role}_'"
            )


def test_testbed_matches_the_plan_and_the_pyats_expectations():
    """The testbed is only useful if it points at the devices the plan declares.

    Nothing else in the offline suite can catch a testbed that still names the
    old management addresses, because a wrong testbed only fails once the live
    lab tries to connect.
    """
    plan = load_yaml(ROOT / "data" / "lab.yml")
    testbed = load_yaml(ROOT / "pyats" / "testbed.yml")
    devices = testbed["devices"]
    assert set(devices) == set(plan["nodes"]), (
        f"testbed devices {sorted(devices)} do not match plan nodes "
        f"{sorted(plan['nodes'])}"
    )
    for name, node in plan["nodes"].items():
        connections = devices[name]["connections"]
        ips = {
            conn["ip"]
            for block in connections.values()
            if isinstance(block, dict)
            for conn in ([block] if "ip" in block else block.values())
            if isinstance(conn, dict) and "ip" in conn
        }
        assert node["mgmt_ipv4"] in ips, (
            f"testbed {name} does not point at the planned management address "
            f"{node['mgmt_ipv4']}"
        )


def test_testbed_credentials_come_from_the_environment():
    """No literal credential may appear in the testbed."""
    raw = (ROOT / "pyats" / "testbed.yml").read_text(encoding="utf-8")
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        if key.strip() not in ("username", "password", "private_key"):
            continue
        assert "%ENV{" in value, (
            f"testbed credential {key.strip()!r} must come from %ENV{{...}}, "
            f"got {value.strip()!r}"
        )


def test_pyats_suite_has_no_bare_regex_assertions():
    """Parsing must live in pyats/parsers.py so it stays offline-testable.

    An inline re.search against device output cannot be verified without a live
    lab, which is how two real defects survived in this file.
    """
    source = (ROOT / "pyats" / "test_network.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "import re" not in body, (
        "test_network.py must not parse output itself; import the helpers from "
        "parsers.py so the logic is covered by tests/test_pyats_parsers.py"
    )
    assert "re.search" not in body, (
        "inline re.search against device output is not offline-testable; add a "
        "helper in pyats/parsers.py and cover it there"
    )


def test_ansible_cfg_does_not_pin_collections_path():
    """collections_path in ansible.cfg overrides ANSIBLE_COLLECTIONS_PATH.

    Pinning it there is what made `ansible-playbook --syntax-check` unable to
    resolve nokia.srlinux, so the env var is the single source of truth. Only
    real settings are checked: the file also explains in a comment why the
    setting is absent, and that must not trip the test.
    """
    for raw_line in (ROOT / "ansible/ansible.cfg").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "[")):
            continue
        key = line.split("=", 1)[0].strip().lower()
        assert key != "collections_path", (
            "ansible.cfg must not set collections_path; it overrides "
            "ANSIBLE_COLLECTIONS_PATH and breaks collection resolution"
        )


def test_unknown_topology_node_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    topology_path = fixture / "topology/topology.clab.yml"
    topology = load_yaml(topology_path)
    topology["topology"]["links"][0]["endpoints"][1] = "missing:e1-1"
    topology_path.write_text(yaml.safe_dump(topology, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("unknown node" in error for error in errors)


def test_management_address_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    inventory_path = fixture / "ansible/inventories/hosts.ini"
    inventory_path.write_text(
        inventory_path.read_text(encoding="utf-8").replace(
            "srl01 ansible_host=172.20.20.11", "srl01 ansible_host=172.20.20.99"
        ),
        encoding="utf-8",
    )

    errors = validate_repository(fixture)

    assert any("does not match inventory" in error for error in errors)


def test_address_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    host_vars_path = fixture / "ansible/host_vars/srl01.yml"
    host_vars = load_yaml(host_vars_path)
    host_vars["transit_ip"] = "10.1.99.1/24"
    host_vars_path.write_text(yaml.safe_dump(host_vars, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("transit_ip is '10.1.99.1/24'" in error for error in errors)


def test_bgp_peer_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    host_vars_path = fixture / "ansible/host_vars/srl01.yml"
    host_vars = load_yaml(host_vars_path)
    host_vars["bgp_peers"][0]["peer_ip"] = "10.1.99.2"
    host_vars_path.write_text(yaml.safe_dump(host_vars, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("BGP peers do not match" in error for error in errors)


def test_plan_version_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    plan_path = fixture / "data/lab.yml"
    plan = load_yaml(plan_path)
    plan["version"] = 2
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("version must be 1" in error for error in errors)


def test_pyats_plan_coverage_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    plan_path = fixture / "data/lab.yml"
    plan = load_yaml(plan_path)
    del plan["pyats"]["routes"]["frr01"]
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("pyats.routes must cover" in error for error in errors)


def test_invalid_pyats_route_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    plan_path = fixture / "data/lab.yml"
    plan = load_yaml(plan_path)
    plan["pyats"]["routes"]["srl01"][0] = "not-a-prefix"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("contains an invalid prefix" in error for error in errors)


def test_invalid_link_protocol_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    plan_path = fixture / "data/lab.yml"
    plan = load_yaml(plan_path)
    plan["links"][0]["protocols"] = ["isis"]
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("protocols must be a non-empty list" in error for error in errors)


def test_testbed_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    testbed_path = fixture / "pyats/testbed.yml"
    testbed = load_yaml(testbed_path)
    testbed["devices"]["frr01"]["connections"]["cli"]["ip"] = "172.20.20.99"
    testbed_path.write_text(yaml.safe_dump(testbed, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("SSH connection does not match data/lab.yml" in error for error in errors)


def test_missing_prerequisite_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    (fixture / "ansible/host_vars/srl01.yml").unlink()

    errors = validate_repository(fixture)

    assert any("required file is missing: ansible/host_vars/srl01.yml" in error for error in errors)


def test_missing_required_file_is_reported_without_traceback(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    (fixture / "data/lab.yml").unlink()

    errors = validate_repository(fixture)

    assert errors == ["required file is missing: data/lab.yml"]


def test_malformed_yaml_is_reported_without_traceback(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    (fixture / "data/lab.yml").write_text("node_types: [", encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("cannot parse YAML" in error for error in errors)


def test_null_topology_is_reported_without_traceback(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    (fixture / "topology/topology.clab.yml").write_text("topology:\n", encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("topology.topology must be a mapping" in error for error in errors)


def test_plan_drift_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    plan_path = fixture / "data/lab.yml"
    plan = load_yaml(plan_path)
    plan["nodes"]["srl01"]["host_vars"]["core_ip"] = "10.9.12.1/24"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("core_ip is '10.1.12.1/24'" in error for error in errors)


def test_interface_reuse_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    topology_path = fixture / "topology/topology.clab.yml"
    topology = load_yaml(topology_path)
    topology["topology"]["links"][1]["endpoints"][0] = "srl01:e1-1"
    topology_path.write_text(yaml.safe_dump(topology, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("used more than once" in error for error in errors)


def test_changed_ansible_result_is_rejected(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    result.write_text(
        json.dumps(
            {"playbooks": [{"plays": [{"hosts": {"srl01": {"changed": 1, "failed": 0, "unreachable": 0}}}]}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_ansible_result.py", str(result), "--require-idempotent"],
    )

    assert check_ansible_result() == 1


def test_failed_ansible_result_is_rejected(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    hosts = {
        host: {
            "changed": 0,
            "failed": int(host == "frr01"),
            "unreachable": 0,
        }
        for host in ("srl01", "srl02", "frr01")
    }
    result.write_text(
        json.dumps({"playbooks": [{"plays": [{"hosts": hosts}]}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_ansible_result.py", str(result)])

    assert check_ansible_result() == 1


def test_unreachable_ansible_result_is_rejected(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    hosts = {
        host: {
            "changed": 0,
            "failed": 0,
            "unreachable": int(host == "srl02"),
        }
        for host in ("srl01", "srl02", "frr01")
    }
    result.write_text(
        json.dumps({"playbooks": [{"plays": [{"hosts": hosts}]}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_ansible_result.py", str(result)])

    assert check_ansible_result() == 1


def test_ansible_result_host_set_drift_is_rejected(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    result.write_text(
        json.dumps({"playbooks": [{"plays": [{"hosts": {"srl01": {"changed": 0, "failed": 0, "unreachable": 0}}}]}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_ansible_result.py", str(result)])

    assert check_ansible_result() == 1


def test_self_link_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    topology_path = fixture / "topology/topology.clab.yml"
    topology = load_yaml(topology_path)
    topology["topology"]["links"][0]["endpoints"][1] = "srl01:e1-2"
    topology_path.write_text(yaml.safe_dump(topology, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("cannot connect two interfaces" in error for error in errors)


def test_missing_ansible_result_returns_input_error(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["check_ansible_result.py", str(tmp_path / "missing.json")])

    assert check_ansible_result() == 2


def test_invalid_ansible_json_returns_input_error(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    result.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_ansible_result.py", str(result)])

    assert check_ansible_result() == 2


def test_duplicate_play_statistics_are_aggregated(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    result.write_text(
        json.dumps(
            {
                "playbooks": [
                    {"plays": [{"hosts": {"srl01": {"changed": 1, "failed": 0, "unreachable": 0}}}]},
                    {"plays": [{"hosts": {"srl01": {"changed": 0, "failed": 0, "unreachable": 0}}}]},
                    {"plays": [{"hosts": {"srl02": {"changed": 0, "failed": 0, "unreachable": 0}}}]},
                    {"plays": [{"hosts": {"frr01": {"changed": 0, "failed": 0, "unreachable": 0}}}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_ansible_result.py", str(result), "--require-idempotent"],
    )

    assert check_ansible_result() == 1


def test_all_skipped_ansible_result_is_rejected(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    result.write_text(
        json.dumps(
            {
                "playbooks": [
                    {
                        "plays": [
                            {
                                "hosts": {
                                    host: {
                                        "ok": 0,
                                        "changed": 0,
                                        "failed": 0,
                                        "unreachable": 0,
                                        "skipped": 3,
                                    }
                                    for host in ("srl01", "srl02", "frr01")
                                }
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["check_ansible_result.py", str(result), "--require-idempotent"])

    assert check_ansible_result() == 1


def test_ansible_report_contains_hashes_and_status(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    hosts = {
        host: {"ok": 1, "changed": 0, "failed": 0, "unreachable": 0}
        for host in ("srl01", "srl02", "frr01")
    }
    result.write_text(
        json.dumps({"playbooks": [{"plays": [{"hosts": hosts}]}]}),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_ansible_result.py",
            str(result),
            "--require-idempotent",
            "--report",
            str(report),
            "--run-id",
            "test-run",
        ],
    )

    assert check_ansible_result() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema"] == "isp-lab.ansible-result/v1"
    assert payload["status"] == "passed"
    assert payload["run_id"] == "test-run"
    assert len(payload["result_sha256"]) == 64


def test_bom_encoded_ansible_result_is_accepted(tmp_path, monkeypatch):
    result = tmp_path / "ansible.json"
    result.write_text(
        json.dumps(
            {
                "playbooks": [
                    {
                        "plays": [
                            {
                                "hosts": {
                                    host: {"changed": 0, "failed": 0, "unreachable": 0}
                                    for host in ("srl01", "srl02", "frr01")
                                }
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["check_ansible_result.py", str(result), "--require-idempotent"],
    )

    assert check_ansible_result() == 0


def test_new_plan_node_requires_projection_files(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    plan_path = fixture / "data/lab.yml"
    plan = load_yaml(plan_path)
    plan["nodes"]["srl03"] = {
        "type": "srl",
        "group": "srl",
        "mgmt_ipv4": "172.20.20.14",
        "host_vars": {"loopback_ip": "10.0.0.4/32"},
    }
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("required file is missing: ansible/host_vars/srl03.yml" in error for error in errors)


def test_literal_secret_assignment_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    group_vars_path = fixture / "ansible/group_vars/srlinux.yml"
    group_vars_path.write_text(
        group_vars_path.read_text(encoding="utf-8") + "\napi_token: literal-token\n",
        encoding="utf-8",
    )

    errors = validate_repository(fixture)

    assert any("literal secret assignment" in error for error in errors)


def test_out_of_tree_bind_mount_is_rejected(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    topology_path = fixture / "topology/topology.clab.yml"
    topology = load_yaml(topology_path)
    topology["topology"]["nodes"]["frr01"]["binds"].append("/etc/passwd:/host-etc-passwd:ro")
    topology_path.write_text(yaml.safe_dump(topology, sort_keys=False), encoding="utf-8")

    errors = validate_repository(fixture)

    assert any("bind source must stay inside .lab" in error for error in errors)


def test_protocol_configuration_cannot_be_removed(tmp_path):
    fixture = copy_contract_fixture(tmp_path)
    role_path = fixture / "ansible/roles/srlinux_ospf/tasks/main.yml"
    role_path.write_text(
        role_path.read_text(encoding="utf-8").replace("nokia.srlinux.validate", "nokia.srlinux.cli"),
        encoding="utf-8",
    )

    errors = validate_repository(fixture)

    assert any("validate intended configuration" in error for error in errors)
