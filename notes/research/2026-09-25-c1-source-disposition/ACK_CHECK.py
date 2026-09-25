#!/usr/bin/env python3
"""Source-only self-check for the C1 source disposition (bounded, stdlib, offline).

Run from the repo root of a clean checkout of this branch:

    python3 notes/research/2026-09-25-c1-source-disposition/ACK_CHECK.py

This is NOT a plan-item acceptance check: seq 745 REJECTed the r9 plan that
contained b3, so no plan item is admitted (seq 756 amendment 2). It asserts
only claims the disposition file itself makes, and it is written so that a
stub cannot pass by shuffling or duplicating rows:

  * the six disposition rows carry exactly one verdict each;
  * the source IDs form an exact, unique, once-only set matched against the
    pinned matrix — duplicating a retained-negative row while omitting another
    fails, because the set must be equal, not merely the same size;
  * each ID is checked against the verdict the matrix supports, not just a
    total;
  * the four machine reopening statuses are asserted by key and value;
  * hashes recorded in the file equal the bytes present in this checkout.

Exit 0 and print ACK-CHECK PASS on success; raise (non-zero exit) otherwise.
"""
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
DISP = ROOT / "notes/research/2026-09-25-c1-source-disposition/DISPOSITION.md"
MATRIX = ROOT / "notes/research/2026-09-25-c1-neighbor-prior-art/C1_EXACT_CLAIM_MATRIX.md"
SCREEN = ROOT / "notes/research/2026-09-25-c1-bounded-source-screen/SOURCE_SCREEN.md"
T_GATE = ROOT / "notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md"

RN = "**retained-negative**"
AU = "**abstract-only-Unknown**"

FAILED = []


def check(cond, label):
    if not cond:
        FAILED.append(label)


text = DISP.read_text()

# 1. Machine summary block parses and carries the expected contract fields.
block = re.search(r"## Machine summary\n\n```json\n(.*?)\n```", text, re.S)
check(block is not None, "machine summary json block present")
data = json.loads(block.group(1)) if block else {}
for key in (
    "rows",
    "retained_negative",
    "abstract_only_unknown",
    "garcia_rows_abstract_only_unknown",
    "corrections_to_matrix",
    "stop_code",
    "matrix_sha256",
    "matrix_head",
    "base_main",
    "gate_state_changed",
    "novelty_claimed",
    "thesis_or_focus_selected",
    "study_registered",
    "flash_used",
    "model_or_service_action",
    "owner_question_created",
):
    check(key in data, f"machine summary has field {key}")

# 2. Six disposition rows, one verdict each, no row double-counted or omitted.
rows = [ln for ln in text.splitlines() if re.match(r"^\| \d+ \| ", ln)]
check(len(rows) == 6, f"six disposition rows (got {len(rows)})")
per_row = [(RN in ln) + (AU in ln) for ln in rows]
check(all(n == 1 for n in per_row), "each row carries exactly one verdict")
rn_rows = [ln for ln in rows if RN in ln]
au_rows = [ln for ln in rows if AU in ln]
check(len(rn_rows) == 4, f"four retained-negative rows (got {len(rn_rows)})")
check(len(au_rows) == 2, f"two abstract-only-Unknown rows (got {len(au_rows)})")
check(all("Garcia" in ln for ln in au_rows), "both Unknown rows are Garcia rows")
check(not any(("Garcia" in ln) and (RN in ln) for ln in rows), "no Garcia row is retained-negative")

# 2b. Exact six-source identity: IDs must match the pinned matrix as a set,
#     each appearing exactly once, and each carrying the verdict that source
#     supports. A row duplicated while another is omitted fails here even
#     though the row count and verdict totals would still pass (seq 756 AM2).
SOURCE_IDS = {
    "2607.05545": RN,   # Hu & Qu
    "2608.07920": RN,   # Shu
    "2505.13488": RN,   # Germani & Spitale
    "2608.25869": RN,   # Kapetanovic et al.
    "7411618": AU,      # Garcia, which number is sticky
    "6366838": AU,      # Garcia, algorithmic anchoring
}
def source_ids(line):
    """Return bare source ids (arXiv id without version, or SSRN id).

    `arXiv:2607.05545v1` -> `2607.05545`; the version suffix and any trailing
    text are excluded so one row yields exactly one token.
    """
    out = set()
    for m in re.finditer(r"(?:arXiv:|SSRN )([0-9]+\.[0-9]+|[0-9]+)", line):
        out.add(m.group(1))
    return out


row_ids = [source_ids(ln) for ln in rows]
dup_rows = [i for i, s in enumerate(row_ids) if len(s) != 1]
check(not dup_rows, f"each row names exactly one source id (violations: {dup_rows})")
flat = [next(iter(s)) for s in row_ids if len(s) == 1]
check(len(flat) == len(set(flat)) == 6, f"six unique source ids, once each (got {flat})")
check(set(flat) == set(SOURCE_IDS), "row ids equal the pinned matrix source-id set")
for rid, expected in SOURCE_IDS.items():
    owning = [ln for ln, s in zip(rows, row_ids) if s == {rid}]
    check(len(owning) == 1, f"{rid} appears in exactly one disposition row")
    if len(owning) == 1:
        got = RN if RN in owning[0] else AU if AU in owning[0] else None
        check(got == expected, f"{rid} verdict is {expected} (got {got})")

# 2c. Row-to-matrix alignment: each disposition source id must also occur in
#     the pinned accepted matrix bytes, so rows cannot be invented.
matrix_text = MATRIX.read_text() if MATRIX.is_file() else ""
for rid in SOURCE_IDS:
    check(rid in matrix_text, f"{rid} is present in the pinned matrix bytes")

# 3. Counts agree with the machine summary, and the summary claims no authority.
check(
    data.get("retained_negative", -1) + data.get("abstract_only_unknown", -1) == data.get("rows", -2) == 6,
    "summary counts sum to rows == 6",
)
check(data.get("garcia_rows_abstract_only_unknown") == len(au_rows), "Garcia Unknown count matches rows")
check(data.get("stop_code") == "insufficient_full_text_binding", "stop code persists")
check(data.get("gate_state_changed") is False, "no gate change claimed")
check(data.get("novelty_claimed") is False, "no novelty claimed")
check(data.get("thesis_or_focus_selected") is False, "no thesis/focus selected")
check(data.get("study_registered") is False, "no study registered")
check(data.get("flash_used") is False, "no Flash spend claimed")
check(data.get("model_or_service_action") is False, "no model/service action claimed")
check(data.get("owner_question_created") is False, "no owner question claimed")

# 4. Hashes recorded in the file match the bytes actually present in this checkout.
check(MATRIX.is_file(), "pinned matrix file present in this commit")
matrix_sha = hashlib.sha256(MATRIX.read_bytes()).hexdigest() if MATRIX.is_file() else ""
check(matrix_sha == data.get("matrix_sha256"), "recorded matrix sha256 equals present matrix bytes")
check(
    hashlib.sha256(SCREEN.read_bytes()).hexdigest()
    == "5b1c301fabe163834e5a40171ac08970efbfd5579aa1492d21dc5c0bdc454aee",
    "source screen bytes are the accepted main revision",
)
check(
    hashlib.sha256(T_GATE.read_bytes()).hexdigest()
    == "1766b07ac41d6d4141817ebdf84e9be9254562a6a86450e456ec296d85a30708",
    "T_GATE_CHOICE bytes are the committed seq407 design",
)

# 5. All four reopening conditions are asserted by key AND value, and the
#    disposition names them in prose (seq 756 AM2: text/UNMET counts alone
#    would let a row be missing or inverted).
EXPECTED_REOPENING = {
    "garcia_full_text": "unmet",
    "git_reachable_corpus_binding": "unmet_route_decision_open",
    "exact_claim_matrix": "delivered_and_dispositioned",
    "c1_a_data": "absent_no_named_dataset",
}
reopening = data.get("reopening_conditions", {})
check(set(reopening) == set(EXPECTED_REOPENING), "four reopening keys, no more/no fewer")
for key, value in EXPECTED_REOPENING.items():
    check(reopening.get(key) == value, f"reopening.{key} == {value} (got {reopening.get(key)})")
check(text.count("still UNMET") >= 2, "at least two reopening conditions recorded still-unmet")
check("DELIVERED" in text, "condition 3 recorded delivered")

# 6. It does not rely on the withdrawn probe as evidence.
check("cannot ever surface" in text, "probe wording is quoted as withdrawn")
check(
    data.get("probe_evidence_used", "").startswith("withdrawn"),
    "probe evidence declared withdrawn, not relied on",
)

if FAILED:
    print("ACK-CHECK FAIL")
    for f in FAILED:
        print(f"  - {f}")
    sys.exit(1)

print(f"ACK-CHECK PASS: 6 rows, 4 retained-negative, 2 Garcia abstract-only-Unknown, matrix sha256 {matrix_sha[:12]}... verified from present bytes")
