"""Inert queue/archive model for PACKET-CTL-4 and SI-R3 fault histories.

All data is in memory. Nothing is scheduled, persisted, executed or promoted.
Sequence comparisons model a serialized durable CAS adapter that does not yet
exist. Hashes detect contradictory bytes, not malicious authorized authors.
Verifier labels/synthetic scores are fixtures, not independent qualification.
"""
from __future__ import annotations

from workers.claim_binding import (
    BindingError, canonical_bytes, digest, load_json, require_digest, require_id,
)


class Quarantined(BindingError):
    """Authoritative history cannot be replayed; do not serve a partial view."""


def _fields(obj, fields):
    if type(obj) is not dict or set(obj) != set(fields):
        raise BindingError("missing or unknown fields")


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise BindingError("invalid integer bound")
    return value


def synthetic_score(patch: str) -> int:
    """Deliberately artificial deterministic score; no empirical meaning."""
    if not isinstance(patch, str) or not patch or len(patch.encode("utf-8")) > 65536:
        raise BindingError("invalid synthetic patch")
    return sum(patch.encode("utf-8")) % 101


def rollback_requirement(kind: str) -> str:
    requirements = {"code": "exact prior code identity",
                    "state": "durable-state migration proof",
                    "protocol": "mixed-version compatibility proof",
                    "effects": "irreversible-effect compensation proof"}
    if not isinstance(kind, str) or kind not in requirements:
        raise BindingError("undeclared rollback class")
    return requirements[kind]


def _packet(packet):
    _fields(packet, ("task_id", "source_id", "base_sha256", "test_command_sha256",
                     "base_release_generation", "budget_units", "rollback_class"))
    require_id(packet["task_id"])
    require_id(packet["source_id"])
    require_digest(packet["base_sha256"])
    require_digest(packet["test_command_sha256"])
    _integer(packet["base_release_generation"])
    _integer(packet["budget_units"], 1)
    rollback_requirement(packet["rollback_class"])


def _owner(task, command):
    if task["status"] != "claimed" or command["at"] >= task["expires_at"]:
        raise BindingError("no current unexpired lease")
    if command["owner"] != task["owner"] or command["generation"] != task["generation"]:
        raise BindingError("stale or foreign lease owner")


def _terminal(task, result):
    _fields(result, ("outcome", "attempt_id", "contract_sha256", "cost_units", "patch",
                     "score", "verifier_id", "reason_sha256"))
    if result["attempt_id"] != task["attempt_id"] or result["contract_sha256"] != task["contract_sha256"]:
        raise BindingError("result does not bind the exact attempt and contract")
    cost = _integer(result["cost_units"])
    outcome = result["outcome"]
    if outcome not in ("candidate", "failed", "evaluator_outage", "over_budget"):
        raise BindingError("unknown terminal outcome")
    if (cost > task["packet"]["budget_units"]) != (outcome == "over_budget"):
        raise BindingError("cost and budget outcome contradict")
    if outcome == "candidate":
        if type(result["score"]) is not int or result["score"] != synthetic_score(result["patch"]):
            raise BindingError("synthetic evaluation does not match exact patch")
        if require_id(result["verifier_id"]) == task["owner"] or result["reason_sha256"] is not None:
            raise BindingError("candidate lacks distinct verifier or has contradictory error")
    else:
        require_digest(result["reason_sha256"])
        if any(result[k] is not None for k in ("patch", "score", "verifier_id")):
            raise BindingError("failed/outage/budget result cannot carry successful evidence")


def _transition(old: dict, command: dict):
    """Return detached next state, whether history grows, and stable receipt ID."""
    canonical_bytes(command)
    if type(command) is not dict:
        raise BindingError("command object required")
    at = _integer(command.get("at"))
    if at < old["at"]:
        raise BindingError("logical clock moved backwards")
    kind = command.get("kind")
    state = load_json(canonical_bytes(old))
    state["at"] = at
    token = digest(canonical_bytes(command))
    if kind == "admit":
        _fields(command, ("kind", "at", "packet"))
        packet = command["packet"]
        _packet(packet)
        task_id, contract = packet["task_id"], digest(canonical_bytes(packet))
        if task_id in state["tasks"]:
            if state["tasks"][task_id]["contract_sha256"] != contract:
                raise BindingError("same task ID reused with changed contract/source bytes")
            return old, False, contract
        state["tasks"][task_id] = dict(packet=load_json(canonical_bytes(packet)),
            contract_sha256=contract, status="queued", generation=0, owner=None,
            expires_at=None, attempt_id=None, terminal=None, archive_id=None)
        token = contract
    elif kind in ("claim", "heartbeat", "finish"):
        extras = {"claim": ("owner", "lease_units"),
                  "heartbeat": ("owner", "generation", "lease_units"),
                  "finish": ("owner", "generation", "result")}[kind]
        _fields(command, ("kind", "at", "task_id", *extras))
        task = state["tasks"].get(require_id(command["task_id"]))
        if task is None:
            raise BindingError("unadmitted task")
        require_id(command["owner"])
        if kind == "claim":
            if task["status"] == "terminal" or (task["status"] == "claimed" and at < task["expires_at"]):
                raise BindingError("task is terminal or already leased")
            task.update(status="claimed", owner=command["owner"],
                        expires_at=at + _integer(command["lease_units"], 1),
                        generation=task["generation"] + 1)
            task["attempt_id"] = digest(canonical_bytes([command["task_id"],
                task["contract_sha256"], task["generation"]]))
            token = task["attempt_id"]
        else:
            _integer(command["generation"], 1)
            if kind == "finish" and task["status"] == "terminal":
                if command["owner"] == task["owner"] and command["generation"] == task["generation"] \
                        and canonical_bytes(command["result"]) == canonical_bytes(task["terminal"]):
                    return old, False, task["archive_id"]
                raise BindingError("conflicting terminal acknowledgement")
            _owner(task, command)
            if kind == "heartbeat":
                expiry = at + _integer(command["lease_units"], 1)
                if expiry <= task["expires_at"]:
                    raise BindingError("heartbeat must extend the current lease")
                task["expires_at"] = expiry
            else:
                result = command["result"]
                _terminal(task, result)
                entry = dict(task_id=command["task_id"], packet=task["packet"],
                    generation=task["generation"], result=result, inert=True, authority="none")
                archive_id = digest(canonical_bytes(entry))
                state["archive"][archive_id] = entry
                task.update(status="terminal", terminal=result, archive_id=archive_id)
                token = archive_id
    elif kind == "simulate_release":
        _fields(command, ("kind", "at", "archive_id", "expected_release_generation"))
        _integer(command["expected_release_generation"])
        if command["expected_release_generation"] != state["release_generation"]:
            raise BindingError("stale release generation")
        entry = state["archive"].get(require_digest(command["archive_id"]))
        if entry is None or entry["result"]["outcome"] != "candidate":
            raise BindingError("archive entry has no verified synthetic candidate")
        if entry["packet"]["base_sha256"] != state["champion"] or \
                entry["packet"]["base_release_generation"] != state["release_generation"]:
            raise BindingError("candidate was evaluated against a stale parent")
        if entry["packet"]["rollback_class"] != "code":
            raise BindingError(rollback_requirement(entry["packet"]["rollback_class"]))
        candidate = digest(entry["result"]["patch"].encode("utf-8"))
        if candidate == state["champion"]:
            raise BindingError("no new descendant")
        state["champion"] = candidate
        state["release_generation"] += 1
        state["releases"].append(candidate)
    elif kind == "simulate_code_rollback":
        _fields(command, ("kind", "at", "target_sha256", "expected_release_generation"))
        _integer(command["expected_release_generation"])
        target = require_digest(command["target_sha256"])
        if command["expected_release_generation"] != state["release_generation"] \
                or target not in state["releases"] or target == state["champion"]:
            raise BindingError("stale, unknown or unchanged code rollback")
        state["champion"] = target
        state["release_generation"] += 1  # never rewind the fencing generation
        state["releases"].append(target)
    else:
        raise BindingError("unsupported event; intake is not an admitted packet")
    return state, True, token


class Simulator:
    """A single-threaded model. Never use as a live atomic queue adapter."""

    def __init__(self, initial_champion: str):
        self._header = canonical_bytes(dict(format="inert-archive-v1",
                                             initial_champion=require_digest(initial_champion)))
        self._events: tuple[bytes, ...] = ()
        self._state = dict(at=0, tasks={}, archive={}, champion=initial_champion,
                           release_generation=0, releases=[initial_champion])

    @property
    def sequence(self):
        return len(self._events)

    def view(self):
        return load_json(canonical_bytes(self._state))

    def export(self) -> tuple[bytes, ...]:
        return (self._header, *self._events)

    @staticmethod
    def history_sha256(lines: tuple[bytes, ...]) -> str:
        return digest(b"\n".join(lines) + b"\n")

    def submit(self, command: dict, *, expected_sequence: int) -> str:
        _integer(expected_sequence)
        if expected_sequence != self.sequence:
            raise BindingError("stale compare-and-swap sequence")
        command = load_json(canonical_bytes(command))
        state, changed, receipt = _transition(self._state, command)
        if changed:
            prev = digest(self._header) if not self._events else load_json(self._events[-1])["event_sha256"]
            payload = dict(sequence=self.sequence + 1, previous_sha256=prev, command=command)
            payload["event_sha256"] = digest(canonical_bytes(payload))
            self._events += (canonical_bytes(payload),)
            self._state = state
        return receipt

    @classmethod
    def from_lines(cls, lines: tuple[bytes, ...], *, expected_history_sha256: str):
        row = 0
        try:
            if type(lines) is not tuple or not lines:
                raise BindingError("complete immutable history tuple required")
            if cls.history_sha256(lines) != require_digest(expected_history_sha256):
                raise BindingError("history bytes differ from independently pinned snapshot")
            header = load_json(lines[0])
            _fields(header, ("format", "initial_champion"))
            if header["format"] != "inert-archive-v1":
                raise BindingError("unknown history version")
            simulator = cls(header["initial_champion"])
            if lines[0] != simulator._header:
                raise BindingError("authoritative header bytes are not canonical")
            for row, line in enumerate(lines[1:], 1):
                event = load_json(line)
                _fields(event, ("sequence", "previous_sha256", "command", "event_sha256"))
                old_sequence = simulator.sequence
                simulator.submit(event["command"], expected_sequence=old_sequence)
                if simulator.sequence == old_sequence or line != simulator._events[-1]:
                    raise BindingError("invalid sequence/hash chain or duplicate authoritative event")
            return simulator
        except (BindingError, TypeError, UnicodeError, KeyError) as exc:
            raise Quarantined(f"history quarantined at row {row}: {exc}") from exc

    def rebuild_projection(self):
        lines = self.export()
        return self.from_lines(lines, expected_history_sha256=self.history_sha256(lines)).view()

    def legitimate_projection(self, projection) -> bool:
        """History failure raises; an invalid derived projection simply differs."""
        authoritative = self.rebuild_projection()
        try:
            return canonical_bytes(projection) == canonical_bytes(authoritative)
        except BindingError:
            return False
