import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from atb import watch as W
from atb.rex import RexError, Target

SCREENS = os.path.join(HERE, "fixtures", "screens")
LOGS = os.path.join(HERE, "fixtures", "logs")

RUNNING = {"last_exit": None,
           "child": {"pid": 111, "name": "2.1.322", "argv0": "claude", "path": "/x/claude/versions/2.1.322"},
           "foreground": {"pid": 111, "name": "2.1.322", "argv0": "claude"}}
RUNNING_CODEX = {"last_exit": None, "child": {"pid": 222, "name": "codex", "argv0": "codex"},
                 "foreground": {"pid": 222, "name": "codex", "argv0": "codex"}}
EXITED = {"last_exit": {"exit_code": 0}}
SHELL = {"last_exit": None, "child": {"pid": 5, "name": "zsh", "argv0": "-zsh"},
         "foreground": {"pid": 5, "name": "zsh", "argv0": "-zsh"}}


def screen(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as fh:
        return fh.read()


def status(state, kind=None, app="claude-code", msg=None):
    r = {"state": state, "app": app, "effective_app": app, "updated_at": "2026-11-11T17:55:53+08:00"}
    if kind:
        r["kind"] = kind
    if msg:
        r["msg"] = msg
    return [r]


class FakeRex:
    """Plays back one frame per poll. A frame is a dict with optional keys:
    process, status (records), screen, gone (session vanished), append (log text
    written before the frame is shown)."""

    def __init__(self, frames, log_path=None):
        self.frames = frames
        self.i = 0
        self.log_path = log_path
        self.captures = 0
        self._applied = -1
        self._apply()

    def _apply(self):
        if self._applied == self.i:
            return
        self._applied = self.i
        f = self.frame()
        if f.get("append") and self.log_path:
            with open(self.log_path, "a") as fh:
                fh.write(f["append"])

    def frame(self):
        return self.frames[min(self.i, len(self.frames) - 1)]

    def advance(self, _seconds):
        self.i += 1
        self._apply()

    def call(self, t, method, args=None):
        f = self.frame()
        if f.get("gone"):
            raise RexError(["block", "call"], 3, 'block target "x" not found')
        if method == "process":
            return f.get("process", RUNNING)
        if method == "program_status":
            return {"records": f.get("status", [])}
        raise AssertionError(method)

    def capture(self, t, fmt="text"):
        self.captures += 1
        return self.frame().get("screen", "")

    def target_alive(self, t):
        return "session_gone" if self.frame().get("gone") else None


class Clock:
    def __init__(self, rex):
        self.t = 0.0
        self.rex = rex

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.rex.advance(s)


T = Target("session:01a1ca0b-c01d-7b7d-8919-37a4a2f714b9", "block:01a1ca0b-c01d-7bfe-aa20-5397597b31e8", "atb-probe")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "session.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def seed(self, fixture):
        shutil.copy(os.path.join(LOGS, fixture), self.log)
        with open(self.log) as fh:
            return sum(1 for _ in fh)

    def run_watch(self, frames, tool="claude", frm=None, log=True, timeout=30, alive=lambda pid: True, **kw):
        rex = FakeRex(frames, self.log if log else None)
        clock = Clock(rex)
        r = W.watch(rex, T, tool, self.log if log else None, frm, timeout=timeout, interval=1.0,
                    clock=clock.now, sleep=clock.sleep, alive=alive, **kw)
        return r, rex


def jsonl(*rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


class NeedsInput(Base):
    def test_question_menu_not_in_log_is_found_through_rex_status(self):
        """The incident: AskUserQuestion on screen, nothing in the log, turn not over."""
        n = self.seed("claude_ask_not_logged_yet.jsonl")
        menu = screen("claude_ask_pruning_page1.txt")
        frames = [
            {"status": status("working"), "screen": screen("claude_working.txt")},
            {"status": status("blocked", "question", msg="answer: Node pruning ..."), "screen": menu},
            {"status": status("blocked", "question", msg="answer: Node pruning ..."), "screen": menu},
        ]
        r, rex = self.run_watch(frames, frm=n)
        self.assertEqual((r.status, r.source, r.kind), ("needs_input", "rex_status", "question"))
        self.assertEqual(r.code, 4)
        self.assertEqual(rex.i, 2, "reported on the second consecutive blocked poll")
        self.assertTrue(r.prompt.startswith("←  ☐ Pruning  ☐ lisa  ☐ Airport  ☐ Shadowrocket  ✔ Submit  →"))
        self.assertEqual([t["label"] for t in r.menu["tabs"]], ["Pruning", "lisa", "Airport", "Shadowrocket", "Submit"])
        text = r.to_text()
        first = dict(kv.split("=", 1) for kv in shlex.split(text.split("\n")[0]))
        self.assertEqual(first["status"], "needs_input")
        self.assertEqual(first["session"], T.session_id)
        self.assertEqual(first["tabs"], "5")
        self.assertIn("rex_status: blocked (question): answer: Node pruning ...", text)
        self.assertIn("agent-menu read -s " + T.session_id, text)
        self.assertIn("----- prompt (screen, verbatim) -----\n←  ☐ Pruning", text)

    def test_pending_question_in_log(self):
        n = self.seed("claude_turn_end.jsonl")
        with open(os.path.join(LOGS, "claude_ask_pending.jsonl")) as fh:
            pending = fh.read()
        menu = screen("claude_ask_pruning_page1.txt")
        frames = [{"status": status("working"), "screen": screen("claude_working.txt"), "append": pending},
                  {"status": status("working"), "screen": menu},
                  {"status": status("working"), "screen": menu}]
        r, _ = self.run_watch(frames, frm=n)
        self.assertEqual((r.status, r.source, r.kind), ("needs_input", "log", "question"))
        self.assertEqual([q["header"] for q in r.questions], ["Pruning", "lisa", "Airport", "Shadowrocket"])
        self.assertIn("----- questions (session log) -----\nQ1 [Pruning]", r.to_text())
        self.assertIn("AskUserQuestion", r.pending_tools)

    def test_trust_screen_without_status(self):
        frames = [{"status": [], "screen": screen("claude_trust_folder.txt")}] * 3
        r, _ = self.run_watch(frames, log=False, frm=0)
        self.assertEqual((r.status, r.source, r.kind), ("needs_input", "screen", "trust"))
        self.assertIn("log=none", r.status_line())
        self.assertIn("❯ No, exit", r.prompt)

    def test_codex_approval(self):
        frames = [{"process": RUNNING_CODEX, "status": status("blocked", "permission", app="codex"),
                   "screen": screen("codex_exec_approval.txt")}] * 3
        r, _ = self.run_watch(frames, tool="codex", log=False, frm=0)
        self.assertEqual((r.status, r.source, r.kind), ("needs_input", "rex_status", "permission"))
        self.assertTrue(r.prompt.startswith("  Would you like to run the following command?"))

    def test_model_menu_reports_done_status_but_screen_wins(self):
        frames = [{"status": status("done"), "screen": screen("claude_model_menu.txt")}] * 3
        r, _ = self.run_watch(frames, log=False, frm=0)
        self.assertEqual((r.status, r.source, r.kind), ("needs_input", "screen", "menu"))

    def test_blocked_flash_is_not_reported(self):
        n = self.seed("claude_turn_end.jsonl")
        end = jsonl({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
                    {"type": "system", "subtype": "turn_duration"})
        frames = [{"status": status("blocked", "permission"), "screen": screen("claude_permission_bash.txt")},
                  {"status": status("working"), "screen": screen("claude_working.txt")},
                  {"status": status("working"), "screen": screen("claude_working.txt"), "append": end}]
        r, _ = self.run_watch(frames, frm=n)
        self.assertEqual((r.status, r.reply), ("turn_end", "ok"))

    def test_blocked_but_unknown_screen_shows_tail(self):
        frames = [{"status": status("blocked", "auth"), "screen": "Password:\n"}] * 3
        r, _ = self.run_watch(frames, log=False, frm=0)
        self.assertEqual((r.status, r.kind), ("needs_input", "auth"))
        self.assertEqual(r.prompt, "Password:")
        self.assertIn("found no prompt", r.reason)

    def test_quoted_menu_on_idle_screen_is_not_needs_input(self):
        frames = [{"status": status("done"), "screen": screen("claude_idle_quoting_menu.txt")}]
        r, _ = self.run_watch(frames, log=False, frm=0, timeout=5)
        self.assertEqual(r.status, "timeout")
        self.assertEqual(r.code, 3)


class TurnEnd(Base):
    def test_log_marker(self):
        n = self.seed("claude_bash_pending.jsonl")
        end = jsonl({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_bash01"}]}},
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Created hello.txt."}]}},
                    {"type": "system", "subtype": "turn_duration"})
        frames = [{"status": status("working"), "screen": screen("claude_working.txt")},
                  {"status": status("working"), "screen": screen("claude_working.txt"), "append": end}]
        r, _ = self.run_watch(frames, frm=n)
        self.assertEqual((r.status, r.source, r.reason, r.reply), ("turn_end", "log", "completed", "Created hello.txt."))
        self.assertEqual(r.code, 0)
        self.assertIn("----- reply -----\nCreated hello.txt.\n----- end reply -----", r.to_text())

    def test_marker_before_from_is_ignored(self):
        n = self.seed("claude_turn_end.jsonl")
        frames = [{"status": status("done"), "screen": screen("claude_idle_after_turn.txt")}]
        r, _ = self.run_watch(frames, frm=n, timeout=4)
        self.assertEqual(r.status, "timeout")

    def test_codex_task_complete(self):
        shutil.copy(os.path.join(LOGS, "codex_task_complete.jsonl"), self.log)
        frames = [{"process": RUNNING_CODEX, "status": status("done", app="codex"), "screen": screen("codex_idle.txt")}]
        r, _ = self.run_watch(frames, tool="codex", frm=1)
        self.assertEqual((r.status, r.reply), ("turn_end", "Created `hello.txt`."))

    def test_status_fallback_after_working(self):
        frames = ([{"status": status("working"), "screen": screen("claude_working.txt")}] * 2
                  + [{"status": status("done"), "screen": screen("claude_idle_after_turn.txt")}])
        r, rex = self.run_watch(frames, log=False, frm=0, timeout=60)
        self.assertEqual((r.status, r.source), ("turn_end", "rex_status"))
        self.assertIn("without a log turn-end marker", r.reason)

    def test_no_status_fallback_without_seeing_work(self):
        frames = [{"status": status("done"), "screen": screen("claude_idle_after_turn.txt")}]
        r, _ = self.run_watch(frames, log=False, frm=0, timeout=20)
        self.assertEqual(r.status, "timeout")

    def test_log_resolved_later(self):
        frames = [{"status": status("working"), "screen": screen("claude_working.txt")},
                  {"status": status("working"), "screen": screen("claude_working.txt"),
                   "append": jsonl({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                                   {"type": "system", "subtype": "turn_duration"})}]
        rex = FakeRex(frames, self.log)
        clock = Clock(rex)
        seen = []

        def resolver():
            seen.append(1)
            return self.log if os.path.exists(self.log) else None

        r = W.watch(rex, T, "claude", None, 0, timeout=10, clock=clock.now, sleep=clock.sleep,
                    alive=lambda p: True, log_resolver=resolver)
        self.assertEqual((r.status, r.reply, r.log), ("turn_end", "hi", self.log))


class Exited(Base):
    def test_agent_exit_in_keep_open_pane(self):
        frames = [{"status": status("working"), "screen": "x"}, {"process": EXITED, "screen": "Resume this session"}]
        r, _ = self.run_watch(frames, log=False, frm=0)
        self.assertEqual((r.status, r.reason, r.exit_code), ("exited", "agent_exited", 0))
        self.assertEqual(r.code, 5)

    def test_agent_pid_gone_inside_shell(self):
        r, _ = self.run_watch([{"status": status("working"), "screen": "x"}], log=False, frm=0,
                              alive=lambda pid: False)
        self.assertEqual((r.status, r.reason), ("exited", "agent_exited"))

    def test_session_killed(self):
        frames = [{"status": status("working"), "screen": "x"}, {"gone": True}]
        r, _ = self.run_watch(frames, log=False, frm=0)
        self.assertEqual((r.status, r.reason), ("exited", "session_gone"))

    def test_no_agent_at_start(self):
        r, rex = self.run_watch([{"process": SHELL, "screen": "% "}], log=False, frm=0, start_timeout=3)
        self.assertEqual((r.status, r.reason), ("exited", "no_agent_process"))
        self.assertIn("-zsh", r.prompt)
        self.assertGreaterEqual(rex.i, 6, "waited --start-timeout for the agent")

    def test_agent_starts_after_shell_startup(self):
        trust = screen("claude_trust_folder.txt")
        frames = [{"process": SHELL, "screen": ""}] * 3 + [{"status": [], "screen": trust}]
        r, _ = self.run_watch(frames, log=False, frm=0)
        self.assertEqual((r.status, r.kind), ("needs_input", "trust"))

    def test_pane_already_exited_does_not_wait(self):
        r, rex = self.run_watch([{"process": EXITED, "screen": "bye"}], log=False, frm=0, start_timeout=60)
        self.assertEqual((r.status, r.reason, r.exit_code), ("exited", "no_agent_process", 0))
        self.assertEqual(rex.i, 0)

    def test_turn_end_wins_over_exit(self):
        n = self.seed("claude_bash_pending.jsonl")
        end = jsonl({"type": "assistant", "message": {"content": [{"type": "text", "text": "bye"}]}},
                    {"type": "system", "subtype": "turn_duration"})
        frames = [{"status": status("working"), "screen": "x"}, {"process": EXITED, "append": end}]
        r, _ = self.run_watch(frames, frm=n)
        self.assertEqual((r.status, r.reply), ("turn_end", "bye"))

    def test_rex_error_with_live_target_propagates(self):
        class Broken(FakeRex):
            def call(self, t, method, args=None):
                if self.i >= 1:
                    raise RexError(["block", "call"], 1, "server error")
                return super().call(t, method, args)

        rex = Broken([{"status": status("working"), "screen": "x"}])
        clock = Clock(rex)
        with self.assertRaises(RexError):
            W.watch(rex, T, "claude", None, 0, timeout=10, clock=clock.now, sleep=clock.sleep, alive=lambda p: True)


class Output(Base):
    def test_json(self):
        frames = [{"status": [], "screen": screen("claude_trust_folder.txt")}] * 3
        r, _ = self.run_watch(frames, log=False, frm=0)
        d = json.loads(r.to_json())
        self.assertEqual((d["status"], d["kind"], d["exit"], d["from"]), ("needs_input", "trust", 4, 0))
        self.assertEqual(d["menu"]["options"][1]["label"], "Yes, I trust this folder")

    def test_quoting_paths_with_spaces(self):
        r = W.WatchResult(status="timeout", tool="claude", session_id="s", block_id="b", label="my label",
                          log="/Users/me/Mobile Documents/x.jsonl", frm=3, lines=4, elapsed=1.0)
        d = dict(kv.split("=", 1) for kv in shlex.split(r.status_line()))
        self.assertEqual(d["log"], "/Users/me/Mobile Documents/x.jsonl")
        self.assertEqual(d["label"], "my label")


class AgentStatus(unittest.TestCase):
    def test_blocked_record_wins_and_other_apps_ignored(self):
        recs = [{"state": "working", "effective_app": "claude-code"},
                {"id": "x", "state": "blocked", "kind": "question", "effective_app": "claude-code"},
                {"state": "blocked", "effective_app": "cargo"}]
        self.assertEqual(W.agent_status(recs, "claude")["kind"], "question")
        self.assertIsNone(W.agent_status([{"state": "working", "effective_app": "cargo"}], "codex"))


if __name__ == "__main__":
    unittest.main()
