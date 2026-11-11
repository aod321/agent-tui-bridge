"""Read Claude Code and Codex CLI JSONL session logs.

Both tools append one whole JSON object per line while they run.

Turn end markers: Claude -> {"type":"system","subtype":"turn_duration"};
Codex -> {"type":"event_msg","payload":{"type":"task_complete"|"turn_aborted"}}.

Caveat found with Claude Code 2.1.322: while an AskUserQuestion menu is on
screen, the assistant row holding that tool_use is *not* in the log yet. It is
written together with the tool_result after the user answers. A permission
prompt for Bash, by contrast, does have its tool_use row in the log while it
waits. So the log alone cannot tell that Claude is waiting for a person; the
watcher combines it with Rex's program status and the screen.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

from .errors import TargetError

TOOLS = ("claude", "codex")
# Claude tools whose tool_use means "a person has to answer this".
CLAUDE_USER_INPUT_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
# Codex function calls with the same meaning.
CODEX_USER_INPUT_TOOLS = {"request_user_input"}


def claude_project_key(cwd: str) -> str:
    """Claude names a project's log folder after its cwd with every non-alphanumeric char as '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.path.expanduser(cwd)))


def latest(tool: str, cwd: str | None = None) -> str | None:
    if tool == "claude":
        base = os.path.expanduser("~/.claude/projects")
        if cwd:
            files = glob.glob(f"{base}/{glob.escape(claude_project_key(cwd))}/*.jsonl")
        else:
            files = glob.glob(f"{base}/*/*.jsonl")
    else:
        files = glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/rollout-*.jsonl"))
        if cwd:
            want = os.path.realpath(os.path.expanduser(cwd))
            files = [f for f in files if _codex_cwd(f) == want]
    return max(files, key=os.path.getmtime) if files else None


def _codex_cwd(path: str) -> str | None:
    with open(path) as fh:
        first = fh.readline()
    if not first.strip():
        return None
    meta = json.loads(first)
    cwd = (meta.get("payload") or {}).get("cwd")
    return os.path.realpath(cwd) if cwd else None


def line_count(path: str) -> int:
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def rows(path: str, start: int = 0) -> list[dict]:
    """Parse complete JSONL rows from line `start` on. A partial last line is skipped."""
    out = []
    with open(path) as fh:
        for i, line in enumerate(fh):
            if i < start:
                continue
            if not line.endswith("\n"):
                break  # still being written
            if not line.strip():
                continue
            out.append(json.loads(line))
    return out


class LogTail:
    """Incrementally read rows appended after line `start` of a JSONL file."""

    def __init__(self, path: str, start: int):
        self.path = path
        self.start = start
        self.rows: list[dict] = []
        self._offset: int | None = None  # byte offset just after line `start`
        self.lines = 0  # lines in the file as of the last poll
        self.last_change: float | None = None

    def poll(self, now: float) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        new: list[dict] = []
        with open(self.path, "rb") as fh:
            if self._offset is None:
                for i in range(self.start):
                    if not fh.readline():
                        raise ValueError(
                            f"{self.path} has only {i} lines, fewer than --from {self.start}; "
                            "mark the log before sending"
                        )
                self._offset = fh.tell()
                self.lines = self.start
            fh.seek(self._offset)
            while True:
                pos = fh.tell()
                line = fh.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    fh.seek(pos)
                    break
                self._offset = fh.tell()
                self.lines += 1
                if line.strip():
                    new.append(json.loads(line))
        if new:
            self.rows.extend(new)
            self.last_change = now
        return new


def text_of(tool: str, r: dict):
    """Return (role, text) for a user/assistant message row, else None."""
    if tool == "claude":
        if r.get("type") not in ("user", "assistant") or r.get("isSidechain"):
            return None
        c = (r.get("message") or {}).get("content")
        if isinstance(c, str):
            t = c
        else:
            t = "\n".join(x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")
        if r.get("isMeta") or not t.strip() or t.lstrip().startswith("<"):
            return None
        return r["type"], t
    p = r.get("payload") or {}
    if r.get("type") == "response_item" and p.get("type") == "message" and p.get("role") in ("user", "assistant"):
        t = "\n".join(x.get("text", "") for x in p.get("content", []) if isinstance(x, dict))
        if not t.strip() or t.lstrip().startswith("<"):
            return None
        return p["role"], t
    return None


def is_end(tool: str, r: dict) -> bool:
    if tool == "claude":
        return r.get("type") == "system" and r.get("subtype") == "turn_duration"
    return r.get("type") == "event_msg" and (r.get("payload") or {}).get("type") in ("task_complete", "turn_aborted")


def end_reason(tool: str, r: dict) -> str:
    if tool == "codex" and (r.get("payload") or {}).get("type") == "turn_aborted":
        return "aborted"
    return "completed"


def last_reply(tool: str, rs: list[dict]) -> str:
    replies = [m[1] for m in (text_of(tool, r) for r in rs) if m and m[0] == "assistant"]
    return replies[-1] if replies else ""


def model_of(tool: str, path: str):
    m = None
    for r in rows(path):
        if tool == "claude" and r.get("type") == "assistant":
            m = (r.get("message") or {}).get("model") or m
        if tool == "codex" and r.get("type") == "turn_context":
            p = r.get("payload") or {}
            m = f'{p.get("model")} effort={p.get("effort")}'
    return m


@dataclass
class PendingCall:
    tool_name: str
    call_id: str
    user_input: bool  # a tool whose whole purpose is to ask the person
    questions: list[dict] = field(default_factory=list)
    input: dict | str | None = None


def pending_calls(tool: str, rs: list[dict]) -> list[PendingCall]:
    """Tool calls in `rs` that have no result yet, oldest first."""
    pending: dict[str, PendingCall] = {}
    if tool == "claude":
        for r in rs:
            # api-request-blob rows replay history sent to the API; only real rows count.
            if r.get("type") not in ("assistant", "user") or r.get("isSidechain"):
                continue
            c = (r.get("message") or {}).get("content")
            if not isinstance(c, list):
                continue
            for x in c:
                if not isinstance(x, dict):
                    continue
                if r["type"] == "assistant" and x.get("type") == "tool_use":
                    name = x.get("name", "")
                    inp = x.get("input") or {}
                    qs = inp.get("questions") if name == "AskUserQuestion" and isinstance(inp, dict) else None
                    pending[x["id"]] = PendingCall(
                        tool_name=name,
                        call_id=x["id"],
                        user_input=name in CLAUDE_USER_INPUT_TOOLS,
                        questions=list(qs or []),
                        input=inp,
                    )
                elif r["type"] == "user" and x.get("type") == "tool_result":
                    pending.pop(x.get("tool_use_id"), None)
        return list(pending.values())
    for r in rs:
        if r.get("type") != "response_item":
            continue
        p = r.get("payload") or {}
        t = p.get("type")
        if t in ("function_call", "custom_tool_call", "local_shell_call"):
            name = p.get("name") or t
            args = p.get("arguments") if t == "function_call" else p.get("input")
            qs: list[dict] = []
            if name in CODEX_USER_INPUT_TOOLS and isinstance(args, str):
                parsed = json.loads(args)
                qs = list(parsed.get("questions") or [])
            pending[p.get("call_id") or p.get("id")] = PendingCall(
                tool_name=name,
                call_id=p.get("call_id") or p.get("id"),
                user_input=name in CODEX_USER_INPUT_TOOLS,
                questions=qs,
                input=args,
            )
        elif t in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            pending.pop(p.get("call_id"), None)
    return list(pending.values())


def format_questions(questions: list[dict]) -> str:
    """Render AskUserQuestion / request_user_input questions for a person to read.

    Option numbers match the keys Claude Code accepts on each page. Claude adds
    "Type something" and "Chat about this" after the listed options.
    """
    out = []
    for qi, q in enumerate(questions, 1):
        head = q.get("header") or q.get("id") or f"Q{qi}"
        mode = "multi-select" if q.get("multiSelect") else "single-select"
        out.append(f"Q{qi} [{head}] ({mode}) {q.get('question', '')}")
        opts = q.get("options") or []
        for oi, o in enumerate(opts, 1):
            desc = o.get("description") or ""
            out.append(f"  {oi}. {o.get('label', '')}" + (f" — {desc}" if desc else ""))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Find the log that belongs to a process running in a Rex pane


def claude_log_for_pid(pid: int) -> str | None:
    """Exact log path for a running Claude Code process, from ~/.claude/sessions/<pid>.json.

    The file may not exist yet: Claude creates it on the first message.
    Returns None if the pid has no session file (not Claude, or too old a version).
    """
    meta_path = os.path.expanduser(f"~/.claude/sessions/{pid}.json")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as fh:
        meta = json.load(fh)
    sid, cwd = meta.get("sessionId"), meta.get("cwd")
    if not sid or not cwd:
        raise ValueError(f"{meta_path} lacks sessionId or cwd: {meta}")
    found = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
    if len(found) > 1:
        raise ValueError(f"several logs for Claude session {sid}: {found}")
    if found:
        return found[0]
    return os.path.join(os.path.expanduser("~/.claude/projects"), claude_project_key(cwd), f"{sid}.jsonl")


def process_start(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=True)
    stamp = " ".join(out.stdout.split())
    return datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y").timestamp()


class AmbiguousLog(TargetError):
    pass


def codex_log_for_process(pid: int, cwd: str) -> str | None:
    """The Codex rollout written by the process `pid` running in `cwd`.

    Codex keeps no pid -> rollout map, so this picks rollouts whose session cwd
    matches and that were modified after the process started. Raises
    AmbiguousLog when more than one matches; pass the log path explicitly then.
    Returns None when none matches yet (Codex writes the file on the first prompt).
    """
    started = process_start(pid) - 2
    want = os.path.realpath(cwd)
    files = glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/rollout-*.jsonl"))
    hits = [f for f in files if os.path.getmtime(f) >= started and _codex_cwd(f) == want]
    if len(hits) > 1:
        raise AmbiguousLog(f"several Codex rollouts for {want} since pid {pid} started: {sorted(hits)}")
    return hits[0] if hits else None
