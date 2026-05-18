"""Incremental byte-offset reader for append-only JSONL files.

See ui_plan.md section 5.2: the call logs and telemetry are actively
appended, so the backend must not re-slurp whole files. A JsonlTailer
remembers a byte offset and returns only records from lines appended
since the last read. A trailing partial line (writer mid-append) is held
back until its newline arrives. If the file shrinks (truncation or
rotation) the offset resets to 0.
"""
import json
from pathlib import Path


class JsonlTailer:
    def __init__(self, path):
        self.path = Path(path)
        self._offset = 0

    def reset(self):
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
        """Return a list of parsed objects from newly-appended complete lines."""
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
