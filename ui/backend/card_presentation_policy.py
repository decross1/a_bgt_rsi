"""Narrow, source-controlled presentation exceptions for legacy owner cards.

The Oracle/Nara mailbox authenticates ordering and byte preservation, not its
actor labels.  Consequently, a normal ``question_resolution`` or a note saying
that a session was delegated must never remove an owner action.  This module is
not a general resolution protocol.  It records the small, independently
reviewed historical set that the dashboard may *present* as archived or routed.

Each exception is bound to the complete SHA-256 of both rows that justify it.
Changing any source row, duplicating its identity, or adding a superficially
similar future row makes the exception disappear rather than widening it.
"""
from __future__ import annotations

from collections.abc import Iterable


# (question msg id, question row sha256, evidence msg id, evidence row sha256)
# These rows were reviewed as historical supersession/withdrawal/prerequisite
# claims.  The effect is presentation-only: no mailbox authority is conferred
# and no future row is covered by this table.
HISTORICAL_ARCHIVES = (
    ("oracle-0eb4b4117656adad", "d394d2571e8af8d98239faf60260d9f7713224dfc951cbb3975bdcc67704ec59",
     "oracle-bf2eff918802894e", "46512654380daacf911f4eeb3fddb9b2a7804b3f664a79e0c817f2639ad448b5"),
    ("oracle-da79077408eb0a1d", "f9bd7b49a2b908c287d330d9f59022faa00758e7d4b5387ec7417b1e418c8852",
     "oracle-1401bd6bb661c9d7", "d51b7e8d970abc8eb7128700bf7979768d2ed7065aff146657fd4c2f56843407"),
    ("oracle-a0e6f9e20abd6de7", "f61cf43042f60dbc887ef599eb2ee539ee628f52e06c11396b7d58a07d24aa40",
     "oracle-06e1c0e3f1dc3495", "0571c84ee076031933103f6f030cb2ca4e01b82ea4645c3bf85598279490b3fc"),
    ("oracle-20819142605d114b", "02d3778b3c845ee0d1d3f455ef927c4c9d84808c7a81f6ee6e17be975be5d4c2",
     "oracle-8e2a246be955cf9e", "936a0f14c70471deb203aa07e31cc7b33a7873e65780433040edf9af24d0420a"),
    ("oracle-acd9d1f742e36e83", "71ef912ac2df1ad56a4ec3a6b614b7c7998a0d5eef560741f83adcbe8bcf4d9f",
     "oracle-84578daf1ce36134", "2d5202f807ddbfd1d21ebe22b0800f05ca0b3aa5b30febb3ff826401a26f85e1"),
    ("oracle-6c7e1f4cd076922d", "c2484c98ad0b24b90c338d82422d45eb0595a5cf72d4b3cdc923cb4b5feb6698",
     "oracle-9041774ff1c344d3", "2bc6a197e24f378ef152a4aa3c60e07276515d2001814468307d470efe44e2c5"),
    ("oracle-3c4be35ad37f564d", "bc0ef74007aec71f90ba1e1bf2271552c15fa53a2b324f5331fd08e81bc0765d",
     "oracle-16d27275a3b1c8f5", "727370fbbaea92f7c2b5a13ca0748b1edf8520d6edec6aa699582ae0efb6d829"),
    ("oracle-f5525d16cbc23b7c", "3ca548be9493e7b1c490f618045188e0b0e97cac76e63d7eb2780cf63aac638f",
     "oracle-e8713d59bafaaf8f", "55a8b9f173c36d9756ee67e7dcbe0c96761c2cfad2b400a5e2204a47e73d4ebf"),
    ("oracle-04ba6663f61c4a1c", "4c4c79b12c6bfba52f6e4cdb87f0e5d34d357077e08cc8a3da2a72527439a62c",
     "oracle-95790522f1998fce", "cd6817d9d2f4c8ebe4a517705e3709f4ff5d18d2cedf043132f9298bd664d83a"),
    ("oracle-8a39b4976cd70950", "44316dadb5d34bc70d6b878eab46408dd54f5ce3087ee6c1680c37ee0eb1e11a",
     "oracle-fcca39bc2189b243", "0152d98d735305c7739e7e907b1d8dcb509c4ca86b5d1330e70be4dcffe9e3fa"),
)

# The one reviewed routing note.  It does not resolve any question; it only
# sends these exact open cards to interactive Claude for disposition.
CLAUDE_HANDOFF = (
    "codex-7b2e67c525e4330e",
    "b8a2279fb0d50414a8841553ffba9566b25f8d18f566b7968c3d850cac05ef0c",
    (
        ("claude-18ae939243e70e7d", "448ff2e132e9e637da9daa5e235cf2ac68c5adad2403838ca77c765bb81de1d1"),
        ("claude-81a020b8a67564fb", "127714a861036324ae887194ecdde3c0eecfa8f33ed98e43b446556d1f351dd5"),
        ("claude-be888586650d41c7", "5d085929781ec2ed4de1033b1458db34b0611dea753807ea0abf70a47bbd9644"),
        ("claude-29abf7a047709c1b", "c01d215da4854217e895fb8f00ef07a0bf04daad074cd44c282c51b7d274e080"),
        ("claude-ea80ba6d45758d49", "41bd54cebc9c2ec273246150c99ec4e8b30bda6b6286c361e2f63b84f486a090"),
    ),
)


def _one_exact(rows: Iterable[dict], msg_id: str, sha256: str) -> dict | None:
    all_ids = [row for row in rows if isinstance(row, dict) and row.get("msg_id") == msg_id]
    matches = [row for row in all_ids if row.get("row_sha256") == sha256]
    return matches[0] if len(all_ids) == 1 and len(matches) == 1 else None


def historical_archive(question: dict, rows: list[dict]) -> dict | None:
    """Return an exact historical presentation archive, otherwise ``None``.

    This does not inspect actor names or unpinned evidence.  In particular,
    seq815/819 and the contested seq604/672/680 chain intentionally are absent.
    """
    for question_id, question_sha, evidence_id, evidence_sha in HISTORICAL_ARCHIVES:
        if (question.get("msg_id") != question_id or question.get("row_sha256") != question_sha):
            continue
        source = _one_exact(rows, question_id, question_sha)
        evidence = _one_exact(rows, evidence_id, evidence_sha)
        if source is None or evidence is None:
            return None
        if (source.get("kind") != "question" or source.get("to") != "owner"
                or evidence.get("kind") != "question_resolution"
                or evidence.get("in_reply_to") != question_id):
            return None
        return evidence
    return None


def interactive_claude_handoff(question: dict, rows: list[dict]) -> dict | None:
    """Return the one exact audited routing note, never a generic handoff."""
    note_id, note_sha, questions = CLAUDE_HANDOFF
    if (question.get("msg_id"), question.get("row_sha256")) not in questions:
        return None
    note = _one_exact(rows, note_id, note_sha)
    if note is None or not (note.get("kind") == "note" and note.get("actor") == "codex"
                             and note.get("to") == "claude"):
        return None
    ref = note.get("body", {}).get("ref") if isinstance(note.get("body"), dict) else None
    expected_ids = [question_id for question_id, _ in questions]
    if not isinstance(ref, dict) or ref.get("question_ids") != expected_ids:
        return None
    # Hashes bind today's order, but preserve the ordering condition explicitly:
    # a future row cannot retroactively route a question that appeared later.
    question_positions = [index for index, row in enumerate(rows) if row is question]
    note_positions = [index for index, row in enumerate(rows) if row is note]
    if len(question_positions) != 1 or len(note_positions) != 1 or question_positions[0] >= note_positions[0]:
        return None
    return note
