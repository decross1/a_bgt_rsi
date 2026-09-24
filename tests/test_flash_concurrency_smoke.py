"""Concurrency smoke tool: dry run and a fake local SSE server; never port 30080."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools import flash_concurrency_smoke as smoke

REPO_DEPLOYMENT = Path(__file__).resolve().parents[1] / "config/model_deployment.json"


def _deployment(tmp_path, running) -> str:
    manifest = json.loads(REPO_DEPLOYMENT.read_text())
    if running is None:
        manifest.pop("max_running_requests")
    else:
        manifest["max_running_requests"] = running
    path = tmp_path / "model_deployment.json"
    path.write_text(json.dumps(manifest))
    return str(path)


def test_dry_run_prints_plan_without_network(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_opener", lambda: pytest.fail("dry run opened a connection"))
    assert smoke.main(["--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    configured = json.loads(REPO_DEPLOYMENT.read_text())["max_running_requests"]
    assert plan["dry_run"] is True and plan["configured_max_running_requests"] == configured
    assert len(plan["requests"]) == configured == 4
    assert plan["requests"][0]["POST"] == "http://127.0.0.1:30080/v1/chat/completions"
    assert "effective_max_running_requests_per_dp" in plan["pass_rule"]


@pytest.mark.parametrize("running", [1, 2, 4])
def test_dry_run_sends_the_configured_number_of_distinct_requests(tmp_path, capsys, running):
    assert smoke.main(["--dry-run", "--deployment", _deployment(tmp_path, running)]) == 0
    plan = json.loads(capsys.readouterr().out)
    prompts = [r["body"]["messages"][0]["content"] for r in plan["requests"]]
    assert len(prompts) == len(set(prompts)) == running
    assert f"== {running}," in plan["pass_rule"]


@pytest.mark.parametrize("running", [3, 8, None])
def test_rejects_a_deployment_without_a_reviewed_count(tmp_path, capsys, running):
    assert smoke.main(["--dry-run", "--deployment", _deployment(tmp_path, running)]) == 2
    assert "max_running_requests" in json.loads(capsys.readouterr().out)["error"]


def test_rejects_non_loopback_base():
    with pytest.raises(SystemExit):
        smoke.main(["--dry-run", "--base", "http://example.invalid:30080"])


def test_overlap_rule():
    row = dict(error=None)
    both = [dict(row, first_token_s=0.2, end_s=2.0), dict(row, first_token_s=0.3, end_s=1.5)]
    assert smoke.overlap(both) == {"overlapped": True, "overlap_s": 1.2,
                                   "overlapping_pairs": 1, "pairs": 1}
    serial = [dict(row, first_token_s=0.2, end_s=1.0), dict(row, first_token_s=1.1, end_s=2.0)]
    assert smoke.overlap(serial)["overlapped"] is False
    # Four streams: three overlap, the fourth starts after the first ended.
    four = [dict(row, first_token_s=0.1, end_s=1.0), dict(row, first_token_s=0.2, end_s=2.0),
            dict(row, first_token_s=0.3, end_s=2.0), dict(row, first_token_s=1.5, end_s=3.0)]
    result = smoke.overlap(four)
    assert result["overlapped"] is False and result["pairs"] == 6
    assert result["overlapping_pairs"] == 5
    assert smoke.overlap(four[:3])["overlapped"] is True
    assert smoke.overlap(four[:1])["overlapped"] is None


def test_timing_reports_per_stream_rates():
    row = dict(error=None, start_s=0.0, first_token_s=0.5, end_s=2.5, chunks=10,
               usage={"completion_tokens": 50})
    assert smoke.timing(row) == {"ttft_s": 0.5, "decode_s": 2.0, "chunks_per_s": 5.0,
                                 "completion_tokens": 50, "completion_tokens_per_s": 20.0}
    assert smoke.timing(dict(row, error="boom"))["ttft_s"] is None


def _server(running_requests, serialize, effective=None, tokens=262144):
    gate = threading.Lock()
    lanes = threading.BoundedSemaphore(effective or running_requests)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            info = {"max_running_requests": running_requests,
                    "max_total_num_tokens": tokens,
                    "internal_states": [{"effective_max_running_requests_per_dp":
                                         effective or running_requests}]}
            body = json.dumps(info).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            lock = gate if serialize else lanes
            lock.acquire()
            try:
                for word in ("one", "two", "three"):
                    event = {"choices": [{"delta": {"content": word}}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.1)
                usage = {"choices": [], "usage": {"completion_tokens": 3}}
                self.wfile.write(f"data: {json.dumps(usage)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            finally:
                lock.release()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize(
    ("configured", "served", "serialize", "effective", "tokens", "code"),
    [
        (4, 4, False, None, 262144, 0),     # C4 as configured, all four decode together
        (2, 2, False, None, 262144, 0),     # C2 rollback pin
        (1, 1, False, None, 262144, 0),     # C1 rollback pin: nothing to overlap
        (4, 4, False, 3, 262144, 1),        # requested 4, silently capped to 3 by the mamba pool
        (4, 2, False, None, 262144, 1),     # server still on C2 while config says C4
        (4, 4, True, None, 262144, 1),      # reports C4 but serializes the streams
        (4, 4, False, None, 131072, 1),     # shrunken token pool
    ],
)
def test_live_path_against_fake_server(tmp_path, capsys, configured, served, serialize,
                                       effective, tokens, code):
    server = _server(served, serialize, effective, tokens)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        argv = ["--base", base, "--timeout", "10",
                "--deployment", _deployment(tmp_path, configured)]
        assert smoke.main(argv) == code
    finally:
        server.shutdown()
    report = json.loads(capsys.readouterr().out)
    assert report["configured_max_running_requests"] == configured
    assert report["max_running_requests"] == served
    assert report["effective_max_running_requests_per_dp"] == (effective or served)
    assert len(report["requests"]) == configured
    assert [r["stream"] for r in report["requests"]] == list(range(configured))
    assert all(r["chunks"] == 3 and r["error"] is None and r["completion_tokens"] == 3
               and r["ttft_s"] is not None for r in report["requests"])
    lanes = effective or served
    if configured == 1:
        assert report["overlapped"] is None
    else:
        # The fake server enforces its lane count, so fewer lanes than streams
        # (a capped or stale server) cannot decode all of them at once.
        assert report["overlapped"] is (not serialize and lanes >= configured)
    assert report["server_checks"]["effective_max_running_requests_per_dp"]["ok"] is (
        lanes == configured)
