"""The scripts in bin/ start, and agent-log keeps its old behaviour."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin")
LOGS = os.path.join(HERE, "fixtures", "logs")


def run(*args, timeout=20):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=timeout)


class Help(unittest.TestCase):
    def test_help(self):
        for name in ("agent-watch", "agent-menu", "agent-log"):
            with self.subTest(name=name):
                p = run(os.path.join(BIN, name), "--help")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("usage", p.stdout.lower())

    def test_watch_requires_from(self):
        p = run(os.path.join(BIN, "agent-watch"), "claude", "-s", "x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--from", p.stderr)


class AgentLogCompat(unittest.TestCase):
    log = os.path.join(LOGS, "claude_turn_end.jsonl")

    def test_mark(self):
        p = run(os.path.join(BIN, "agent-log"), "mark", self.log)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "7"))

    def test_wait_prints_reply_only(self):
        p = run(os.path.join(BIN, "agent-log"), "wait", "claude", self.log, "--from", "0", "--timeout", "2")
        self.assertEqual((p.returncode, p.stdout), (0, "Done: pruned to 7 nodes.\n"))

    def test_wait_timeout_exit_3(self):
        p = run(os.path.join(BIN, "agent-log"), "wait", "claude", self.log, "--from", "7", "--timeout", "1")
        self.assertEqual(p.returncode, 3)
        self.assertIn("agent-watch", p.stderr)

    def test_show(self):
        p = run(os.path.join(BIN, "agent-log"), "show", "claude", self.log)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "[user] Clean up the proxy profile.\n\n[assistant] Done: pruned to 7 nodes.\n\n")

    def test_model(self):
        p = run(os.path.join(BIN, "agent-log"), "model", "claude", self.log)
        self.assertEqual(p.stdout.strip(), "claude-opus-5-5")

    def test_codex_wait(self):
        p = run(os.path.join(BIN, "agent-log"), "wait", "codex", os.path.join(LOGS, "codex_task_complete.jsonl"),
                "--from", "1", "--timeout", "2")
        self.assertEqual(p.stdout, "Created `hello.txt`.\n")


if __name__ == "__main__":
    unittest.main()
