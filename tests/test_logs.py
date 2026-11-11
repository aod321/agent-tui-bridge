import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from atb import logs

FIX = os.path.join(HERE, "fixtures", "logs")


def rows(name):
    return logs.rows(os.path.join(FIX, name))


class ClaudeLogs(unittest.TestCase):
    def test_turn_end_and_reply(self):
        rs = rows("claude_turn_end.jsonl")
        self.assertTrue(any(logs.is_end("claude", r) for r in rs))
        self.assertEqual(logs.last_reply("claude", rs), "Done: pruned to 7 nodes.")
        self.assertEqual(logs.pending_calls("claude", rs), [])

    def test_pending_ask_user_question(self):
        pend = logs.pending_calls("claude", rows("claude_ask_pending.jsonl"))
        self.assertEqual(len(pend), 1, "the api-request-blob replay must not count")
        p = pend[0]
        self.assertEqual((p.tool_name, p.call_id, p.user_input), ("AskUserQuestion", "toolu_ask01", True))
        self.assertEqual([q["header"] for q in p.questions], ["Pruning", "lisa", "Airport", "Shadowrocket"])

    def test_answered_question_is_not_pending(self):
        rs = rows("claude_ask_answered.jsonl")
        self.assertEqual(logs.pending_calls("claude", rs), [])
        self.assertTrue(any(logs.is_end("claude", r) for r in rs))

    def test_question_not_logged_yet(self):
        # Claude Code 2.1.322 can show the menu before the tool_use row exists.
        rs = rows("claude_ask_not_logged_yet.jsonl")
        self.assertEqual(logs.pending_calls("claude", rs), [])
        self.assertFalse(any(logs.is_end("claude", r) for r in rs))

    def test_pending_bash_is_not_a_question(self):
        pend = logs.pending_calls("claude", rows("claude_bash_pending.jsonl"))
        self.assertEqual([(p.tool_name, p.user_input) for p in pend], [("Bash", False)])

    def test_interrupted_turn_ends(self):
        rs = rows("claude_interrupted.jsonl")
        self.assertEqual(logs.pending_calls("claude", rs), [])
        self.assertTrue(any(logs.is_end("claude", r) for r in rs))
        self.assertEqual(logs.last_reply("claude", rs), "")

    def test_sidechain_ignored(self):
        self.assertEqual(logs.pending_calls("claude", rows("claude_sidechain_ask.jsonl")), [])

    def test_format_questions(self):
        p = logs.pending_calls("claude", rows("claude_ask_pending.jsonl"))[0]
        text = logs.format_questions(p.questions)
        lines = text.split("\n")
        self.assertEqual(lines[0], "Q1 [Pruning] (single-select) Node pruning for the main profile. How far should I cut?")
        self.assertEqual(lines[1], "  1. 3 main protocols per server (Recommended) — Around 6–8 nodes.")
        self.assertIn("Q4 [Shadowrocket] (multi-select) Should I also change the Shadowrocket collection?", lines)


class CodexLogs(unittest.TestCase):
    def test_task_complete(self):
        rs = rows("codex_task_complete.jsonl")
        end = [r for r in rs if logs.is_end("codex", r)]
        self.assertEqual(len(end), 1)
        self.assertEqual(logs.end_reason("codex", end[0]), "completed")
        self.assertEqual(logs.last_reply("codex", rs), "Created `hello.txt`.")
        self.assertEqual(logs.pending_calls("codex", rs), [])

    def test_exec_waiting(self):
        pend = logs.pending_calls("codex", rows("codex_exec_pending.jsonl"))
        self.assertEqual([(p.tool_name, p.user_input) for p in pend], [("exec", False)])

    def test_request_user_input(self):
        pend = logs.pending_calls("codex", rows("codex_request_user_input.jsonl"))
        self.assertEqual(len(pend), 1)
        self.assertTrue(pend[0].user_input)
        self.assertEqual(pend[0].questions[0]["question"], "Which files should I touch?")
        self.assertIn("Q1 [Scope] (single-select) Which files should I touch?", logs.format_questions(pend[0].questions))

    def test_turn_aborted(self):
        rs = rows("codex_turn_aborted.jsonl")
        end = [r for r in rs if logs.is_end("codex", r)]
        self.assertEqual(logs.end_reason("codex", end[0]), "aborted")


class Tail(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "s.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text, mode="a"):
        with open(self.path, mode) as fh:
            fh.write(text)

    def test_incremental_and_partial_line(self):
        self.write('{"n":1}\n{"n":2}\n', "w")
        t = logs.LogTail(self.path, 1)
        self.assertEqual(t.poll(1.0), [{"n": 2}])
        self.write('{"n":3}\n{"n":')
        self.assertEqual(t.poll(2.0), [{"n": 3}])
        self.assertEqual(t.lines, 3)
        self.write('4}\n')
        self.assertEqual(t.poll(3.0), [{"n": 4}])
        self.assertEqual(t.last_change, 3.0)
        self.assertEqual([r["n"] for r in t.rows], [2, 3, 4])

    def test_missing_file_then_created(self):
        t = logs.LogTail(self.path, 0)
        self.assertEqual(t.poll(1.0), [])
        self.write('{"n":1}\n', "w")
        self.assertEqual(t.poll(2.0), [{"n": 1}])

    def test_from_past_end_raises(self):
        self.write('{"n":1}\n', "w")
        with self.assertRaises(ValueError):
            logs.LogTail(self.path, 5).poll(1.0)

    def test_corrupt_line_raises(self):
        self.write('{"n":1}\nnot json\n', "w")
        with self.assertRaises(json.JSONDecodeError):
            logs.LogTail(self.path, 0).poll(1.0)


class Locate(unittest.TestCase):
    def test_project_key(self):
        self.assertEqual(logs.claude_project_key("/Users/me/My Docs/a_b.c"), "-Users-me-My-Docs-a-b-c")
        self.assertEqual(logs.claude_project_key("/Users/me/论文"), "-Users-me---")
        self.assertEqual(logs.claude_project_key("/Users/me/iCloud~md~obsidian"), "-Users-me-iCloud-md-obsidian")

    def test_claude_log_for_pid(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}):
            os.makedirs(os.path.join(home, ".claude", "sessions"))
            self.assertIsNone(logs.claude_log_for_pid(4242))
            with open(os.path.join(home, ".claude", "sessions", "4242.json"), "w") as fh:
                json.dump({"pid": 4242, "sessionId": "abc", "cwd": "/Users/me/proj x"}, fh)
            # not written yet: the deterministic path
            self.assertEqual(logs.claude_log_for_pid(4242),
                             os.path.join(home, ".claude", "projects", "-Users-me-proj-x", "abc.jsonl"))
            # written: found by session id wherever it is
            d = os.path.join(home, ".claude", "projects", "elsewhere")
            os.makedirs(d)
            open(os.path.join(d, "abc.jsonl"), "w").close()
            self.assertEqual(logs.claude_log_for_pid(4242), os.path.join(d, "abc.jsonl"))


if __name__ == "__main__":
    unittest.main()
