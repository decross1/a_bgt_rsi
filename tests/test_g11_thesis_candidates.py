"""Acceptance for plan 2026-09-24 d1 (G1.1): 3-5 thesis candidates from the brief.

STRUCTURE ONLY, per docs/v2/THESIS_BRIEF_2026-09-23.md lines 39-53: presence and
ranges, never prose. Citation reality is Oracle's screen (claude-5dea097dd434208a
amendment 3, D-061). Sections, labelled lines and table rows all read; the fixture holds
one per shape, asserted last.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "notes/research/2026-09-24-g11-candidates/CANDIDATES.md"
PLACEHOLDER = re.compile(r"placeholder|todo|tbd|fixme|<[a-z_ ]+>|\.{3}", re.I)
FIELDS = {"title": ("title",), "question": ("question",), "lens": ("lens",),
          "prior": ("prior", "related work"), "theory": ("theory", "t ·", "t .", "t-"),
          "semi": ("semi-synthetic", "s ·", "s .", "s-"),
          "applied": ("applied", "a ·", "a .", "a-"),
          "falsifier": ("falsifier",), "anomaly": ("anomaly",), "cost": ("cost",),
          "conviction": ("conviction",)}
REQUIRED = tuple(FIELDS)  # every one must be present and filled in each candidate
STAGES = {"theory": [(r"openspiel|decision problem|\bgam", "a game or decision problem"),
                     (r"benchmark|equilibrium", "a benchmark"),
                     (r"decision rule|preregist|threshold", "a decision rule")],
          "semi": [(r"arm", "arms"), (r"n\s*=\s*\d|sample", "a sample"), (r"outcome", "an outcome"),
                   (r"missing", "a missing-data rule")],
          "applied": [(r"option|prediction market|crypto|market|venue", "a market"),
                      (r"\bdata\b|snapshot|historical|series|history", "its data")]}
PROBABILITIES = ("p_pass_T", "p_pass_S", "p_pass_A", "p_dead_end")
CONVICTION_FIELDS = PROBABILITIES + ("interest_0_10",)


def text():
    return DOC.read_text()


CANDIDATE = re.compile(r"(?im)^[ \t]*#{1,6}[ \t]*[^\n]*\bcandidates?\b[^\n]*$")


def ranges():
    """(start, end) per candidate; a document title naming `candidates` is not one."""
    found = [m.start() for m in CANDIDATE.finditer(text()) if m.start() > 0]
    return [(s, min([e for e in found if e > s], default=len(text()))) for s in found]


HEADING = re.compile(r"(?im)^[ \t]*#{1,6}[ \t]*(.+?)[ \t]*$")


filled = lambda v: bool(v) and len(v.strip()) > 3 and not PLACEHOLDER.search(v)


def captions(block):  # (offset, text) of every heading in a candidate
    return [(m.start(), m.group(1)) for m in HEADING.finditer(block or "")]


def field(rng, key):
    """One field's text, or None when absent. Shapes join, so a split field reads whole."""
    block, names = text()[rng[0]:rng[1]], FIELDS[key]
    found, heads = [], captions(block)
    for i, (offset, caption) in enumerate(heads):
        if not offset:  # the block's heading is a Title only if it names something
            named = re.sub(r"(?i)candidates?\s*\d*\s*[:.\-]?\s*", "", caption).strip()
            if key == "title" and len(named) > 3:
                found.append(named)
            continue
        if not any(re.search(r"(?i)\b%s\b" % re.escape(n).replace(r"\ ", r"\s"), caption) for n in names):
            continue
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(block)
        found.append(block[block.index("\n", offset) + 1:stop])
        break
    for name in names:
        escaped = re.escape(name)
        labelled = (r"(?iims)^[ \t]*(?:[-*][ \t]+)?\*{1,2}%s[^*\n]*\*{1,2}[ \t]*:?[ \t\r\n]*(.*?)"
                    r"(?=^[ \t]*(?:[-*][ \t]+)?\*{1,2}[A-Za-z][^*\n]{1,60}\*{1,2}|^#{1,6}[ \t]|\Z)" % escaped)
        row = r"(?im)^[ \t]*\|[ \t]*\*{0,2}%s[^|\n]*?\*{0,2}[ \t]*\|[ \t]*(.*)$" % escaped
        for pattern in (labelled, row):
            for m in re.finditer(pattern, block):
                cell = m.group(1) or ""
                if "|" in cell:  # this cell only, plus a wrapped continuation row
                    cell = cell[:cell.index("|")]
                    tail = block[block.index("\n", m.end()):] if "\n" in block[m.end():] else ""
                    wrapped = re.match(r"(?m)^\s*\|([^\n|]*)\|", tail)
                    if wrapped:
                        cell += " " + wrapped.group(1)
                found.append(cell.strip())
    return "\n".join(x for x in found if x).strip() or None


def test_three_to_five_candidates_and_no_title_block():  # a title naming "candidates" is not one
    assert DOC.is_file(), f"{DOC.relative_to(ROOT)} does not exist"
    assert 3 <= len(ranges()) <= 5, f"need 3-5 candidates, found {len(ranges())}"


def test_every_field_is_filled_and_the_line_is_honest():
    for rng in ranges():
        for key in REQUIRED:
            assert filled(field(rng, key)), f"{key} missing/placeholder at {rng[0]}"
        assert re.search(r"(?i)replication|extension|\bnew\b", text()[rng[0]:rng[1]]), \
            "must say: replicates, extends, or is new"


def test_lens_is_one_two_or_three_and_two_carries_the_rigor_rule():
    for rng in ranges():
        lens = field(rng, "lens")
        assert filled(lens), "lens missing"
        used = [n for n in "123" if re.search(r"(?<![\d.])%s(?![\d.])" % n, lens)]
        assert used, f"lens names none of 1, 2, 3: {lens[:60]!r}"
        if "2" in used:  # on the Lens field: the prose names beliefs and orders throughout
            assert re.search(r"(?i)bayes|classical", lens), "lens 2 names no classical Bayesian baseline"
            assert re.search(r"(?i)\bqq\b|separat|discriminat|different prediction", lens), \
                "lens 2 names no separating test"


def test_each_stage_names_what_the_brief_asks_for():
    for rng in ranges():
        for key in ("theory", "semi", "applied"):
            value = field(rng, key)
            assert filled(value), f"{key} missing"
            for pattern, why in STAGES[key]:
                assert re.search("(?i)" + pattern, value), f"{key} names no {why}: {value[:60]!r}"


def test_anomaly_map_holds_two_outcomes_and_conviction_is_five_numbered_fields():
    for rng in ranges():
        anomaly = field(rng, "anomaly")
        assert filled(anomaly), "anomaly map missing"
        bullet, items, current = re.compile(r"(?:[-*]|\d+[.)])\s+"), [], ""
        for chunk in re.split(r"(?=(?:^|[\s;,.])" + bullet.pattern + r")", anomaly):  # cells too
            piece = chunk.strip()
            if not piece:
                continue
            if re.match(r"^" + bullet.pattern, piece):
                items.append(current) if current else None
                current = bullet.sub("", piece, count=1)
            elif current:
                current += " " + piece  # a wrap of the same item, not a new one
        items.append(current) if current else None
        cells = [c.strip() for c in anomaly.split("|") if 20 < len(c.strip()) < 900 and not c.isdigit()]
        counted = items if len(items) >= 2 else cells
        assert len(counted) >= 2, f"anomaly map: {len(counted)} outcomes, need 2"
        conviction = field(rng, "conviction")
        assert filled(conviction), "conviction missing"
        for name in CONVICTION_FIELDS:
            number = re.search(r"(?i)%s[ \t*]*[:=]?[ \t]*\*{0,2}(-?\d+(?:\.\d+)?)" % name, conviction)
            assert number, f"no number for {name}"
            value = float(number.group(1))
            low, high = (0.0, 1.0) if name in PROBABILITIES else (0.0, 10.0)
            assert low <= value <= high, f"{name}={value} outside [{low}, {high}]"
            rest = re.split(r"-\s*p_pass\w*\s*:|-\s*interest\S*\s*:|\n", conviction[number.end():])[0].strip(" -\t")
            assert len(rest) >= 8 and re.search(r"(?i)[a-z]{4}", rest), \
                f"{name} has no reason after its number"
        cost = field(rng, "cost")
        assert re.search(r"(?i)flash", cost) and re.search(r"(?i)hour|\bh\b", cost), \
            f"cost must name Flash hours: {cost[:60]!r}"
