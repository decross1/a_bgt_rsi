"""Incremental byte-offset reader for append-only JSONL files.

See ui_plan.md section 5.2: the call logs and telemetry are actively
appended, so the backend must not re-slurp whole files. A JsonlTailer
remembers a byte offset and returns only records from lines appended
since the last read. A trailing partial line (writer mid-append) is held
back until its newline arrives. If the file shrinks (truncation or
rotation) the offset resets to 0.

FIRST-ATTACH SEMANTICS (2026-08-15 fix): by default the tailer attaches
at EOF — the first ``read_new`` (or ``seek_to_end``) records the file's
current size and returns nothing; only lines appended AFTER that are
ever parsed. This is the fix for the 6.5GB ``/api/health`` hang
(2026-08-15, rotated operationally): a backend restart must never
re-parse a giant pre-existing telemetry/call log just to tail it.
History is therefore NOT replayed. The one consumer whose in-memory
index IS the history — ``chain.LogStore`` — opts back in with
``replay=True`` (its files are the bounded day/exp logs, and without
replay the /chain inspector would go blind to pre-restart records).
"""
import json
from pathlib import Path


class JsonlTailer:
    def __init__(self, path, replay=False):
        self.path = Path(path)
        # None == "not yet attached": the first read attaches at the file's
        # CURRENT size (forward-only). replay=True keeps the legacy
        # from-byte-0 first read for index-building consumers (chain.LogStore).
        self._offset = 0 if replay else None

    def reset(self):
        """Explicitly replay from the start of the file on the next read."""
        self._offset = 0

    def seek_to_end(self):
        """Skip whatever is already in the file. Used for forward-only streaming."""
        if not self.path.exists():
            self._offset = 0
            return
        try:
            self._offset = self.path.stat().st_size
        except OSError:
            self._offset = 0

    def read_new(self):
        """Return a list of parsed objects from newly-appended complete lines.

        The FIRST call attaches: it seeks to the file's current end and
        returns [] (unless constructed with replay=True) — a pre-existing
        file, however large, is never re-parsed on attach.
        """
        if self._offset is None:       # first attach -> EOF, never replay
            self.seek_to_end()
            return []
        if not self.path.exists():
            return []
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._offset:        # truncated or rotated -> start over
            self._offset = 0
        if size == self._offset:
            return []

        with open(self.path, "rb") as fh:
            fh.seek(self._offset)
            data = fh.read()

        last_newline = data.rfind(b"\n")
        if last_newline == -1:
            return []                  # only a partial line so far
        self._offset += last_newline + 1

        records = []
        text = data[:last_newline + 1].decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue               # skip malformed; never crash the tail
        return records
