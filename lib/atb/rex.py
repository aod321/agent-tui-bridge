"""Thin wrapper over the Rex CLI (bin/rex) used by agent-watch and agent-menu.

Every call goes through bin/rex, so ATB_REX and the bundled-CLI lookup apply.
A failing rex command raises RexError with its stderr; nothing is retried.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from .errors import TargetError

BIN_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "bin"))


class RexError(RuntimeError):
    def __init__(self, args: list[str], code: int, stderr: str):
        self.args_list = args
        self.code = code
        self.stderr = stderr.strip()
        super().__init__(f"rex {' '.join(args)} failed (exit {code}): {self.stderr}")


@dataclass
class Target:
    session_id: str
    block_id: str
    label: str  # session label when resolved; it may change later (Rex hooks rename sessions)


class Rex:
    def __init__(self, bin_path: str | None = None):
        self.bin = bin_path or os.path.join(BIN_DIR, "rex")

    def run(self, *args: str, input_text: str | None = None) -> str:
        p = subprocess.run([self.bin, *args], capture_output=True, text=True, input=input_text)
        if p.returncode != 0:
            raise RexError(list(args), p.returncode, p.stderr)
        return p.stdout

    def json(self, *args: str):
        return json.loads(self.run(*args))

    # -- discovery ---------------------------------------------------------
    def sessions(self) -> list[dict]:
        return self.json("ls", "--json", "--short=false")["sessions"]

    def blocks(self, session_id: str) -> list[dict]:
        return self.json("block", "ls", "-s", session_id, "--json", "--short=false")["blocks"]

    def inspect(self, session_id: str) -> dict:
        return self.json("session", "inspect", session_id, "--json")

    # -- per-block calls -----------------------------------------------------
    def call(self, t: Target, method: str, args: dict | None = None) -> dict:
        cmd = ["block", "call", "-s", t.session_id, "-b", t.block_id, method]
        if args is not None:
            cmd.append(json.dumps(args))
        return json.loads(self.run(*cmd))

    def capture(self, t: Target, fmt: str = "text") -> str:
        cmd = ["capture", "-s", t.session_id, "-b", t.block_id]
        if fmt == "text":
            cmd.append("--trim")
        else:
            cmd += ["--format", fmt]
        return self.run(*cmd)

    def send_keys(self, t: Target, *keys: str) -> None:
        self.run("send-key", "-s", t.session_id, "-b", t.block_id, *keys)

    def send_text(self, t: Target, text: str) -> None:
        self.run("send", "-s", t.session_id, "-b", t.block_id, "--", text)

    def target_alive(self, t: Target) -> str | None:
        """None if the session and block still exist, else 'session_gone' or 'block_gone'."""
        if not any(s["session_id"] == t.session_id for s in self.sessions()):
            return "session_gone"
        if not any(b["block_id"] == t.block_id for b in self.blocks(t.session_id)):
            return "block_gone"
        return None


def _match(items: list[dict], key: str, want: str, kind: str) -> dict:
    """Match a Rex ID, label, or ID suffix. Raise unless exactly one item matches."""
    exact = [i for i in items if i[key] == want]
    if exact:
        return exact[0]
    by_label = [i for i in items if i.get("label") == want]
    if len(by_label) == 1:
        return by_label[0]
    if len(by_label) > 1:
        ids = ", ".join(i[key] for i in by_label)
        raise TargetError(f"{kind} label {want!r} matches several {kind}s ({ids}); pass an ID")
    suffix = [i for i in items if i[key].endswith(want)]
    if len(suffix) == 1:
        return suffix[0]
    if len(suffix) > 1:
        raise TargetError(f"{kind} ID suffix {want!r} is ambiguous; pass the full ID")
    names = ", ".join(f"{i.get('label')}={i[key]}" for i in items) or "none"
    raise TargetError(f"no {kind} matches {want!r} (have: {names})")


def agent_process(proc: dict, tool: str) -> dict | None:
    """The claude/codex process in a block's `process` result, if any."""
    for key in ("foreground", "child"):
        p = proc.get(key)
        if not p:
            continue
        hay = " ".join(str(p.get(k, "")) for k in ("argv0", "name", "path", "invoked_path", "script")).lower()
        if tool in hay:
            return p
    return None


def wait_agent(rex: Rex, t: Target, tool: str, timeout: float, clock=None, sleep=None) -> tuple[dict, dict | None]:
    """Wait up to `timeout` seconds for claude/codex to be running in the block.

    Right after `rex new --interactive`, the pane is still reading ~/.zshrc, so
    the agent may not be there yet. Returns (process result, agent or None).
    Stops early if the pane's program has already exited.
    """
    import time

    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    deadline = clock() + timeout
    while True:
        proc = rex.call(t, "process")
        agent = agent_process(proc, tool)
        exited = proc.get("last_exit") is not None and not proc.get("child")
        if agent or exited or clock() >= deadline:
            return proc, agent
        sleep(0.5)


def resolve(rex: Rex, session: str | None, block: str | None, tool: str | None = None) -> Target:
    """Turn a session/block label, ID, or ID suffix into full IDs.

    Labels are looked up once, here. Rex's agent hooks can rename a session
    while the agent runs, so later calls use only the IDs.
    """
    if not session and not block:
        raise TargetError("pass -s SESSION (a Rex session ID or label) or -b BLOCK")
    sessions = rex.sessions()
    if session:
        s = _match(sessions, "session_id", session, "session")
        candidates = [s]
    else:
        candidates = sessions
    if block:
        hits = []
        for s in candidates:
            for b in rex.blocks(s["session_id"]):
                if b["block_id"] == block or b["block_id"].endswith(block) or b.get("label") == block:
                    hits.append((s, b))
        if len(hits) != 1:
            raise TargetError(f"block {block!r} matched {len(hits)} blocks; pass a full block ID with -b")
        s, b = hits[0]
        return Target(session_id=s["session_id"], block_id=b["block_id"], label=s.get("label", ""))
    s = candidates[0]
    blocks = [b for b in rex.blocks(s["session_id"]) if b.get("creator_name") == "com.superlogical.terminal"]
    if not blocks:
        raise TargetError(f"session {s['session_id']} has no terminal block")
    if len(blocks) == 1:
        return Target(session_id=s["session_id"], block_id=blocks[0]["block_id"], label=s.get("label", ""))
    if tool:
        running = []
        for b in blocks:
            t = Target(s["session_id"], b["block_id"], s.get("label", ""))
            if agent_process(rex.call(t, "process"), tool):
                running.append(t)
        if len(running) == 1:
            return running[0]
    ids = ", ".join(b["block_id"] for b in blocks)
    raise TargetError(f"session {s['session_id']} has several terminal blocks ({ids}); pass -b BLOCK")
