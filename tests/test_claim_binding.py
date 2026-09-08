"""Offline I1 component contracts; no application conftest or model needed."""
from dataclasses import FrozenInstanceError
import math

import pytest

from workers.claim_binding import (
    BindingError, Claim, admit_claim, bind_arguments, canonical_bytes, digest,
    load_json, verify_binding,
)


def test_full_claim_is_canonical_and_defensively_owned():
    value = {"text": "α != a", "metadata": {"seeds": [1, 2], "null": None}}
    c = admit_claim(value)
    reordered = admit_claim({"metadata": {"null": None, "seeds": [1, 2]}, "text": "α != a"})
    assert c == reordered
    saved = c.canonical
    value["metadata"]["seeds"].append(3)
    c.payload()["metadata"]["seeds"].append(9)
    assert c.canonical == saved and c.payload()["metadata"]["seeds"] == [1, 2]
    with pytest.raises(FrozenInstanceError):
        c.canonical = b"changed"


@pytest.mark.parametrize("value", [
    {"text": "claim "}, {"text": "Claim"}, {"text": "claiṁ"},
    {"text": "claim", "metadata": 1},
])
def test_text_and_metadata_changes_change_identity(value):
    assert admit_claim(value).claim_sha256 != admit_claim({"text": "claim"}).claim_sha256


@pytest.mark.parametrize("bad", [
    {"text": ""}, {"text": "  "}, {}, [], {"text": "a", 1: "bad key"},
    {"text": "a", "v": math.nan}, {"text": "a", "v": math.inf},
    {"text": "\ud800"}, {"text": "a", "v": (1, 2)},
])
def test_noncanonical_claims_fail_closed(bad):
    with pytest.raises(BindingError):
        admit_claim(bad)


@pytest.mark.parametrize("bad", [
    '{"text":"a","text":"b"}', '{"text":"a","x":NaN}',
    '{"text":"a","x":1e999}', '{"text":"\\ud800"}', '{',
])
def test_ambiguous_or_invalid_json_rejected(bad):
    with pytest.raises(BindingError):
        load_json(bad)


def test_noncanonical_or_forged_claim_bytes_rejected():
    with pytest.raises(BindingError, match="not canonical"):
        Claim(b'{ "text": "a" }', digest(b'{ "text": "a" }'))
    with pytest.raises(BindingError, match="mismatch"):
        Claim(b'{"text":"a"}', "sha256:" + "0" * 64)


def test_revision_preserves_prior_and_rebinds_stale_model_arguments():
    c1 = admit_claim({"text": "H1", "mechanism": "old"})
    c2 = admit_claim({"text": "H2", "mechanism": "new"}, supersedes=c1)
    c3 = admit_claim({"text": "H3", "mechanism": "newer"}, supersedes=c2)
    assert c1.payload()["text"] == "H1"
    assert c2.supersedes == c1.claim_sha256 and c3.supersedes == c2.claim_sha256
    old = {"hypothesis_text": "H1", "iteration_id": "old", "attempt_id": "old", "k": 10}
    args = bind_arguments(c3, old, attempt_id="a3", iteration_id="i3")
    verify_binding(c3, args, attempt_id="a3", iteration_id="i3")
    assert args["hypothesis_text"] == "H3" and args["k"] == 10
    assert old["hypothesis_text"] == "H1"
    with pytest.raises(BindingError):
        verify_binding(c2, args, attempt_id="a3", iteration_id="i3")
    with pytest.raises(BindingError, match="must change"):
        admit_claim(c3.payload(), supersedes=c3)


@pytest.mark.parametrize("field,value", [
    ("attempt_id", "other"), ("iteration_id", "other"),
    ("input_claim_sha256", None), ("input_claim_sha256", "garbage"),
    ("input_claim", {"text": "other"}), ("hypothesis_text", "other"),
])
def test_dispatch_and_commit_binding_refuse_each_wrong_field(field, value):
    c = admit_claim({"text": "H"})
    args = bind_arguments(c, {}, attempt_id="a", iteration_id="i")
    args[field] = value
    with pytest.raises(BindingError):
        verify_binding(c, args, attempt_id="a", iteration_id="i")


def test_recursive_mutable_input_fails_without_hanging():
    value = {"text": "claim"}
    value["cycle"] = value
    with pytest.raises(BindingError):
        canonical_bytes(value)
