import json
import os
from datetime import datetime, timedelta, timezone

from backend.daily_ops import _agents
from backend.daily_ops_agents import _tail, list_processes, observe

NOW = datetime(2026, 9, 23, 1, 0, tzinfo=timezone.utc)
SERVICE = {"label": "Nara research runner", "status": "online", "detail": "Nara service is active.",
           "observed_at": "2026-09-23T01:00:00Z", "source": "nara-daemon.service state"}


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _jsonl(path, rows, tail=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + tail)


def _mail(seq, actor, kind, body, *, to="all", reply=None, minutes=0):
    return {"seq": seq, "ts": _iso(NOW - timedelta(minutes=minutes)), "actor": actor, "to": to,
            "kind": kind, "in_reply_to": reply, "body": body, "msg_id": f"{actor}-{seq:016x}"}


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "logs" / "oracle_daily").mkdir(parents=True)
    (repo / "logs" / "meta_oracle").mkdir(parents=True)
    plans = repo / "run_state" / "daily_plans"
    plans.mkdir(parents=True)
    for name, ids in (("2026-09-22-r3.json", ["x"]), ("2026-09-23.json", ["a"]),
                      ("2026-09-23-r2.json", ["d1", "d2"]), ("2026-09-23-close-body.json", ["z"])):
        (plans / name).write_text(json.dumps({"items": [
            {"id": i, "goal": "G7.1", "owner": "oracle", "title": f"Build {i}\nnow"} for i in ids]}))
    return repo


def _observe(repo, processes=(), sessions=None, service=SERVICE):
    return observe(repo, now=NOW, nara_service=dict(service), processes=list(processes),
                   pi_sessions=sessions or repo / "no-sessions")


def test_running_oracle_phase_is_working_with_plan_and_latest_mailbox_row(tmp_path):
    repo = _repo(tmp_path)
    started = int((NOW - timedelta(minutes=30)).timestamp())
    (repo / "logs" / "oracle_daily" / f"2026-09-23-work-{started}.log").write_text("")
    (repo / "logs" / "oracle_daily" / f"2026-09-23-plan-{started + 60}.log").write_text("")
    _jsonl(repo / "run_state" / "oracle_nara_mailbox.jsonl", [
        _mail(1, "oracle", "note", {"title": "PLAN READY", "text": "x"}, minutes=40),
        _mail(2, "claude", "review", {"verdict": "amend", "summary": "Fix d1."},
              reply="oracle-0000000000000001", minutes=20),
        _mail(3, "oracle", "note", {"title": "READY FOR REVIEW: d1"}, minutes=5),
    ])
    processes = [{"pid": 10, "ppid": 1, "tty": 0, "cwd": "/", "argv": [
        "bash", "/opt/oracle_system/scripts/oracle-daily", "work"]}]

    cards = _observe(repo, processes)

    oracle = cards["oracle"]
    assert oracle["status"] == "working"
    assert oracle["since"] == _iso(NOW - timedelta(minutes=30))
    assert "work for 2026-09-23" in oracle["detail"] and "2026-09-23-r2.json: 2 item(s)" in oracle["detail"]
    assert [item["id"] for item in oracle["items"]] == ["d1", "d2"]
    assert oracle["items"][0]["title"] == "Build d1 now"
    assert oracle["activity"] == "#3 note: READY FOR REVIEW: d1"
    assert oracle["activity_at"] == _iso(NOW - timedelta(minutes=5))
    meta = cards["meta_oracle"]
    assert meta["activity"] == "#2 review amend re PLAN READY: Fix d1."
    assert meta["status"] == "unknown"
    assert _agents(cards)


def test_bash_c_text_is_not_a_live_run_and_run_log_decides_idle_or_failed(tmp_path):
    repo = _repo(tmp_path)
    _jsonl(repo / "run_state" / "week1.run.jsonl", [
        {"timestamp": _iso(NOW - timedelta(hours=2)), "task_id": "oracle-daily:work:2026-09-23",
         "status": "completed"},
        {"timestamp": _iso(NOW - timedelta(hours=1)), "task_id": "oracle-daily:close:2026-09-23",
         "status": "failed"},
        {"timestamp": _iso(NOW - timedelta(minutes=10)), "task_id": "meta-oracle:code:2026-09-23",
         "status": "completed"},
    ], tail='{"timestamp": "partial')
    wrapper = [{"pid": 5, "ppid": 1, "tty": 0, "cwd": "/",
                "argv": ["/bin/bash", "-c", "bash scripts/oracle-daily work"]}]

    cards = _observe(repo, wrapper)

    assert cards["oracle"]["status"] == "failed"
    assert cards["oracle"]["since"] == _iso(NOW - timedelta(hours=1))
    assert "close for 2026-09-23 ended failed" in cards["oracle"]["detail"]
    assert cards["meta_oracle"]["status"] == "idle"
    assert "code for 2026-09-23" in cards["meta_oracle"]["detail"]


def test_meta_oracle_live_run_is_working(tmp_path):
    repo = _repo(tmp_path)
    started = int((NOW - timedelta(minutes=2)).timestamp())
    (repo / "logs" / "meta_oracle" / f"2026-09-23-code-{started}.log").write_text("")
    cards = _observe(repo, [{"pid": 7, "ppid": 1, "tty": 0, "cwd": "/",
                             "argv": ["bash", "tools/meta_oracle_run.sh", "code"]}])
    assert cards["meta_oracle"]["status"] == "working"
    assert cards["meta_oracle"]["since"] == _iso(NOW - timedelta(minutes=2))


def test_pi_client_ignores_headless_runs_and_uses_its_cwd_sessions(tmp_path):
    repo = _repo(tmp_path)
    sessions = tmp_path / "sessions"
    folder = sessions / "--home-me-oracle_system--"
    folder.mkdir(parents=True)
    session = folder / "s.jsonl"
    session.write_text("{}\n")
    fresh = (NOW - timedelta(minutes=3)).timestamp()
    os.utime(session, (fresh, fresh))
    headless = [
        {"pid": 20, "ppid": 1, "tty": 0, "cwd": "/home/me/oracle_system", "argv": ["pi"]},
        {"pid": 21, "ppid": 30, "tty": 34817, "cwd": "/home/me/oracle_system", "argv": ["pi"]},
        {"pid": 30, "ppid": 1, "tty": 0, "cwd": "/", "argv": ["bash", "/x/scripts/oracle-daily", "work"]},
        {"pid": 22, "ppid": 1, "tty": 34817, "cwd": "/home/me/oracle_system", "argv": ["pi", "-p", "x"]},
    ]
    assert _observe(repo, headless, sessions)["pi_client"]["status"] == "offline"

    interactive = headless + [{"pid": 40, "ppid": 1, "tty": 34817,
                               "cwd": "/home/me/oracle_system", "argv": ["pi"]}]
    card = _observe(repo, interactive, sessions)["pi_client"]
    assert card["status"] == "active" and card["since"] == _iso(NOW - timedelta(minutes=3))

    old = (NOW - timedelta(minutes=45)).timestamp()
    os.utime(session, (old, old))
    assert _observe(repo, interactive, sessions)["pi_client"]["status"] == "idle"


def test_nara_claimed_lane_item_wins_over_cycle_topic(tmp_path):
    repo = _repo(tmp_path)
    (repo / "logs" / "nara-daemon.log").write_text(
        f"[nara-daemon] {_iso(NOW - timedelta(minutes=9))} wake=event:idea_ledger "
        "work=yes:agenda:1 action=cycle:executed\n")
    _jsonl(repo / "run_state" / "coordinator_cycles.jsonl", [
        {"timestamp": _iso(NOW - timedelta(minutes=9)), "status": "executed", "topic": "Braess " * 60}])
    item = _mail(1, "oracle", "plan_item", {"title": "Lab state packet"}, to="nara", minutes=30)
    _jsonl(repo / "run_state" / "oracle_nara_mailbox.jsonl", [item])

    idle = _observe(repo)["nara"]
    assert idle["status"] == "idle"
    assert idle["activity"].startswith("Last cycle (executed): Braess")
    assert len(idle["activity"]) < 200
    assert "wake" in idle["detail"] and "cycle:executed" in idle["detail"]

    claim = _mail(2, "nara", "receipt", {"state": "claimed"}, reply=item["msg_id"], minutes=4)
    _jsonl(repo / "run_state" / "oracle_nara_mailbox.jsonl", [item, claim])
    working = _observe(repo)["nara"]
    assert working["status"] == "working"
    assert working["activity"] == "Lane (claimed): Lab state packet"
    assert "Lane last receipt: claimed for Lab state packet" in working["detail"]

    done = _mail(3, "nara", "receipt", {"state": "validated"}, reply=item["msg_id"], minutes=1)
    _jsonl(repo / "run_state" / "oracle_nara_mailbox.jsonl", [item, claim, done])
    assert _observe(repo)["nara"]["status"] == "idle"


def test_nara_stale_and_offline_are_reported_honestly(tmp_path):
    repo = _repo(tmp_path)
    (repo / "logs" / "nara-daemon.log").write_text(
        f"[nara-daemon] {_iso(NOW - timedelta(hours=5))} wake=heartbeat work=no action=cycle:skipped\n")
    assert _observe(repo)["nara"]["status"] == "stale"
    offline = _observe(repo, service={**SERVICE, "status": "offline", "detail": "Nara service is not active."})
    assert offline["nara"]["status"] == "offline"
    assert _agents(offline)


def test_empty_repo_yields_unknown_cards_that_validate(tmp_path):
    cards = _observe(tmp_path)
    assert cards["oracle"]["status"] == "unknown" and "items" not in cards["oracle"]
    assert cards["meta_oracle"]["status"] == "unknown"
    assert cards["nara"]["status"] == "stale"
    assert _agents(cards)


def test_tail_read_is_bounded_and_drops_partial_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text("first line\n" + "x" * 50 + "\nlast\npartial")
    assert _tail(path, 14) == ["last"]
    assert _tail(tmp_path / "missing", 10) == []


def test_list_processes_reads_a_fake_proc_tree(tmp_path):
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    (proc / "42" / "cmdline").write_bytes(b"bash\0/x/scripts/oracle-daily\0work\0")
    (proc / "42" / "stat").write_text("42 (bash) S 7 42 42 0 -1 4194560")
    (proc / "43").mkdir()  # vanished mid-scan: no cmdline
    (proc / "self").mkdir()
    assert list_processes(proc) == [{"pid": 42, "ppid": 7, "tty": 0, "cwd": None,
                                     "argv": ["bash", "/x/scripts/oracle-daily", "work"]}]
