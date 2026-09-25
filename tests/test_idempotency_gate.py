"""End-to-end tests for the idempotency gate (scripts/check_ansible_result.py).

This gate is the flagship's central claim -- "second run reports changed=0" --
and it had no test exercising it with a payload shaped like the real
`lab_json` callback output. These build that payload (two plays, three hosts,
nested under playbooks[].hosts) and assert the gate accepts a converged run and
rejects every way a run can be non-idempotent.

`lab_json` emits {"playbooks": [{"play": ..., "hosts": {...}, ...}]}; the gate's
`iter_host_stats` walks that structure, so a flat or single-play fixture would
not have exercised the real traversal.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "check_ansible_result.py"


def _stats(ok=0, changed=0, failed=0, unreachable=0, skipped=0):
    return {
        "ok": ok,
        "changed": changed,
        "failed": failed,
        "unreachable": unreachable,
        "skipped": skipped,
        "rescued": 0,
        "ignored": 0,
        "dark": 0,
    }


def _callback_payload(srl01, srl02, frr01):
    """Shape the real lab_json callback emits: two plays, hosts nested per play."""
    return {
        "playbooks": [
            {
                "play": "Configure Nokia SR Linux Backbone Nodes (OSPF & BGP)",
                "task_count": 4,
                "duration_seconds": 3.5,
                "hosts": {"srl01": srl01, "srl02": srl02},
            },
            {
                "play": "Configure FRR Transit Core Node (BGP)",
                "task_count": 2,
                "duration_seconds": 1.5,
                "hosts": {"frr01": frr01},
            },
        ]
    }


CONVERGED = _callback_payload(
    _stats(ok=3, skipped=1), _stats(ok=3, skipped=1), _stats(ok=2)
)
CHANGED_ON_SECOND_RUN = _callback_payload(
    _stats(ok=3, changed=1), _stats(ok=3, skipped=1), _stats(ok=2)
)
WITH_FAILURE = _callback_payload(
    _stats(ok=2, failed=1), _stats(ok=3, skipped=1), _stats(ok=2)
)
WITH_UNREACHABLE = _callback_payload(
    _stats(ok=2, unreachable=1), _stats(ok=3, skipped=1), _stats(ok=2)
)
MISSING_HOST = _callback_payload(
    _stats(ok=3, skipped=1), _stats(ok=3, skipped=1), _stats(ok=2)
)
MISSING_HOST["playbooks"][1]["hosts"] = {}


def run_gate(tmp_path: Path, payload, *extra) -> subprocess.CompletedProcess:
    result = tmp_path / "ansible-run.json"
    result.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(GATE),
            str(result),
            "--plan",
            str(ROOT / "data" / "lab.yml"),
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def test_converged_run_passes_the_idempotency_gate(tmp_path):
    proc = run_gate(
        tmp_path,
        CONVERGED,
        "--require-idempotent",
        "--report",
        str(tmp_path / "report.json"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "changed=0" in proc.stdout


def test_any_change_on_the_second_run_fails(tmp_path):
    proc = run_gate(tmp_path, CHANGED_ON_SECOND_RUN, "--require-idempotent")
    assert proc.returncode == 1, proc.stdout
    assert "changed=1" in proc.stdout


def test_a_failed_host_fails(tmp_path):
    proc = run_gate(tmp_path, WITH_FAILURE, "--require-idempotent")
    assert proc.returncode == 1, proc.stdout
    assert "failed=1" in proc.stdout


def test_an_unreachable_host_fails(tmp_path):
    proc = run_gate(tmp_path, WITH_UNREACHABLE, "--require-idempotent")
    assert proc.returncode == 1, proc.stdout
    assert "unreachable=1" in proc.stdout


def test_a_missing_host_fails_even_when_counters_are_clean(tmp_path):
    """A host that never reported cannot be treated as converged."""
    proc = run_gate(tmp_path, MISSING_HOST, "--require-idempotent")
    assert proc.returncode == 1, proc.stdout
    assert "host set mismatch" in proc.stdout


def test_counters_aggregate_across_plays_per_host(tmp_path):
    """Stats must sum per host across plays, not be read from one play.

    A host appearing in two plays must have its counters added together. Run
    without --require-idempotent so a nonzero `changed` is not itself a failure:
    the point here is the aggregation, which the report exposes directly.
    """
    payload = _callback_payload(_stats(ok=2), _stats(ok=2), _stats(ok=1))
    payload["playbooks"].append(
        {
            "play": "extra play touching srl01 again",
            "hosts": {"srl01": _stats(ok=1, changed=1)},
        }
    )
    report = tmp_path / "report.json"
    proc = run_gate(tmp_path, payload, "--report", str(report))
    assert proc.returncode == 0, proc.stdout
    written = json.loads(report.read_text(encoding="utf-8"))
    # srl01 ran in two plays: 2 + 1 = 3 ok, and the single change must be visible.
    assert written["hosts"]["srl01"]["ok"] == 3
    assert written["hosts"]["srl01"]["changed"] == 1
    assert written["status"] == "passed"
    # The other hosts were touched once each and must be untouched by the extra play.
    assert written["hosts"]["srl02"]["ok"] == 2
    assert written["hosts"]["frr01"]["ok"] == 1


def test_aggregate_change_breaks_the_idempotency_gate(tmp_path):
    """The same aggregate change does fail when idempotency is required."""
    payload = _callback_payload(_stats(ok=2), _stats(ok=2), _stats(ok=1))
    payload["playbooks"].append(
        {"play": "extra", "hosts": {"srl01": _stats(ok=1, changed=1)}}
    )
    proc = run_gate(tmp_path, payload, "--require-idempotent")
    assert proc.returncode == 1, proc.stdout
    assert "changed=1" in proc.stdout


def test_empty_result_is_rejected(tmp_path):
    proc = run_gate(tmp_path, {"playbooks": []})
    assert proc.returncode == 1
    assert "no host statistics" in proc.stdout


def test_malformed_json_is_rejected(tmp_path):
    result = tmp_path / "ansible-run.json"
    result.write_text("not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(GATE), str(result), "--plan", str(ROOT / "data" / "lab.yml")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "cannot read Ansible JSON result" in proc.stdout


def test_report_records_a_content_hash_of_the_result(tmp_path):
    report = tmp_path / "report.json"
    proc = run_gate(tmp_path, CONVERGED, "--report", str(report), "--run-id", "run-1")
    assert proc.returncode == 0, proc.stdout
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["schema"] == "isp-lab.ansible-result/v1"
    assert written["run_id"] == "run-1"
    assert len(written["result_sha256"]) == 64
    assert written["status"] == "passed"
