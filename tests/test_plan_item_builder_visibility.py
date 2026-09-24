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
document is the only place the mistake can be prevented: the lane can refuse an unreadable
`input_paths` entry at admission only once oracle/2026-09-24-lane-input-visibility merges
(that branch defines nara_lane._input_visibility; main 025537c and the lane base a958f91
do not), and nothing in code stops an objective from pointing at a path that is merely
inside the fence.

Landing order (review claude-97db65cb9c72d6ce seq 206, amendments 1-2): this document
describes the MERGED behaviour, so oracle/2026-09-24-lane-input-visibility lands first and
d5 changes only the prose. The three tests below are what keeps the two in step: they
require the merged sentences, and one of them forbids the absolute claim that no file can
ever be handed over by path.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ORACLE_NARA_MAILBOX.md"

# The builder call, as built by nara_lane.builder() AFTER oracle/2026-09-24-lane-input-visibility
# merges: the six base inputs, plus, for each declared `input_paths` entry, its visibility
# verdict and, if PRESENT, its bytes. Verified against builder() on that branch (ab26997
# sets prompt["input_visibility"] and prompt["input_contents"]).
BUILDER_INPUTS = {
    "title": r"\btitle\b",
    "objective": r"\bobjective\b",
    "test": r"acceptance test|test file|test'?s (?:bytes|content)",
    "last_output": r"last (?:test )?output|test output (?:tail|so far)",
    # a document wraps lines, so a space must match a newline too: [ \n]+, not a space
    "writable_contents": r"current contents[ \n]+of[ \n]+(?:the[ \n]+)?writable paths"
                         r"|contents[ \n]+of[ \n]+(?:the[ \n]+)?writable paths",
    # "nothing else" is now false for a declared input, so the closed-world claim is
    # stated as: these inputs, and nothing beyond them.
    "nothing_else": r"nothing else|and nothing more|nothing beyond",
    # seq 206 amendment 2: the two new prompt keys must be named among the inputs.
    "input_visibility": r"input_visibility",
    "input_contents": r"input_contents",
    "input_paths_key": r"`input_paths`",
    "writable_paths_key": r"`writable_paths`|writable paths",
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
    # The operative rule, as review seq 206 amendment 2 states it: content that is not
    # committed at the lane base has to go inline in the objective, and a path mentioned
    # only in the objective's prose is never sent. The author must be told both.
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


def test_it_describes_the_merged_input_rules_and_never_the_absolute_refusal():
    """Review seq 206, amendments 1-2. The doc must describe what the merged lane does:
    a regular file tracked at the lane base HEAD is PRESENT and its bytes are sent; an
    untracked entry is held as 'not readable by the builder'; an entry outside the fence
    is held as 'outside the lane fence'. And it must not claim the builder gets 'nothing
    else' than the six base inputs, because that is false the moment an input is PRESENT."""
    section = authoring_section()
    assert re.search(r"(?i)input_contents[^\n]{0,200}(cap|MAX_FILE_BYTES|limit)", section) \
        or re.search(r"(?i)(cap|limit)[^\n]{0,120}(input_contents|bytes)", section), \
        "the byte cap on shipped input contents is not stated"
    for verdict in ("not readable by the builder", "outside the lane fence"):
        assert verdict in section, f"the contract omits the admission verdict: {verdict!r}"
    # The rule that replaces the old absolute: prose-only paths are never sent.
    assert re.search(r"(?i)(path|name)[^\n]{0,160}prose[^\n]{0,120}"
                     r"(never|not)[^\n]{0,60}(sent|shipped|hand)"
                     r"|(never|not)[^\n]{0,60}(sent|shipped)[^\n]{0,120}prose", section), \
        "does not state that a path named only in the objective's prose is never sent"
    # And the forgery this branch exists to stop: the doc must not say the refusal of an
    # unreadable input is live on main, because it is not until the lane branch merges.
    assert not re.search(r"(?i)main (?:already )?(?:has|defines|carries)[^\n]{0,80}_input_visibility",
                         text()), "claims _input_visibility exists on main"


def test_it_says_a_shape_test_is_not_a_citation_check():
    # Review seq 165 amendment 2: "state in the notes that the shape test is not a
    # citation check." Stated in the contract, since the author writes the test.
    assert re.search(r"(?i)(shape|format)[^\n]{0,60}not (a )?citation check|"
                     r"not a citation check", text()), (
        "the contract never says a shape/format test is not a citation check"
    )
