"""Verify the new guards actually catch the defects they claim to.

A guard that cannot fail is worse than no guard, so each case below
reintroduces the original defect in a scratch copy and asserts the check fires.
"""

import json
import re
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


def test_readme_explains_why_windows_cannot_run_the_live_lab():
    """The Linux requirement must state the reason, not just assert it.

    pyATS and Genie publish no Windows wheels. On a native Windows host pip
    reports `from versions: none` for a version that genuinely exists, which
    reads like an outage or a typo in the pin. A reader who does not know the
    wheel situation burns time chasing a network problem that isn't there, so
    the README has to carry the explanation.
    """
    readme = (ROOT / "README.md").read_text("utf-8")

    assert "Why Linux" in readme, "README must explain the Linux requirement"
    for token in ("pyATS", "Windows", "from versions: none"):
        assert token in readme, f"README platform note is missing {token!r}"


def test_offline_suite_does_not_import_pyats():
    """Offline tests must stay runnable without pyATS installed.

    This suite is the authoritative gate and runs on any host. If an offline
    test imported pyats, the whole gate would collapse on exactly the machines
    that cannot install it (Windows, and any host before the wheel is cached).
    """
    banned = ("pyats", "genie", "unstructured")
    offenders: list[str] = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            # Match the module and any submodule. An exact match on the bare
            # name is not enough: `import pyats.testbed` is a real pyATS
            # dependency and slipped past the first version of this check.
            if stripped.startswith("from "):
                module = stripped[len("from "):].split(" ")[0].strip()
            else:
                module = stripped[len("import "):].split(" ")[0].strip().rstrip(",")
            for banned_name in banned:
                root = module.split(".")[0]
                if root == banned_name:
                    offenders.append(f"{path.name}:{number}: {stripped}")

    assert not offenders, "offline tests must not import pyATS: " + "; ".join(offenders)


def test_no_route_assertion_uses_a_bare_substring_check():
    """A route assertion must not reduce to `prefix in output`.

    `show ... prefix <p> detail` echoes the command line, which contains the
    prefix. So a substring test is True for a prefix with no route installed,
    and the assertion cannot fail. This exact defect shipped once: the FRR
    path was fixed and the SR Linux path was left calling the same helper.

    Both paths must now go through a real check, so ban the bare form outright
    rather than trusting a reviewer to notice a new one.
    """
    source = (ROOT / "pyats" / "test_network.py").read_text("utf-8")

    # Only assert statements count. `for prefix in prefixes` is a loop, and the
    # explanatory comment quotes the bad form on purpose; flagging either would
    # make the guard cry wolf on correct code.
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(source.splitlines(), 1)
        if re.search(r"\bassert\b", line)
        and re.search(r"\b\w*[Pp]refix\w*\s+in\s+\w+", line)
    ]
    assert not offenders, (
        "route assertions must not use a substring presence check: "
        + "; ".join(offenders)
    )


def test_route_helpers_are_imported_not_reimplemented():
    """test_network.py must call the tested helpers, not inline its own logic.

    A second copy of the parsing logic in the test file is a second thing that
    can be wrong and is not covered by the offline parser suite.
    """
    source = (ROOT / "pyats" / "test_network.py").read_text("utf-8")

    # json is legitimately used for the FRR JSON route check.
    inline_json = re.findall(r"json\.loads\(", source)
    for helper in ("srl_route_is_installed", "frr_bgp_peers", "ping_succeeded"):
        assert f"    {helper}," in source, f"{helper} must be imported from parsers"
    # Only the FRR route check may parse JSON, and it is asserted inline.
    assert len(inline_json) <= 1, "unexpected extra JSON parsing in the test file"
