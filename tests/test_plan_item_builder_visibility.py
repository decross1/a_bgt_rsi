"""Acceptance for plan 2026-09-24 d5 (G7.1): the plan-item contract must state, where an
author reads it, what the lane builder can see.

Why (meta-oracle review claude-e347ce59ca643116 seq 165, material finding 1, fix target
skill): "The plan-item skill should state that the lane worktree = checkout HEAD + test,
and the builder sees objective, title, test, last output and the current contents of
writable paths, nothing else." I posted plan item seq 160 telling its builder to copy 19
paper titles from a file that exists nowhere, because I had no written statement of what
the builder is handed; the contract in docs/ORACLE_NARA_MAILBOX.md described the sandbox
but never the builder's inputs.

The rule is checked where an author reads it, not in code, because the author-facing
document is the only place the mistake can be prevented: admission() can refuse an
unreadable `input_paths` entry (main does, at nara_lane._input_visibility) but nothing in
code stops an objective from pointing at a path that is merely inside the fence.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ORACLE_NARA_MAILBOX.md"

# The builder call, as built by nara_lane.builder(): these are the only inputs, so the
# contract must name exactly them. Verified against orchestrator/nara_lane.py on main.
BUILDER_INPUTS = {
    "title": r"\btitle\b",
    "objective": r"\bobjective\b",
    "test": r"acceptance test|test file|test'?s (?:bytes|content)",
    "last_output": r"last (?:test )?output|test output (?:tail|so far)",
    # a document wraps lines, so a space must match a newline too: [ \n]+, not a space
    "writable_contents": r"current contents[ \n]+of[ \n]+(?:the[ \n]+)?writable paths"
                         r"|contents[ \n]+of[ \n]+(?:the[ \n]+)?writable paths",
    "nothing_else": r"nothing else|and nothing more|nothing beyond",
}


def text():
    return DOC.read_text()


def authoring_section():
    """The lines under '## Writing a plan item (Oracle)' up to the next '## ' heading."""
    body = text()
    start = body.index("## Writing a plan item (Oracle)")
    rest = body[start + len("## Writing a plan item (Oracle)"):]
    nxt = rest.find("\n## ")
    return rest[: nxt if nxt >= 0 else len(rest)]


def test_the_contract_has_a_builder_visibility_statement():
    section = authoring_section()
    assert re.search(r"(?im)^#{2,4}.*builder (?:can see|sees|'s view|is given)", section), (
        "the plan-item section names no builder-visibility statement; an author has "
        "nothing to read about what the builder is handed"
    )


def test_it_names_every_builder_input_and_that_there_are_no_others():
    section = authoring_section()
    for name, pattern in BUILDER_INPUTS.items():
        assert re.search(pattern, section, re.I), f"builder visibility omits: {name}"


def test_it_states_the_worktree_is_head_plus_the_test_so_inputs_cannot_be_files():
    section = authoring_section()
    assert (re.search(r"(?i)head", section) and re.search(r"(?i)acceptance test", section)
            and re.search(r"(?i)checkout|base", section)), "no worktree-composition statement"
    # The operative rule: an input cannot be handed over by naming a path. The author
    # must put the content inline in the objective, and must be told a named path is not
    # readable. Both checks are case-insensitive by flag, not by inline (?i) alternation.
    assert re.search(r"(?i)inline", section), "objective never says inputs go inline"
    assert re.search(r"(?i)(input|content|prior|reading list)[^\n]{0,200}(inline|objective)",
                     section) or re.search(
                     r"(?i)(objective|inline)[^\n]{0,200}(input|content|prior|reading list)",
                     section), (
        "does not tell the author to put input content inline in the objective")
    refused = (r"(?i)(cannot|can not|can't|never|not possible|refus|reject|hold)"
               r"[^\n]{0,200}(path|file|input)")
    refused_b = r"(?i)(input|path)[^\n]{0,200}(cannot|can not|can't|never|refus|reject|held)"
    assert re.search(refused, section) or re.search(refused_b, section), \
        "does not say a named input path cannot be read by the builder"


def test_it_says_a_shape_test_is_not_a_citation_check():
    # Review seq 165 amendment 2: "state in the notes that the shape test is not a
    # citation check." Stated in the contract, since the author writes the test.
    assert re.search(r"(?i)(shape|format)[^\n]{0,60}not (a )?citation check|"
                     r"not a citation check", text()), (
        "the contract never says a shape/format test is not a citation check"
    )
