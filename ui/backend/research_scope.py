"""Explicit UI campaign scope; never delete or relabel historical records.

Existing API clients retain ``all``. The operator UI requests ``active`` and
must not fall back to global history when the campaign pointer is invalid.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from orchestrator.research_campaign import (
    CampaignError,
    load_active_campaign,
    record_matches,
    unique_matching_records,
)

ScopeName = Literal["active", "all"]
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_ROWS = 100_000


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _invalid_constant(_value):
    raise ValueError("non-finite JSON value")


def _json(data):
    return json.loads(
        data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )


def _reject_redirected_parents(path: Path) -> None:
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("redirected source directory")


def read_records(path: Path) -> list[dict]:
    """Bounded regular-file snapshot. Unreadable is not an empty campaign."""
    try:
        _reject_redirected_parents(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("not a regular file")
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds read limit")
        lines = [line for line in data.splitlines() if line.strip()]
        if len(lines) > MAX_SOURCE_ROWS:
            raise ValueError("source exceeds row limit")
        rows = [_json(line) for line in lines]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("non-object source row")
        return rows
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise HTTPException(
            503, detail=f"Campaign source unavailable: {path.name}"
        ) from exc


class ResearchScope:
    def __init__(self, name: ScopeName, repo_root: Path, memory_dir: Path):
        self.name = name
        self.memory_dir = Path(memory_dir)
        self.campaign = None
        if name == "active":
            try:
                self.campaign = load_active_campaign(repo_root=Path(repo_root))
            except CampaignError as exc:
                raise HTTPException(
                    503, detail="Active campaign identity is unavailable"
                ) from exc

    def metadata(self) -> dict:
        campaign = self.campaign
        return {
            "mode": self.name,
            "status": "all_research"
            if self.name == "all"
            else ("active" if campaign else "no_active_campaign"),
            "campaign": None
            if campaign is None
            else {
                "campaign_id": campaign["campaign_id"],
                "title": campaign["title"],
                "research_question": campaign["research_question"]["text"],
                "manifest_sha256": campaign["_manifest_sha256"],
                "activated_at": campaign["_activation"]["activated_at"],
            },
            "history_preserved": True,
        }

    def records(self, rows: list[dict], identity: str) -> list[dict]:
        if self.name == "all":
            return rows
        if self.campaign is None:
            return []
        return unique_matching_records(rows, self.campaign, identity_field=identity)

    def iterations(self) -> list[dict]:
        return self.records(
            read_records(self.memory_dir / "loop_memory.jsonl"), "iteration_id"
        )

    def ledger_snapshot(self) -> tuple[list[dict], dict]:
        """Validate bounded bytes before using the existing pure reducer."""
        from jsonschema import ValidationError

        from workers.idea_ledger import reduce_events, validate_event

        events = read_records(self.memory_dir / "idea_ledger.jsonl")
        try:
            for event in events:
                validate_event(event)
            return events, reduce_events(events)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise HTTPException(503, detail="Campaign idea ledger unavailable") from exc

    def clusters(self, state: dict) -> dict:
        if self.name == "all":
            return state
        ids = {row["iteration_id"] for row in self.iterations()}
        # A mixed historical/current cluster cannot donate its old rung,
        # status, title or agenda to the current campaign. Individual current
        # iterations remain available in Record library regardless.
        return {
            key: row
            for key, row in state.items()
            if isinstance(row, dict)
            and isinstance(row.get("members"), list)
            and row["members"]
            and all(member in ids for member in row["members"])
        }

    def todo(self, items: list[dict]) -> tuple[list[dict], int]:
        if self.name == "all":
            return items, 0
        iterations = {row["iteration_id"] for row in self.iterations()}
        findings = {
            row["finding_id"]
            for row in self.records(
                read_records(self.memory_dir / "surfaced_findings.jsonl"), "finding_id"
            )
        }
        bubbles = {
            row["run_id"]
            for row in self.records(
                read_records(self.memory_dir / "coordinator_bubbles.jsonl"), "run_id"
            )
        }
        eligible = {
            "gate_verdict": iterations,
            "finding_review": findings,
            "bubble_ack": bubbles,
        }
        visible = [
            item
            for item in items
            if item.get("kind") in {"state_gate", "stale_active_run"}
            or item.get("id") in eligible.get(item.get("kind"), set())
        ]
        return visible, len(items) - len(visible)

    def experiment_matches(self, results: Path) -> bool:
        if self.name == "all":
            return True
        if self.campaign is None:
            return False
        path = results / "summary.json"
        if not os.path.lexists(path):
            return False
        rows = self._summary(path)
        return bool(len(rows) == 1 and record_matches(rows[0], self.campaign))

    @staticmethod
    def _summary(path: Path) -> list[dict]:
        try:
            _reject_redirected_parents(path)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("not a regular file")
                data = stream.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("summary exceeds read limit")
            row = _json(data)
            if not isinstance(row, dict):
                raise TypeError("summary is not an object")
            return [row]
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                503, detail="Experiment campaign source unavailable"
            ) from exc


def register(app, *, repo_root: Path, memory_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["research_scope"])

    @router.get("/research_scope")
    def research_scope(research_scope: ScopeName = "active"):
        return ResearchScope(research_scope, repo_root, memory_dir).metadata()

    app.include_router(router)
    return router
