"""Isolated I1 candidate store; never selected by the running apparatus.

The caller must supply an explicit SQLite path and maintain trusted private
directory ancestry/lifecycle. Only parent-directory existence and leaf symlinks
are checked: ancestor symlinks, permissions and ownership are not validated,
and checking a path before opening it does not prevent replacement races.
Transactions reserve IDs before return and append immutable claims/receipts.
Idempotence covers this store's receipt insertion, NOT a worker's external
effects. The caller must provide a verified legacy sequence floor before runtime
integration. No existing cache, schema, or canonical ledger is modified here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from workers.claim_binding import (
    BindingError, Claim, canonical_bytes, digest, load_json, require_digest,
    require_id,
)


class AttemptStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.is_symlink() or not self.path.parent.is_dir():
            raise BindingError("store requires an existing parent directory and no leaf symlink")
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY, iteration_id TEXT UNIQUE NOT NULL,
                    day TEXT NOT NULL, sequence INTEGER NOT NULL,
                    reserved_at TEXT NOT NULL, UNIQUE(day, sequence));
                CREATE TABLE IF NOT EXISTS claims (
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    claim_sha256 TEXT NOT NULL, canonical BLOB NOT NULL,
                    supersedes TEXT, PRIMARY KEY(attempt_id, claim_sha256));
                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_sha256 TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    dispatch_id TEXT NOT NULL, canonical BLOB NOT NULL,
                    UNIQUE(attempt_id, dispatch_id));
            """)

    @contextmanager
    def _connection(self):
        if self.path.is_symlink():
            raise BindingError("store path became a symlink")
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def reserve(self, day: str, *, minimum_sequence: int = 0) -> dict:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise BindingError("day must be an ISO calendar date")
        if type(minimum_sequence) is not int or minimum_sequence < 0:
            raise BindingError("minimum sequence must be a nonnegative integer")
        with self._transaction() as db:
            last = db.execute("SELECT MAX(sequence) FROM attempts WHERE day=?",
                              (day,)).fetchone()[0] or 0
            sequence = max(last, minimum_sequence) + 1
            row = {"attempt_id": "attempt-" + uuid4().hex,
                   "iteration_id": f"iter-{day}-{sequence:03d}",
                   "reserved_at": datetime.now(timezone.utc).isoformat()}
            db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?)",
                       (row["attempt_id"], row["iteration_id"], day, sequence,
                        row["reserved_at"]))
        return row

    @staticmethod
    def _iteration(db, attempt_id):
        row = db.execute("SELECT iteration_id FROM attempts WHERE attempt_id=?",
                         (require_id(attempt_id),)).fetchone()
        if row is None:
            raise BindingError("unknown attempt")
        return row[0]

    def put_claim(self, attempt_id: str, claim: Claim) -> None:
        with self._transaction() as db:
            self._iteration(db, attempt_id)
            if claim.supersedes is not None and not db.execute(
                    "SELECT 1 FROM claims WHERE attempt_id=? AND claim_sha256=?",
                    (attempt_id, claim.supersedes)).fetchone():
                raise BindingError("unknown superseded claim in this attempt")
            prior = db.execute(
                "SELECT canonical, supersedes FROM claims WHERE attempt_id=? AND claim_sha256=?",
                (attempt_id, claim.claim_sha256)).fetchone()
            if prior is not None:
                if prior != (claim.canonical, claim.supersedes):
                    raise BindingError("claim identity reuse with different lineage")
                return
            existing = db.execute("SELECT claim_sha256, supersedes FROM claims WHERE attempt_id=?", (attempt_id,)).fetchall()
            heads = {h for h, _ in existing} - {parent for _, parent in existing}
            if existing and (claim.supersedes not in heads or len(heads) != 1):
                raise BindingError("claim revision must supersede the unique current head")
            db.execute("INSERT INTO claims VALUES (?, ?, ?, ?)",
                       (attempt_id, claim.claim_sha256, claim.canonical, claim.supersedes))

    def put_receipt(self, attempt_id: str, claim_sha256: str, *, dispatch_id: str,
                    step: str, producer: str, parent_request_id: str,
                    source_receipt_ids: list[str], output: dict,
                    status: str = "passed", supersedes: str | None = None) -> str:
        require_digest(claim_sha256)
        if status not in ("passed", "failed", "skipped"):
            raise BindingError("invalid execution status")
        if type(output) is not dict or type(source_receipt_ids) is not list:
            raise BindingError("output must be an object; sources must be a list")
        if len(source_receipt_ids) != len(set(source_receipt_ids)):
            raise BindingError("duplicate source receipt")
        for value in source_receipt_ids:
            require_digest(value)
        if supersedes is not None:
            require_digest(supersedes)
        with self._transaction() as db:
            iteration_id = self._iteration(db, attempt_id)
            if not db.execute("SELECT 1 FROM claims WHERE attempt_id=? AND claim_sha256=?",
                              (attempt_id, claim_sha256)).fetchone():
                raise BindingError("unknown claim in this attempt")
            for source in source_receipt_ids + ([] if supersedes is None else [supersedes]):
                row = db.execute("SELECT canonical FROM receipts WHERE receipt_sha256=? AND attempt_id=?",
                                 (source, attempt_id)).fetchone()
                if row is None or digest(row[0]) != source:
                    raise BindingError("unknown or corrupt source receipt")
                if source in source_receipt_ids and load_json(row[0])["input_claim_sha256"] != claim_sha256:
                    raise BindingError("source evidence belongs to another claim version")
                if source in source_receipt_ids and status == "passed" and load_json(row[0])["status"] != "passed":
                    raise BindingError("successful receipt cannot cite unsuccessful evidence")
                if source == supersedes and load_json(row[0])["step"] != step:
                    raise BindingError("retry must supersede the same step")
            record = dict(attempt_id=attempt_id, iteration_id=iteration_id,
                          input_claim_sha256=claim_sha256,
                          dispatch_id=require_id(dispatch_id), step=require_id(step),
                          producer=require_id(producer),
                          parent_request_id=require_id(parent_request_id),
                          source_receipt_ids=source_receipt_ids, output=output,
                          status=status, supersedes=supersedes)
            data = canonical_bytes(record)
            receipt_id = digest(data)
            prior = db.execute("SELECT receipt_sha256, canonical FROM receipts WHERE attempt_id=? AND dispatch_id=?",
                               (attempt_id, dispatch_id)).fetchone()
            if prior is not None:
                if prior != (receipt_id, data):
                    raise BindingError("dispatch identity already has different receipt bytes")
                return receipt_id
            claims = db.execute("SELECT claim_sha256, supersedes FROM claims WHERE attempt_id=?",
                                (attempt_id,)).fetchall()
            claim_heads = {h for h, _ in claims} - {parent for _, parent in claims}
            if claim_heads != {claim_sha256}:
                raise BindingError("new receipt requires the unique current claim head")
            records = []
            for rid, raw in db.execute("SELECT receipt_sha256, canonical FROM receipts WHERE attempt_id=?", (attempt_id,)):
                if digest(raw) != rid:
                    raise BindingError("corrupt receipt history")
                records.append((rid, load_json(raw)))
            same_step = [(rid, r) for rid, r in records if r["step"] == step]
            heads = {rid for rid, _ in same_step} - {r["supersedes"] for _, r in same_step}
            if same_step and (supersedes not in heads or len(heads) != 1):
                raise BindingError("retry must supersede the unique current step head")
            superseded = {r["supersedes"] for _, r in records}
            if status == "passed" and any(rid in superseded for rid in source_receipt_ids):
                raise BindingError("successful receipt cites superseded evidence")
            db.execute("INSERT INTO receipts VALUES (?, ?, ?, ?)",
                       (receipt_id, attempt_id, dispatch_id, data))
        return receipt_id

    def read_receipt(self, receipt_id: str) -> dict:
        require_digest(receipt_id)
        with self._connection() as db:
            row = db.execute("SELECT canonical FROM receipts WHERE receipt_sha256=?",
                             (receipt_id,)).fetchone()
        if row is None or digest(row[0]) != receipt_id:
            raise BindingError("unknown or corrupt receipt")
        return load_json(row[0])

    def verify_for_commit(self, attempt_id: str, claim: Claim, receipt_ids: list[str],
                          *, required_steps: tuple[str, ...],
                          required_sources: dict[str, tuple[str, ...]]) -> None:
        """Snapshot eligibility, not a journal commit or worker-truth proof.

        The trusted caller declares the exact expected step DAG. A later
        atomic journal adapter must recheck this snapshot at its commit boundary.
        """
        if not required_steps or len(set(required_steps)) != len(required_steps):
            raise BindingError("required steps must be nonempty and unique")
        if type(required_sources) is not dict or set(required_sources) != set(required_steps):
            raise BindingError("exact expected source graph required")
        for step, sources in required_sources.items():
            if type(sources) is not tuple or len(set(sources)) != len(sources) or step in sources \
                    or not set(sources).issubset(required_steps):
                raise BindingError("invalid expected source graph")
        if len(receipt_ids) != len(set(receipt_ids)):
            raise BindingError("duplicate commit receipt")
        with self._transaction() as db:
            iteration_id = self._iteration(db, attempt_id)
            claims = db.execute("SELECT claim_sha256, canonical, supersedes FROM claims WHERE attempt_id=?",
                                (attempt_id,)).fetchall()
            registered = {h: raw for h, raw, _ in claims}
            if registered.get(claim.claim_sha256) != claim.canonical:
                raise BindingError("claim is not registered for this attempt")
            if claim.claim_sha256 in {parent for _, _, parent in claims}:
                raise BindingError("claim has been superseded")
            claim_heads = set(registered) - {parent for _, _, parent in claims}
            if claim_heads != {claim.claim_sha256}:
                raise BindingError("verification requires the unique current claim head")
            records = {}
            for rid, raw in db.execute("SELECT receipt_sha256, canonical FROM receipts WHERE attempt_id=?", (attempt_id,)):
                if digest(raw) != rid:
                    raise BindingError("corrupt receipt history")
                records[rid] = load_json(raw)
            found = {}
            superseded = {r["supersedes"] for r in records.values()}
            for rid in receipt_ids:
                r = records.get(rid)
                if r is None or r["attempt_id"] != attempt_id or r["iteration_id"] != iteration_id \
                        or r["input_claim_sha256"] != claim.claim_sha256 or r["status"] != "passed":
                    raise BindingError("wrong identity or unsuccessful commit evidence")
                if rid in superseded:
                    raise BindingError("selected receipt has been superseded")
                if r["step"] in found:
                    raise BindingError("duplicate evidence step")
                found[r["step"]] = rid
            if set(found) != set(required_steps):
                raise BindingError("missing or unexpected evidence steps")
            for step, rid in found.items():
                expected = {found[source] for source in required_sources[step]}
                if set(records[rid]["source_receipt_ids"]) != expected:
                    raise BindingError("receipt sources differ from exact selected dependency graph")
