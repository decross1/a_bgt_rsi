"""Concurrency smoke tool: dry run and a fake local SSE server; never port 30080."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools import flash_concurrency_smoke as smoke


def test_dry_run_prints_plan_without_network(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_opener", lambda: pytest.fail("dry run opened a connection"))
    assert smoke.main(["--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True and len(plan["requests"]) == 2
    assert plan["requests"][0]["POST"] == "http://127.0.0.1:30080/v1/chat/completions"


def test_rejects_non_loopback_base():
    with pytest.raises(SystemExit):
        smoke.main(["--dry-run", "--base", "http://example.invalid:30080"])


def test_overlap_rule():
    row = dict(error=None)
    both = [dict(row, first_token_s=0.2, end_s=2.0), dict(row, first_token_s=0.3, end_s=1.5)]
    assert smoke.overlap(both) == {"overlapped": True, "overlap_s": 1.2}
    serial = [dict(row, first_token_s=0.2, end_s=1.0), dict(row, first_token_s=1.1, end_s=2.0)]
    assert smoke.overlap(serial)["overlapped"] is False


def _server(running_requests, serialize):
    gate = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps({"max_running_requests": running_requests,
                               "max_total_num_tokens": 262144}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if serialize:
                gate.acquire()
            try:
                for word in ("one", "two", "three"):
                    event = {"choices": [{"delta": {"content": word}}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.1)
                self.wfile.write(b"data: [DONE]\n\n")
            finally:
                if serialize:
                    gate.release()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize(("running", "serialize", "code"), [(2, False, 0), (1, True, 1)])
def test_live_path_against_fake_server(capsys, running, serialize, code):
    server = _server(running, serialize)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert smoke.main(["--base", base, "--timeout", "10"]) == code
    finally:
        server.shutdown()
    report = json.loads(capsys.readouterr().out)
    assert report["max_running_requests"] == running
    assert report["overlapped"] is (code == 0)
    assert all(r["chunks"] == 3 and r["error"] is None for r in report["requests"])
