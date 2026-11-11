"""Wait for a Claude Code / Codex turn to end *or* for the agent to need a person.

Signals, checked about once a second:

1. Session log (JSONL): the turn-end marker after line --from ends the wait
   with status=turn_end. An unanswered AskUserQuestion / ExitPlanMode /
   request_user_input call in the log means needs_input.
2. Rex program status (OSC 7501), which Claude Code and Codex report on their
   own: state=blocked (kind permission/question/auth) means needs_input.
3. The screen (rex capture): a key-hint footer such as "Enter to select ·
   ... · Esc to cancel" on the last lines means a menu is waiting. This is the
   only signal for the trust-folder screen, /model menus and Codex's hook
   review, which report no blocked status.
4. The pane: if the agent process is gone, or the session/block was closed,
   status=exited.

A needs_input signal must hold for two polls in a row before it is reported,
so a menu that is being dismissed is not reported twice.
"""
from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import asdict, dataclass, field

from . import logs, screen
from .errors import TargetError
from .rex import Rex, RexError, Target, agent_process, wait_agent

EXIT_CODES = {"turn_end": 0, "timeout": 3, "needs_input": 4, "exited": 5}


@dataclass
class WatchResult:
    status: str  # turn_end | needs_input | exited | timeout
    tool: str
    session_id: str
    block_id: str
    label: str
    log: str | None
    frm: int | None
    lines: int | None
    elapsed: float
    source: str = ""  # log | rex_status | screen | pane
    kind: str | None = None  # question | permission | trust | auth | menu
    reason: str = ""
    reply: str = ""
    prompt: str = ""
    screen: str = ""
    menu: dict | None = None
    questions: list = field(default_factory=list)
    rex_status: dict | None = None
    pending_tools: list = field(default_factory=list)
    exit_code: int | None = None
    pages: list | None = None

    @property
    def code(self) -> int:
        return EXIT_CODES[self.status]

    def status_line(self) -> str:
        pairs = [
            ("status", self.status),
            ("kind", self.kind),
            ("source", self.source),
            ("reason", self.reason or None),
            ("tool", self.tool),
            ("session", self.session_id),
            ("block", self.block_id),
            ("label", self.label or None),
            ("log", self.log or "none"),
            ("from", self.frm),
            ("lines", self.lines),
            ("elapsed", f"{self.elapsed:.1f}"),
            ("exit_code", self.exit_code),
        ]
        if self.rex_status:
            pairs.append(("rex_state", self.rex_status.get("state")))
        if self.pending_tools:
            pairs.append(("pending", ",".join(self.pending_tools)))
        if self.menu and self.menu.get("tabs"):
            pairs.append(("tabs", len(self.menu["tabs"])))
        return " ".join(f"{k}={shlex.quote(str(v))}" for k, v in pairs if v is not None and v != "")

    def to_text(self) -> str:
        out = [self.status_line()]
        rs = self.rex_status
        if rs and (rs.get("state") == "blocked" or self.status == "timeout"):
            out.append(f"rex_status: {rs.get('state')}" + (f" ({rs['kind']})" if rs.get("kind") else "")
                       + (f": {rs['msg']}" if rs.get("msg") else ""))
        if self.status == "turn_end":
            out += ["----- reply -----", self.reply, "----- end reply -----"]
        elif self.status == "needs_input":
            if self.menu and self.menu.get("tabs"):
                labels = " | ".join(t["label"] for t in self.menu["tabs"])
                out.append(f"tabs: {labels}")
            if self.pages:
                for p in self.pages:
                    out += [f"----- page {p['index'] + 1}/{len(self.pages)}: {p['tab'] or ''} -----", p["prompt"]]
                out.append("----- end pages -----")
            else:
                out += ["----- prompt (screen, verbatim) -----", self.prompt, "----- end prompt -----"]
            if self.questions:
                out += ["----- questions (session log) -----", logs.format_questions(self.questions),
                        "----- end questions -----"]
            out += self._hints()
        else:
            if self.prompt:
                out.append(self.prompt)
            if self.screen:
                tail = "\n".join(screen.normalize(self.screen)[-15:])
                out += ["----- screen tail -----", tail, "----- end screen -----"]
        return "\n".join(out)

    def _hints(self) -> list[str]:
        here = os.path.dirname(os.path.realpath(__file__))
        menu_bin = os.path.normpath(os.path.join(here, "..", "..", "bin", "agent-menu"))
        s = shlex.quote(self.session_id)
        b = shlex.quote(self.block_id)
        hints = []
        tabs = (self.menu or {}).get("tabs") or []
        if len([t for t in tabs if not t.get("submit")]) > 1 and not self.pages:
            hints.append(f"hint: {len(tabs)}-page question menu; read every page with: {menu_bin} read -s {s} -b {b}")
        if tabs:
            n = len([t for t in tabs if not t.get("submit")])
            hints.append(f"hint: answer with: {menu_bin} answer -s {s} -b {b} " + " ".join(["N"] * n)
                         + "  (one per question page; N,M on multi-select pages; text:WORDS for Type something)")
        else:
            hints.append(f"hint: answer with: {menu_bin} answer -s {s} -b {b} N  (option N, counted from the top)")
        return hints

    def to_json(self) -> str:
        d = asdict(self)
        d["from"] = d.pop("frm")
        d["exit"] = self.code
        return json.dumps(d, ensure_ascii=False)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def agent_status(records: list[dict], tool: str) -> dict | None:
    """The program-status record reported by the agent (blocked records win)."""
    app = "claude" if tool == "claude" else "codex"
    mine = [r for r in records if app in (r.get("effective_app") or r.get("app") or "")]
    if not mine:
        return None
    blocked = [r for r in mine if r.get("state") == "blocked"]
    return blocked[0] if blocked else mine[0]


def watch(
    rex: Rex,
    target: Target,
    tool: str,
    log_path: str | None,
    frm: int | None,
    *,
    timeout: float,
    interval: float = 1.0,
    debounce: int = 2,
    screen_idle: float = 2.0,
    status_grace: float = 5.0,
    log_resolver=None,
    read_tabs: bool = False,
    start_timeout: float = 15.0,
    clock=time.monotonic,
    sleep=time.sleep,
    alive=pid_alive,
) -> WatchResult:
    t0 = clock()
    tail = logs.LogTail(log_path, frm or 0) if log_path else None
    last_screen = ""
    last_status: dict | None = None

    def result(status: str, **kw) -> WatchResult:
        return WatchResult(
            status=status,
            tool=tool,
            session_id=target.session_id,
            block_id=target.block_id,
            label=target.label,
            log=tail.path if tail else log_path,
            frm=frm,
            lines=tail.lines if tail else None,
            elapsed=clock() - t0,
            screen=kw.pop("screen", last_screen),
            rex_status=kw.pop("rex_status", last_status),
            **kw,
        )

    def turn_end_from_log() -> WatchResult | None:
        if tail is None:
            return None
        for i, r in enumerate(tail.rows):
            if logs.is_end(tool, r):
                return result("turn_end", source="log", reason=logs.end_reason(tool, r),
                              reply=logs.last_reply(tool, tail.rows[:i]))
        return None

    def poll_log(now: float) -> None:
        nonlocal tail
        if tail is None and log_resolver is not None:
            path = log_resolver()
            if path:
                tail = logs.LogTail(path, frm or 0)
        if tail is not None:
            tail.poll(now)

    def process_or_exit() -> tuple[dict | None, WatchResult | None]:
        try:
            return rex.call(target, "process"), None
        except RexError:
            gone = rex.target_alive(target)
            if gone:
                return None, result("exited", source="pane", reason=gone)
            raise

    try:
        proc, agent = wait_agent(rex, target, tool, start_timeout, clock=clock, sleep=sleep)
    except RexError:
        gone = rex.target_alive(target)
        if gone:
            return result("exited", source="pane", reason=gone)
        raise
    if agent is None:
        fg = proc.get("foreground") or proc.get("child") or {}
        last = proc.get("last_exit") or {}
        return result("exited", source="pane", reason="no_agent_process",
                      exit_code=last.get("exit_code"),
                      screen=rex.capture(target),
                      prompt=f"foreground process: {fg.get('argv0') or fg.get('name') or 'none'}")
    agent_pid = agent["pid"]

    seen_active = False
    settled_since: float | None = None
    cand = None
    streak = 0
    while True:
        now = clock()
        poll_log(now)
        done = turn_end_from_log()
        if done:
            return done

        proc, ended = process_or_exit()
        if ended:
            return ended
        last = proc.get("last_exit")
        if (last is not None and not proc.get("child")) or not alive(agent_pid):
            poll_log(clock())
            done = turn_end_from_log()
            if done:
                return done
            return result("exited", source="pane", reason="agent_exited",
                          exit_code=(last or {}).get("exit_code"), screen=rex.capture(target))

        last_status = agent_status(rex.call(target, "program_status").get("records") or [], tool)
        state = last_status.get("state") if last_status else None
        if state in ("working", "blocked"):
            seen_active = True

        rows = tail.rows if tail else []
        pend = logs.pending_calls(tool, rows)
        asks = [p for p in pend if p.user_input]
        changed_at = tail.last_change if tail and tail.last_change is not None else t0
        log_idle = now - changed_at
        scr = None
        if state != "working" or log_idle >= screen_idle or asks:
            last_screen = rex.capture(target)
            scr = screen.analyze(last_screen)

        signal = None
        if state == "blocked":
            signal = ("rex_status", last_status.get("kind") or (scr.kind if scr and scr.needs_input else None) or "unknown")
        elif asks:
            signal = ("log", "question")
        elif scr is not None and scr.needs_input:
            signal = ("screen", scr.kind)

        if signal:
            streak = streak + 1 if signal == cand else 1
            cand = signal
            settled_since = None
            if streak >= debounce:
                if scr is None:
                    last_screen = rex.capture(target)
                    scr = screen.analyze(last_screen)
                if scr.needs_input:
                    prompt, menu, why = scr.prompt, scr.menu.to_dict(), scr.reason
                else:
                    prompt = "\n".join(screen.normalize(last_screen)[-30:])
                    menu, why = None, "screen heuristics found no prompt; showing the screen tail"
                questions = asks[0].questions if asks else []
                pages = None
                if read_tabs and menu and len([t for t in menu["tabs"] if not t["submit"]]) > 1:
                    from . import menu as menu_mod
                    pages = [p.to_dict() for p in menu_mod.read_all(rex, target)]
                return result(
                    "needs_input",
                    source=signal[0],
                    kind=signal[1],
                    reason=why,
                    prompt=prompt,
                    menu=menu,
                    questions=questions,
                    pending_tools=[p.tool_name for p in pend],
                    pages=pages,
                )
        else:
            cand, streak = None, 0
            spinner = scr is not None and screen.looks_busy(screen.normalize(last_screen))
            if seen_active and state in ("done", "idle") and log_idle >= status_grace and not spinner:
                settled_since = settled_since if settled_since is not None else now
                if now - settled_since >= status_grace:
                    return result(
                        "turn_end",
                        source="rex_status",
                        reason=f"program status {state} for {status_grace:.0f}s without a log turn-end marker",
                        reply=logs.last_reply(tool, rows),
                    )
            else:
                settled_since = None

        if now - t0 >= timeout:
            if scr is None:
                last_screen = rex.capture(target)
            return result("timeout", reason=f"no turn end after {timeout:.0f}s",
                          pending_tools=[p.tool_name for p in pend])
        sleep(interval)


def resolve_log(rex: Rex, target: Target, tool: str, start_timeout: float = 15.0):
    """Return (path or None, resolver) for the agent running in `target`.

    Claude: exact, from ~/.claude/sessions/<pid>.json, which Claude writes once
    the folder is trusted. Codex: the rollout for the pane's cwd written since
    the process started (raises if ambiguous). Both can be None at first (no
    session file / no rollout yet); `resolver` repeats the lookup, and the
    watcher calls it on every poll until it returns a path.
    """
    proc, agent = wait_agent(rex, target, tool, start_timeout)
    if agent is None:
        fg = proc.get("foreground") or proc.get("child") or {}
        last = proc.get("last_exit")
        state = f"exited with {last.get('exit_code')}" if last and not proc.get("child") else \
            f"foreground: {fg.get('argv0') or fg.get('name')}"
        raise TargetError(f"no {tool} process in block {target.block_id} after {start_timeout:.0f}s ({state})")
    pid = agent["pid"]
    if tool == "claude":
        return logs.claude_log_for_pid(pid), (lambda: logs.claude_log_for_pid(pid))
    cwd = agent.get("cwd")
    if not cwd:
        raise TargetError(f"Rex does not report a cwd for codex pid {pid}; pass the log file explicitly")

    def resolver():
        return logs.codex_log_for_process(pid, cwd)

    return resolver(), resolver
