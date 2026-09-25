"""Deterministic JSON evidence callback for the Phase 0 lab.

The callback intentionally records counters and timing only. It never records
secrets, task arguments, or device command output.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = """
    name: lab_json
    type: aggregate
    short_description: Emit deterministic Ansible host statistics as JSON
    version_added: "0.1.0"
    description:
        - Emits machine-readable play and host counters for lab evidence.
    requirements:
        - ansible-core
"""


class CallbackModule(CallbackBase):
    """Collect per-host Ansible counters without leaking configuration values."""

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "lab_json"
    CALLBACK_NEEDS_ENABLED = False

    def __init__(self) -> None:
        super().__init__()
        self._playbooks: list[dict[str, Any]] = []
        self._play: dict[str, Any] | None = None
        self._started = 0.0
        self._task_starts = 0
        self._play_index = 0

    def _new_stats(self) -> dict[str, int]:
        return {
            "ok": 0,
            "changed": 0,
            "failed": 0,
            "unreachable": 0,
            "skipped": 0,
            "rescued": 0,
            "ignored": 0,
            "dark": 0,
        }

    def _host_stats(self, host_name: str) -> dict[str, int]:
        assert self._play is not None
        return self._play["hosts"].setdefault(host_name, self._new_stats())

    @staticmethod
    def _host_name(result: Any) -> str | None:
        host = getattr(result, "_host", None)
        getter = getattr(host, "get_name", None)
        return getter() if callable(getter) else None

    def _record(self, result: Any, field: str) -> None:
        if self._play is None:
            return
        host_name = self._host_name(result)
        if not host_name:
            return
        stats = self._host_stats(host_name)
        stats[field] = stats.get(field, 0) + 1
        payload = getattr(result, "_result", None)
        if field == "ok" and isinstance(payload, dict) and payload.get("changed"):
            stats["changed"] = stats.get("changed", 0) + 1

    def v2_playbook_on_start(self, playbook: Any) -> None:
        self._playbooks = []
        self._play_index = 0

    def v2_playbook_on_play_start(self, play: Any) -> None:
        self._play = {
            "play": play.get_name() if hasattr(play, "get_name") else str(play),
            "hosts": {name: self._new_stats() for name in play.hosts},
            "task_count": 0,
        }
        self._started = time.monotonic()

    def v2_playbook_on_task_start(self, task: Any, is_conditional: bool = False) -> None:
        if self._play is not None:
            self._play["task_count"] += 1

    def v2_runner_on_ok(self, result: Any) -> None:
        self._record(result, "ok")

    def v2_runner_on_failed(self, result: Any, ignore_errors: bool = False) -> None:
        self._record(result, "failed" if not ignore_errors else "ignored")

    def v2_runner_on_unreachable(self, result: Any) -> None:
        self._record(result, "unreachable")

    def v2_runner_on_skipped(self, result: Any) -> None:
        self._record(result, "skipped")

    def v2_runner_on_rescued(self, result: Any) -> None:
        self._record(result, "rescued")

    def v2_playbook_on_stats(self, stats: Any) -> None:
        if self._play is not None:
            self._play["duration_seconds"] = round(time.monotonic() - self._started, 3)
            self._playbooks.append(self._play)
            self._play = None

    def v2_playbook_on_end(self, playbook: Any) -> None:
        if self._play is not None:
            self.v2_playbook_on_stats(getattr(playbook, "stats", None))
        self._play_index += 1

    def _dump(self) -> str:
        return json.dumps(
            {"playbooks": self._playbooks},
            indent=2,
            sort_keys=True,
        )

    def v2_playbook_on_print_stats(self, stats: Any) -> None:
        self._display.display(self._dump())
        self._display.display("", color="blue")
