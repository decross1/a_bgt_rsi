"""Trusted single-attempt Qwen generator/committer for an admitted packet.

Response text stays data on the host. One admitted regular file is written and
committed; the dispatcher and external parent verifier decide acceptance.
No endpoint, path, shell, test or policy can be supplied by the model.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
import signal
import stat
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workers.claim_binding import load_json
from workers.packet_checks import verify_red
from tools.contained_python import verify_runtime


MODEL = "qwen3.8-27b-nvfp4-mtp"
WORKER = "workers/research_progress.py"


def candidate_bytes(response: dict) -> bytes:
    if type(response) is not dict or response.get("model") != MODEL:
        raise ValueError("returned model differs from admitted declaration")
    if type(response.get("choices")) is not list or len(response["choices"]) != 1:
        raise ValueError("expected one completion")
    choice = response["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("incomplete completion")
    usage = response.get("usage", {})
    if type(usage.get("completion_tokens")) is not int or not 0 < usage["completion_tokens"] <= 4096:
        raise ValueError("invalid completion token accounting")
    if type(usage.get("prompt_tokens")) is not int or usage["prompt_tokens"] < 0 \
            or usage["prompt_tokens"] + usage["completion_tokens"] > 16384:
        raise ValueError("invalid context accounting")
    content = choice.get("message", {}).get("content")
    if type(content) is not str:
        raise ValueError("completion text missing")
    obj = load_json(content)
    if type(obj) is not dict or set(obj) != {"path", "content"} \
            or obj["path"] != WORKER or type(obj["content"]) is not str:
        raise ValueError("expected exact one-file response")
    source = obj["content"].encode("utf-8", errors="strict")
    if not 0 < len(source) <= 32768:
        raise ValueError("candidate byte budget exceeded")
    ast.parse(source, filename=WORKER)
    return source


def write_candidate(target, source, baseline=None):
    """Write exact model bytes; an existing correction needs its frozen digest.

    The caller owns the checkout ancestry/lifecycle; this is not OS isolation.
    """
    flags = os.O_NOFOLLOW | (os.O_RDWR if baseline else os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    fd = os.open(target, flags, 0o644)
    with os.fdopen(fd, "r+b" if baseline else "wb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("candidate must be a single-link regular file")
        if baseline:
            if hashlib.sha256(handle.read()).hexdigest() != baseline:
                raise ValueError("existing candidate differs from frozen correction base")
            handle.seek(0)
            handle.truncate()
        handle.write(source)
        handle.flush()
        os.fsync(handle.fileno())


def _git(*argv):
    return subprocess.check_output(["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
                                   "-c", "core.fsmonitor=false", *argv],
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                                        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}, timeout=15)


def _deadline(signum, frame):
    raise TimeoutError("finite model/commit attempt deadline reached")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest_raw = args.manifest.read_bytes()
    manifest = load_json(manifest_raw)
    evidence = Path(manifest["evidence_dir"])
    for path, wanted in manifest["trusted_files"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != wanted:
            raise RuntimeError("trusted controller/profile bytes changed")
    verify_runtime(manifest.get("approved_runtime"))
    if datetime.now(timezone.utc) >= datetime.fromisoformat(manifest["deadline"]):
        raise RuntimeError("admitted foreground deadline elapsed")
    if manifest["worker_path"] != WORKER or manifest["model"] != MODEL:
        raise RuntimeError("unsupported admission")
    if _git("rev-parse", "HEAD").decode().strip() != manifest["base_sha"] \
            or _git("status", "--porcelain") \
            or _git("branch", "--show-current").decode().strip() != manifest["branch"]:
        raise RuntimeError("builder did not start on exact clean admitted branch/base")
    target = Path(WORKER)
    baseline = manifest.get("worker_base_sha256")
    if (target.exists() and not baseline) or target.is_symlink() or target.parent.is_symlink() \
            or target.parent.resolve() != Path.cwd().resolve() / "workers":
        raise RuntimeError("regular path precondition failed")
    if baseline and (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != baseline):
        raise RuntimeError("correction base differs from admitted digest")
    expected_red = load_json(Path(manifest["red_expectation_path"]).read_bytes())
    receipts = sorted(evidence.glob("acceptance-*/receipt.json"))
    if len(receipts) != 2:
        raise RuntimeError("expected independent preflight and dispatcher red receipts")
    for path in receipts:
        verify_red(load_json(path.read_bytes()), expected_red)
    record = {"started_at": datetime.now(timezone.utc).isoformat(),
              "request_id": str(uuid.uuid4()), "parent_request_id": manifest["nara_request_id"],
              "attempt_id": manifest["attempt_id"], "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
              "model": MODEL, "endpoint": "http://127.0.0.1:8001/v1/chat/completions",
              "max_tokens": 4096, "timeout_seconds": 170, "retries": 0,
              "before_sha": manifest["base_sha"], "status": "started"}
    with (evidence / "model-start.json").open("x") as handle:
        json.dump(record, handle, indent=2)
    prompt = manifest["api"] + "\nNara-issued objective: " + manifest["nara_objective"]
    prompt += "\nParent repair context: " + manifest.get("repair_context", "none")
    body = json.dumps({"model": MODEL, "messages": [
        {"role": "system", "content": 'You implement one pure Python file. Return only a JSON object with exactly "path" and "content". No markdown or shell. Write only workers/research_progress.py.'},
        {"role": "user", "content": prompt}], "temperature": 0.2,
        "top_p": 0.9, "seed": 0, "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False}}, ensure_ascii=True).encode()
    if len(body) > 24000:
        raise RuntimeError("prompt byte budget exceeded")
    (evidence / "qwen-request.json").write_bytes(body)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, _deadline)
    signal.setitimer(signal.ITIMER_REAL, 170)
    connection = http.client.HTTPConnection("127.0.0.1", 8001, timeout=170)
    try:
        connection.request("POST", "/v1/chat/completions", body=body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(262145)
        (evidence / "qwen-response.raw").write_bytes(raw)
        if response.status != 200 or len(raw) > 262144:
            raise RuntimeError("model HTTP status/response byte budget failure")
        decoded = load_json(raw.decode("utf-8", errors="strict"))
        record.update(provider_request_id=decoded.get("id"), usage=decoded.get("usage"),
                      request_sha256=hashlib.sha256(body).hexdigest(),
                      response_sha256=hashlib.sha256(raw).hexdigest())
        source = candidate_bytes(decoded)
        record.update(provider_request_id=decoded.get("id"), usage=decoded["usage"],
                      request_sha256=hashlib.sha256(body).hexdigest(),
                      response_sha256=hashlib.sha256(raw).hexdigest(),
                      source_sha256=hashlib.sha256(source).hexdigest(),
                      completion_sha256=hashlib.sha256(decoded["choices"][0]["message"]["content"].encode()).hexdigest())
        (evidence / "qwen-candidate.py").write_bytes(source)
        write_candidate(target, source, baseline)
        _git("add", "--", WORKER)
        if _git("diff", "--cached", "--name-only").decode().splitlines() != [WORKER] \
                or _git("show", ":" + WORKER) != source:
            raise RuntimeError("staged source differs from exact Qwen bytes")
        _git("-c", "user.name=qwen-builder (bounded adapter)",
             "-c", "user.email=qwen-builder@localhost", "-c", "commit.gpgsign=false",
             "commit", "-m", "feat: summarize research progress from explicit evidence dispositions")
        after = _git("rev-parse", "HEAD").decode().strip()
        if _git("rev-list", "--parents", "-n", "1", after).decode().split() != [after, manifest["base_sha"]] \
                or _git("status", "--porcelain") or _git("show", after + ":" + WORKER) != source:
            raise RuntimeError("candidate commit failed exact parent/source/clean checks")
        record.update(status="candidate_committed", after_sha=after, builder_exit_code=0)
    except BaseException as error:
        record.update(status="failed", error=type(error).__name__ + ": " + str(error), builder_exit_code=1)
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        connection.close()
        record["duration_seconds"] = time.monotonic() - started
        with (evidence / "builder-receipt.json").open("x") as handle:
            json.dump(record, handle, indent=2); handle.write("\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
