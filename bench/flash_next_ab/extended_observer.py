"""UNAPPLIED DRAFT: independently observe Pulse health during a research window.

Only these two local UI endpoints are queried. The observer never calls a
model endpoint, follows redirects, reads response bodies, or touches a weekly
budget. An operational failure stops the exact candidate through the owning
MemoryMonitor, and the controller must still restore the captured residents.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evaluation_window import EXTENDED_SERVING_PROFILE
from .harness import _read_regular_file

URLS = (
    "http://127.0.0.1:8700/api/health",
    "http://127.0.0.1:5173/",
)
MAX_OBSERVER_BYTES = 8 * 1024 * 1024
MAX_OBSERVER_ROWS = 20_000


class ObserverError(RuntimeError):
    """Health monitoring or its durable proof failed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, status, message, headers, url):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UIObserver:
    """An independent five-second thread with a bounded, private JSONL proof."""

    def __init__(self, output: Path, *, monitor: Any, pair_id: str,
                 extended_plan_sha256: str, profile: dict,
                 clock=time.monotonic, request=None) -> None:
        if profile != EXTENDED_SERVING_PROFILE or not pair_id or not extended_plan_sha256:
            raise ObserverError("observer profile or immutable window identity differs")
        if not callable(getattr(monitor, "report_external_breach", None)):
            raise ObserverError("candidate monitor has no operational stop signal")
        if not isinstance(output, Path) or output.is_symlink() or not output.is_dir():
            raise ObserverError("observer output must be a fixed regular directory")
        self.output = output
        self.path = output / "ui-observer.jsonl"
        self.monitor = monitor
        self.pair_id = pair_id
        self.plan_sha256 = extended_plan_sha256
        self.profile = profile
        self.clock = clock
        self.request = request or self._request
        self.done = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_tick_mono: float | None = None
        self.failure_ticks: deque[float] = deque()
        self.failed = False
        self.error_type: str | None = None
        self.ticks = 0
        self.failed_ticks = 0
        self.probes = 0
        self.first_tick_at: str | None = None
        self.last_tick_at: str | None = None
        self._stream = None
        self._origin_mono: float | None = None

    @staticmethod
    def _request(url: str, timeout: float) -> int:
        if url not in URLS or timeout != 2:
            raise ObserverError("UI observer URL/timeout changed")
        with _OPENER.open(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
            return response.status

    def _record(self, row: dict) -> None:
        if self._stream is None:
            raise ObserverError("observer log is absent")
        self._stream.write(
            (json.dumps({"observed_at": _utc_now(), **row}, sort_keys=True,
                        separators=(",", ":"), allow_nan=False) + "\n").encode()
        )
        self._stream.flush()

    def start(self) -> None:
        if self.thread is not None or self.path.exists() or self.path.is_symlink():
            raise ObserverError("UI observer was already started or output exists")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        self._stream = os.fdopen(descriptor, "wb", buffering=0)
        self._record({
            "schema": "flash-next-ui-observer/v1", "event": "plan",
            "pair_id": self.pair_id, "extended_plan_sha256": self.plan_sha256,
            "profile": self.profile, "urls": list(URLS),
            "model_requests": 0, "weekly_budget_debit": False,
        })
        self.thread = threading.Thread(target=self._loop, name="flash-ui-observer", daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        try:
            while not self.done.is_set():
                start_mono = self.clock()
                if not isinstance(start_mono, (int, float)) or isinstance(start_mono, bool) or not math.isfinite(start_mono):
                    raise ObserverError("UI observer clock is invalid")
                if self.last_tick_mono is not None and not 0 <= start_mono - self.last_tick_mono <= 15:
                    raise ObserverError("UI observer has a blind interval")
                self._origin_mono = start_mono if self._origin_mono is None else self._origin_mono
                self.last_tick_mono = start_mono
                self.ticks += 1
                self.first_tick_at = self.first_tick_at or _utc_now()
                self.last_tick_at = _utc_now()
                failed_tick = False
                for url in URLS:
                    request_started = self.clock()
                    row = {"schema": "flash-next-ui-observer/v1", "event": "probe", "url": url}
                    try:
                        code = self.request(url, 2)
                        row["http_status"] = code
                        failed_tick |= code != 200
                    except Exception as exc:  # noqa: BLE001 - UI fault must stop candidate safely
                        row["error_type"] = type(exc).__name__
                        failed_tick = True
                    elapsed = self.clock() - request_started
                    if not math.isfinite(elapsed) or elapsed < 0:
                        raise ObserverError("UI observer latency is invalid")
                    row["elapsed_seconds"] = elapsed
                    if elapsed > 2:
                        failed_tick = True
                    self.probes += 1
                    self._record(row)
                self._record({"schema": "flash-next-ui-observer/v1", "event": "tick",
                              "failed": failed_tick, "tick": self.ticks,
                              "elapsed_monotonic_seconds": start_mono - self._origin_mono})
                if failed_tick:
                    self.failure_ticks.append(start_mono)
                    self.failed_ticks += 1
                while self.failure_ticks and self.failure_ticks[0] < start_mono - 30:
                    self.failure_ticks.popleft()
                if len(self.failure_ticks) >= 2:
                    self.failed = True
                    self.monitor.report_external_breach("two UI health failures within 30 seconds")
                    break
                self.done.wait(max(0, 5 - (self.clock() - start_mono)))
        except BaseException as exc:  # noqa: BLE001 - observer failure is operational abort
            self.failed = True
            self.error_type = type(exc).__name__
            self.monitor.report_external_breach(f"UI observer failed: {type(exc).__name__}")

    def stop(self) -> dict:
        if self.thread is None or self._stream is None:
            raise ObserverError("UI observer never started")
        self.done.set()
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            self.failed = True
            self.error_type = "ObserverShutdownTimeout"
            self.monitor.report_external_breach("UI observer thread did not terminate")
            raise ObserverError("UI observer thread did not terminate")
        self._record({"schema": "flash-next-ui-observer/v1", "event": "finished",
                      "pair_id": self.pair_id, "extended_plan_sha256": self.plan_sha256,
                      "ticks": self.ticks, "probes": self.probes,
                      "failed_ticks": self.failed_ticks,
                      "failed": self.failed, "error_type": self.error_type,
                      "first_tick_at": self.first_tick_at,
                      "last_tick_at": self.last_tick_at})
        os.fsync(self._stream.fileno())
        self._stream.close()
        self._stream = None
        raw, path = _read_regular_file(self.path, label="extended UI observer",
                                       max_bytes=MAX_OBSERVER_BYTES)
        if path != self.path.absolute() or len(raw.splitlines()) > MAX_OBSERVER_ROWS:
            raise ObserverError("UI observer proof exceeded its frozen bounds")
        return {
            "schema": "flash-next-ui-observer-summary/v1",
            "pair_id": self.pair_id, "extended_plan_sha256": self.plan_sha256,
            "observer_log_sha256": hashlib.sha256(raw).hexdigest(),
            "observer_log_bytes": len(raw), "ticks": self.ticks,
            "probes": self.probes, "failed_ticks": self.failed_ticks,
            "failed": self.failed,
            "error_type": self.error_type, "first_tick_at": self.first_tick_at,
            "last_tick_at": self.last_tick_at, "joined": True,
        }
