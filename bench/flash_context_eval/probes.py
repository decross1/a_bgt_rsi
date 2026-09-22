"""Deterministic long-context probes for the Flash context-capacity eval.

RULER-style sanity tasks (multi-key needle retrieval, variable tracking) plus a
streaming client that records time to first token and decode rate. Prompts are
seeded and synthetic; they check recall at a realized length, not usefulness.
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request

ENDPOINT = "http://127.0.0.1:30080/v1/chat/completions"
MODEL = "nvidia/Qwen3.8-Flash-Next-NVFP4"
_WORDS = (
    "river stone lantern orchard meadow harbor copper willow canyon ember "
    "signal quarry marble thistle beacon glacier saddle compass ledger falcon "
    "harvest pillar ribbon tundra velvet anchor bramble cinder drift fable"
).split()


def filler(rng: random.Random, words: int) -> list[str]:
    """Sentences of plain words; ten words per sentence."""
    out = []
    for start in range(0, words, 10):
        sentence = [rng.choice(_WORDS) for _ in range(min(10, words - start))]
        out.append(" ".join(sentence).capitalize() + ".")
    return out


def _spread(sentences: list[str], inserts: list[str], rng: random.Random) -> str:
    slots = sorted(rng.sample(range(len(sentences) + 1), len(inserts)))
    for offset, (slot, text) in enumerate(zip(slots, inserts)):
        sentences.insert(slot + offset, text)
    return " ".join(sentences)


def needle_prompt(words: int, seed: int, needles: int = 8, asked: int = 4) -> tuple[str, dict]:
    rng = random.Random(seed)
    keys = [f"key-{rng.randrange(10**5, 10**6)}" for _ in range(needles)]
    values = {k: str(rng.randrange(10**6, 10**7)) for k in keys}
    body = _spread(filler(rng, words), [f"The special magic number for {k} is {values[k]}." for k in keys], rng)
    chosen = rng.sample(keys, asked)
    question = ("Answer with only a JSON object mapping each key to its special magic number, for keys: "
                + ", ".join(chosen) + ".")
    return body + "\n\n" + question, {k: values[k] for k in chosen}


def vartrack_prompt(words: int, seed: int, hops: int = 4) -> tuple[str, list[str]]:
    rng = random.Random(seed)
    target, decoy = str(rng.randrange(10**4, 10**5)), str(rng.randrange(10**4, 10**5))
    lines, chain = [], []
    for value, name in ((target, "Q"), (decoy, "Z")):
        prev = f"{name}{rng.randrange(100, 999)}"
        lines.append(f"VAR {prev} = {value}.")
        names = [prev]
        for _ in range(hops):
            nxt = f"{name}{rng.randrange(100, 999)}"
            while nxt in names:
                nxt = f"{name}{rng.randrange(100, 999)}"
            lines.append(f"VAR {nxt} = {prev}.")
            names.append(nxt)
            prev = nxt
        if value == target:
            chain = names
    body = _spread(filler(rng, words), lines, rng)
    question = (f"Find every variable that is assigned the value {target}, directly or through other "
                "variables. Answer with only a JSON list of variable names.")
    return body + "\n\n" + question, sorted(chain)


def score_needles(text: str, expected: dict) -> float:
    hits = sum(1 for key, value in expected.items()
               if re.search(re.escape(key) + r'"?\s*[:=]\s*"?' + value + r"\b", text))
    return hits / len(expected)


def score_vartrack(text: str, expected: list[str]) -> dict:
    found = set(re.findall(r"\b[QZ]\d{3}\b", text))
    want = set(expected)
    recall = len(found & want) / len(want)
    precision = len(found & want) / len(found) if found else 0.0
    return {"recall": recall, "precision": precision, "exact": found == want}


def stream_chat(prompt: str, max_tokens: int, timeout: float = 900.0) -> dict:
    """One streamed, thinking-off, greedy request; never retried here."""
    payload = {
        "model": MODEL, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0, "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    start = time.monotonic()
    first = None
    text, usage, finish = [], {}, None
    try:
        with opener.open(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[5:])
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if piece and first is None:
                        first = time.monotonic()
                    text.append(piece)
                    finish = choice.get("finish_reason") or finish
            status = response.status
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "error": exc.read(2000).decode("utf-8", "replace"),
                "total_s": time.monotonic() - start}
    end = time.monotonic()
    completion = int(usage.get("completion_tokens") or 0)
    decode_s = end - first if first is not None else None
    return {
        "status": status, "finish_reason": finish, "text": "".join(text),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0), "completion_tokens": completion,
        "ttft_s": (first - start) if first is not None else None, "total_s": end - start,
        "decode_tok_s": (completion - 1) / decode_s if decode_s and completion > 1 else None,
    }
