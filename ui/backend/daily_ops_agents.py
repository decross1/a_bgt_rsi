"""Read-only observation of who in the lab is active and what each is doing.

Sources (all bounded, read-only, no network, no mutating subprocess):
live processes from /proc, the Oracle daily-loop and meta-oracle transcripts and
run-log rows, the Oracle<->Nara mailbox, the newest daily plan, the interactive
Pi session files, the Nara daemon log, the coordinator cycle log and the active
run mirror.  A card states only what these files show; it never reads prose to
decide a status.
"""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from .daily_ops import _read_regular

PI_ACTIVE_SECONDS = 600
NARA_STALE_SECONDS = 2 * 3600  # daemon heartbeat is 30 min; four missed beats is stale
_PLAN_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-r(\d+))?\.json$")
_LOG_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z]+)-(\d{9,11})\.log$")
_DAEMON_LINE = re.compile(r"^\[nara-daemon\] (\S+) wake=(\S+) work=\S+ action=(\S+)")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _when(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _clip(value: object, maximum: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join("".join(c if ord(c) >= 32 else " " for c in value).split())
    if not text:
        return None
    return text if len(text) <= maximum else text[:maximum - 1].rstrip() + "…"


def _tail(path: Path, maximum: int) -> list[str]:
    """Complete lines from the last ``maximum`` bytes of a regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return []
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            return []
        start = max(0, info.st_size - maximum)
        handle.seek(start)
        raw = handle.read(min(info.st_size, maximum))
    lines = raw.decode("utf-8", errors="replace").split("\n")
    if start > 0:
        lines = lines[1:]  # the first line may be partial
    return [line for line in lines[:-1] if line.strip()]  # the last may be mid-append


def _json_rows(path: Path, maximum: int, needles: tuple[str, ...] = ()) -> list[dict]:
    rows = []
    for line in _tail(path, maximum):
        if needles and not any(needle in line for needle in needles):
            continue  # cheap prefilter before parsing a large log tail
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def list_processes(proc: Path = Path("/proc")) -> list[dict]:
    """pid, ppid, controlling tty, argv and cwd of every readable process."""
    found = []
    try:
        names = [name for name in os.listdir(proc) if name.isdigit()]
    except OSError:
        return found
    for name in names:
        try:  # processes may exit mid-scan; skip any that vanish
            argv = [a.decode(errors="replace") for a in (proc / name / "cmdline").read_bytes().split(b"\0") if a]
            fields = (proc / name / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        try:
            cwd = os.readlink(proc / name / "cwd")
        except OSError:
            cwd = None
        if argv:
            found.append({"pid": int(name), "ppid": int(fields[1]), "tty": int(fields[4]),
                          "argv": argv, "cwd": cwd})
    return found


def _script_runs(processes: list[dict], script: str) -> list[str]:
    """The mode argument of each live run of ``script`` (argv-exact, not bash -c text)."""
    modes = []
    for process in processes:
        argv = process["argv"]
        for index, arg in enumerate(argv):
            if os.path.basename(arg) == script:
                modes.append(argv[index + 1] if index + 1 < len(argv) else "")
                break
    return modes


def _newest_log(directory: Path, mode: str | None) -> dict | None:
    best = None
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    for name in names:
        match = _LOG_NAME.match(name)
        if match and (mode is None or match.group(2) == mode):
            epoch = int(match.group(3))
            if best is None or epoch > best["epoch"]:
                best = {"date": match.group(1), "mode": match.group(2), "epoch": epoch, "name": name}
    return best


def _last_run_row(rows: list[dict], prefix: str) -> dict | None:
    for row in reversed(rows):
        if str(row.get("task_id", "")).startswith(prefix) and _when(row.get("timestamp")):
            return row
    return None


def _mailbox_line(row: dict, titles: dict) -> str:
    body = row.get("body") if isinstance(row.get("body"), dict) else {}
    head = f"#{row.get('seq')} {row.get('kind')}"
    if row.get("kind") == "review" and body.get("verdict"):
        head += f" {body['verdict']}"
    target = row.get("in_reply_to")
    if target:
        head += f" re {titles.get(target) or target}"
    text = _clip(body.get("title") or body.get("summary") or body.get("text") or body.get("state"), 200)
    return _clip(head if not text else f"{head}: {text}", 400)


def _latest_plan(repo: Path) -> dict | None:
    directory = repo / "run_state" / "daily_plans"
    try:
        names = [n for n in os.listdir(directory) if _PLAN_NAME.match(n)]
    except OSError:
        return None
    if not names:
        return None
    name = max(names, key=lambda n: (_PLAN_NAME.match(n).group(1), int(_PLAN_NAME.match(n).group(2) or 0)))
    try:
        plan = json.loads(_read_regular(directory / name, 262_144))
    except (OSError, ValueError):
        return None
    items = []
    for item in (plan.get("items") if isinstance(plan, dict) and isinstance(plan.get("items"), list) else [])[:16]:
        if isinstance(item, dict):
            items.append({key: _clip(item.get(key), 200 if key == "title" else 64) or "?"
                          for key in ("id", "goal", "owner", "title")})
    return {"name": name, "items": items}


def _card(label, role, status, detail, now, source, *, activity=None, activity_at=None,
          since=None) -> dict:
    return {"label": label, "role": role, "status": status, "detail": detail,
            "observed_at": _iso(now), "source": source, "activity": activity,
            "activity_at": _iso(activity_at) if activity_at else None,
            "since": _iso(since) if since else None}


def _scripted(repo, processes, run_rows, now, *, script, logs, prefix, label, role, noun, latest):
    """Card for a phase-scripted agent (the Oracle daily loop and the meta-oracle)."""
    runs = _script_runs(processes, script)
    last = _last_run_row(run_rows, prefix)
    if runs:
        log = _newest_log(repo / "logs" / logs, runs[0] or None)
        since = datetime.fromtimestamp(log["epoch"], timezone.utc) if log else None
        date = f" for {log['date']}" if log else ""
        status, detail = "working", f"Running {noun} {runs[0] or '(no mode)'}{date}."
    elif last is not None:
        since = _when(last["timestamp"])
        _, mode, day = (str(last["task_id"]).split(":") + ["", ""])[:3]
        status = "failed" if last.get("status") == "failed" else "idle"
        detail = f"No live run. Last {noun} {mode} for {day} ended {last.get('status')}."
    else:
        status, since, detail = "unknown", None, f"No live run and no {noun} row in the run log tail."
    return _card(label, role, status, detail, now, f"/proc {script}; logs/{logs}; run log {prefix}*",
                 activity=latest[0] if latest else None, activity_at=latest[1] if latest else None,
                 since=since)


def _pi_card(label, processes, sessions: Path, now) -> dict:
    parents = {p["pid"]: p["argv"] for p in processes}
    live = [p for p in processes
            if os.path.basename(p["argv"][0]) == "pi" and p["tty"] != 0
            and not {"-p", "--print"} & set(p["argv"])
            and not any(os.path.basename(a) in {"oracle-daily", "meta_oracle_run.sh"}
                        for a in parents.get(p["ppid"], []))]
    newest = None
    for process in live:
        if not process.get("cwd"):
            continue
        folder = sessions / ("--" + process["cwd"].strip("/").replace("/", "-") + "--")
        try:
            for entry in os.scandir(folder):
                if entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False):
                    touched = datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)
                    newest = touched if newest is None or touched > newest else newest
        except OSError:
            continue
    if not live:
        status, detail = "offline", "No interactive Pi process is running."
    elif newest is not None and (now - newest).total_seconds() <= PI_ACTIVE_SECONDS:
        status, detail = "active", f"{len(live)} interactive Pi process(es); session written in the last 10 min."
    else:
        status = "idle"
        detail = f"{len(live)} interactive Pi process(es); no session write in the last 10 min."
    return _card(label, "Owner's interactive Oracle client", status, detail, now,
                 "/proc interactive pi; ~/.pi/agent/sessions", since=newest if live else None)


def _nara_card(service: dict, repo: Path, rows: list[dict], titles: dict, now) -> dict:
    parts, status = [service["detail"]], service["status"]
    wake = None
    for line in reversed(_tail(repo / "logs" / "nara-daemon.log", 16_384)):
        match = _DAEMON_LINE.match(line)
        if match and _when(match.group(1)):
            wake = _when(match.group(1))
            parts.append(f"Last daemon wake {match.group(1)[:16]}Z ({match.group(2)}) → {match.group(3)}.")
            break
    cycles = _json_rows(repo / "run_state" / "coordinator_cycles.jsonl", 524_288)
    cycle = cycles[-1] if cycles else None
    cycle_at = _when(cycle.get("timestamp")) if cycle else None
    try:
        active =json.loads(_read_regular(repo / "run_state" / "active_run.json", 65_536))
        active = active if isinstance(active, dict) else None
    except (OSError, ValueError):
        active = None
    claimed, receipt = None, None
    items = {}
    for row in rows:
        if row.get("kind") == "plan_item":
            items[row.get("msg_id")] = {"row": row, "state": "open"}
        elif row.get("kind") in {"receipt", "withdraw"} and row.get("in_reply_to") in items:
            entry = items[row["in_reply_to"]]
            if entry["state"] not in {"validated", "failed", "withdrawn"}:
                body = row.get("body") if isinstance(row.get("body"), dict) else {}
                entry["state"] = "withdrawn" if row["kind"] == "withdraw" else str(body.get("state"))
            if row["kind"] == "receipt":
                receipt = row
    claimed = next((e["row"] for e in reversed(items.values()) if e["state"] == "claimed"), None)
    if receipt is not None:
        body = receipt["body"] if isinstance(receipt.get("body"), dict) else {}
        parts.append(f"Lane last receipt: {body.get('state')} for "
                     f"{titles.get(receipt['in_reply_to']) or receipt['in_reply_to']} at {str(receipt.get('ts', '?'))[:16]}Z.")
    activity, activity_at, since = None, None, None
    if claimed is not None:
        activity = _clip("Lane (claimed): " + str(titles.get(claimed["msg_id"]) or claimed["msg_id"]), 400)
        activity_at = _when(claimed.get("ts"))
    elif active is not None:
        activity = _clip(f"Running {active.get('kind')}: {active.get('label')}"
                         + (f" — {active['current_step']}" if active.get("current_step") else ""), 400)
        activity_at = since = _when(active.get("heartbeat_at")) or _when(active.get("started_at"))
    elif cycle is not None:
        activity = _clip(f"Last cycle ({cycle.get('status')}): {_clip(cycle.get('topic'), 140)}", 400)
        activity_at = cycle_at
    if status == "online":
        if active is not None or claimed is not None:
            status = "working"
            since = _when(active.get("started_at")) if active else activity_at
        else:
            last = max([t for t in (wake, cycle_at) if t], default=None)
            stale = last is None or (now - last).total_seconds() > NARA_STALE_SECONDS
            status, since = ("stale" if stale else "idle"), last
            if stale:
                parts.append("No daemon wake or cycle in the last 2 hours.")
    return _card(service["label"], "Research runner", status, " ".join(parts), now,
                 "nara-daemon.service; logs/nara-daemon.log; coordinator_cycles; mailbox lane",
                 activity=activity, activity_at=activity_at, since=since)


def observe(repo: Path, *, now: datetime, nara_service: dict, oracle_label: str = "Oracle",
            client_label: str = "Pi client", processes: list[dict] | None = None,
            pi_sessions: Path | None = None) -> dict:
    """The oracle, pi_client, nara and meta_oracle cards for the daily-ops summary."""
    processes = list_processes() if processes is None else processes
    mailbox = _json_rows(repo / "run_state" / "oracle_nara_mailbox.jsonl", 4_194_304)
    titles = {}
    for row in mailbox:
        body = row.get("body") if isinstance(row.get("body"), dict) else {}
        titles[row.get("msg_id")] = _clip(body.get("title"), 160)
    latest = {}
    for row in mailbox:
        if row.get("actor") in {"oracle", "claude"} and _when(row.get("ts")):
            latest[row["actor"]] = (_mailbox_line(row, titles), _when(row["ts"]))
    run_rows = _json_rows(repo / "run_state" / "week1.run.jsonl", 2_097_152,
                          ("\"oracle-daily:", "\"meta-oracle:"))
    oracle = _scripted(repo, processes, run_rows, now, script="oracle-daily", logs="oracle_daily",
                       prefix="oracle-daily:", label=oracle_label, role="Steward (daily loop)",
                       noun="daily-loop phase", latest=latest.get("oracle"))
    plan = _latest_plan(repo)
    if plan is not None:
        oracle["items"] = plan["items"]
        oracle["detail"] += f" Newest plan {plan['name']}: {len(plan['items'])} item(s)."
    meta = _scripted(repo, processes, run_rows, now, script="meta_oracle_run.sh", logs="meta_oracle",
                     prefix="meta-oracle:", label="Meta-oracle (Claude)", role="Reviewer",
                     noun="meta-oracle mode", latest=latest.get("claude"))
    return {
        "oracle": oracle,
        "pi_client": _pi_card(client_label, processes,
                              pi_sessions or Path.home() / ".pi" / "agent" / "sessions", now),
        "nara": _nara_card(nara_service, repo, mailbox, titles, now),
        "meta_oracle": meta,
    }
