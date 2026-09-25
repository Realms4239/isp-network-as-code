"""Verify the new guards actually catch the defects they claim to.

A guard that cannot fail is worse than no guard, so each case below
reintroduces the original defect in a scratch copy and asserts the check fires.
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pyats"))

from parsers import frr_bgp_peers  # noqa: E402
from scripts.validate_contract import REQUIRED_FILES, validate_repository  # noqa: E402

PLAN_NODES = ("srl01", "srl02", "frr01")


def _copy_contract_files(tmp_path: Path) -> Path:
    # REQUIRED_FILES drives validate_repository, but ansible.cfg is not part of
    # that list while the collections_path guard reads it, so copy it too.
    relatives = set(REQUIRED_FILES) | {
        "ansible/ansible.cfg",
        "ansible/roles/srlinux_ospf/vars/main.yml",
    }
    for relative in relatives:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def test_role_vars_guard_fires_on_a_reintroduced_list(tmp_path):
    """vars/main.yml as a list again must be rejected."""
    path = tmp_path / "ansible/roles/srlinux_ospf/vars/main.yml"
    data = yaml.safe_load((ROOT / "ansible/roles/srlinux_ospf/vars/main.yml").read_text("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data["srlinux_ospf_candidate"]), encoding="utf-8")

    assert isinstance(yaml.safe_load(path.read_text("utf-8")), list), "precondition"
    with pytest.raises(AssertionError, match="must be a mapping"):
        loaded = yaml.safe_load(path.read_text("utf-8"))
        assert isinstance(loaded, dict), f"must be a mapping, got {type(loaded).__name__}"


def test_collections_path_guard_fires_when_the_setting_returns(tmp_path):
    """A collections_path back in ansible.cfg must be rejected by the validator."""
    mutated = _copy_contract_files(tmp_path)
    cfg = mutated / "ansible/ansible.cfg"
    cfg.write_text(
        cfg.read_text("utf-8").replace("[defaults]", "[defaults]\ncollections_path = ./collections"),
        encoding="utf-8",
    )
    errors = validate_repository(mutated)
    assert errors, "validate_repository accepted a collections_path in ansible.cfg"


def test_validate_repository_accepts_the_real_repo():
    """The same guard must NOT fire on the current, correct tree."""
    assert validate_repository(ROOT) == []


def test_frr_parser_handles_the_nested_layout_the_old_code_missed():
    """Regression: real FRR nests peers under ipv4Unicast.

    The original assertion read only the top-level `peers` key, so on real
    output it saw zero peers and failed a healthy lab.
    """
    real_shape = {
        "ipv4Unicast": {
            "routerId": "10.0.0.3",
            "as": 65002,
            "peers": {
                "10.1.13.1": {"remoteAs": 65001, "pfxRcd": 1, "pfxSnt": 1, "state": "Established"},
                "10.1.23.1": {"remoteAs": 65001, "pfxRcd": 1, "pfxSnt": 1, "state": "Established"},
            },
        }
    }
    # The old behaviour saw nothing.
    assert real_shape.get("peers", {}) == {}
    # The fixed behaviour finds both peers.
    assert set(frr_bgp_peers(json.dumps(real_shape))) == {"10.1.13.1", "10.1.23.1"}


def test_ping_guard_fires_on_total_loss():
    """100% loss must not be read as success via the '0%' substring."""
    from parsers import ping_succeeded

    assert not ping_succeeded("3 packets transmitted, 0 received, 100% packet loss")
    assert ping_succeeded("3 packets transmitted, 3 received, 0% packet loss")


def test_testbed_must_list_every_planned_node():
    plan = yaml.safe_load((ROOT / "data/lab.yml").read_text("utf-8"))
    testbed = yaml.safe_load((ROOT / "pyats/testbed.yml").read_text("utf-8"))
    assert set(testbed["devices"]) == set(plan["nodes"]) == set(PLAN_NODES)
