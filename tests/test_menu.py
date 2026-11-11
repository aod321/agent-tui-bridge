import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from atb import menu, screen
from atb.rex import Target

R = "─" * 80
E = "\x1b"
T = Target("session:s", "block:b", "probe")


class AskSim:
    """Simulates Claude Code's AskUserQuestion menu as observed in 2.1.322."""

    def __init__(self, questions, start=0, checks=None, stuck_digits=False):
        self.q = questions
        self.chip = len(questions) == 1 and not questions[0]["multi"]
        self.n_tabs = len(questions) + (0 if self.chip else 1)
        self.idx = start
        self.cursor = 1
        self.answers = [None] * len(questions)
        self.checks = checks or [[False] * len(q["options"]) for q in questions]
        self.text_mode = False
        self.buf = ""
        self.closed = None  # None while open, else "submitted" / "cancelled"
        self.keys = []
        self.stuck_digits = stuck_digits

    # -- rendering ---------------------------------------------------------
    def answered(self, i):
        return any(self.checks[i]) if self.q[i]["multi"] else self.answers[i] is not None

    def tokens(self):
        toks = [("☒" if self.answered(i) else "☐", q["header"]) for i, q in enumerate(self.q)]
        if not self.chip:
            toks.append(("✔", "Submit"))
        return toks

    def tabbar(self, vt=False):
        parts = []
        for i, (g, h) in enumerate(self.tokens()):
            tok = f"{g} {h}"
            if vt and i == self.idx:
                tok = f"{E}[38;2;0;0;0m{E}[48;2;177;185;249m {tok} {E}[0m"
            parts.append(tok)
        body = "  ".join(parts)
        return f" {body}" if self.chip else f"←  {body}  →"

    def page(self):
        if self.idx >= len(self.q):
            out = ["Review your answers", ""]
            if not all(self.answered(i) for i in range(len(self.q))):
                out += ["⚠ You have not answered all questions", ""]
            for i, q in enumerate(self.q):
                if self.answered(i):
                    ans = ", ".join(o for o, c in zip(q["options"], self.checks[i]) if c) if q["multi"] else self.answers[i]
                    out += [f" ● {q['question']}", f"   → {ans}"]
            out += ["", "Ready to submit your answers?", "", "❯ 1. Submit answers", "  2. Cancel"]
            return out
        q = self.q[self.idx]
        out = [q["question"], ""]
        n = len(q["options"])
        for k, label in enumerate(q["options"], 1):
            cur = "❯" if self.cursor == k else " "
            if q["multi"]:
                out += [f"{cur} {k}. [{'✔' if self.checks[self.idx][k - 1] else ' '}] {label}", f"         about {label}"]
            else:
                out += [f"{cur} {k}. {label}", f"     about {label}"]
        cur = "❯" if self.cursor == n + 1 else " "
        if q["multi"]:
            out += [f"{cur} {n + 1}. [ ] Type something", "     Next"]
        else:
            out.append(f"{cur} {n + 1}. {self.buf if self.text_mode and self.buf else 'Type something.'}")
        out += [R, f"  {n + 2}. Chat about this", ""]
        if self.text_mode:
            out.append("-- INSERT -- · Enter to select · ↑/↓ to navigate · ctrl+g to edit in VS Code")
        else:
            out.append("Enter to select · Tab/Arrow keys to navigate · Esc to cancel")
        return out

    def render(self, vt=False):
        if self.closed:
            return f"⏺ ok\n{R}\n❯ \n{R}\n  -- INSERT -- ⏸ manual mode on\n"
        return "\n".join(["⏺ I need some decisions.", "", R, self.tabbar(vt), ""] + self.page()) + "\n"

    # -- input -------------------------------------------------------------
    def advance(self):
        if self.chip:
            self.closed = "submitted"
        else:
            self.idx = min(self.idx + 1, self.n_tabs - 1)
            self.cursor = 1

    def key(self, k):
        self.keys.append(k)
        if self.closed:
            raise AssertionError(f"key {k!r} sent after the menu closed")
        on_submit = self.idx >= len(self.q)
        if k in ("left", "right"):
            if not self.text_mode:
                self.idx = max(0, self.idx - 1) if k == "left" else min(self.n_tabs - 1, self.idx + 1)
                self.cursor = 1
            return
        if k == "enter" and self.text_mode:
            self.answers[self.idx] = self.buf
            self.text_mode, self.buf = False, ""
            self.advance()
            return
        if k.isdigit():
            d = int(k)
            if self.stuck_digits:
                return
            if on_submit:
                if d == 1 and all(self.answered(i) for i in range(len(self.q))):
                    self.closed = "submitted"
                elif d == 2:
                    self.closed = "cancelled"
                return
            q = self.q[self.idx]
            n = len(q["options"])
            if 1 <= d <= n:
                if q["multi"]:
                    self.checks[self.idx][d - 1] = not self.checks[self.idx][d - 1]
                else:
                    self.answers[self.idx] = q["options"][d - 1]
                    self.advance()
            elif d == n + 1 and not q["multi"]:
                self.text_mode = True
                self.cursor = n + 1
            return
        raise AssertionError(f"unexpected key {k!r}")

    def text(self, s):
        if not self.text_mode:
            raise AssertionError("text typed outside the text field")
        self.buf += s


class ListSim:
    """A one-page menu answered by moving the cursor (permission, trust, /model)."""

    def __init__(self, title, options, numbered=True, footer="Esc to cancel · Tab to amend", frozen=False):
        self.title, self.options, self.numbered, self.footer = title, options, numbered, footer
        self.cursor = 1
        self.chosen = None
        self.keys = []
        self.frozen = frozen

    def render(self, vt=False):
        if self.chosen:
            return f"⏺ ok\n{R}\n❯ \n{R}\n"
        out = ["⏺ Bash(touch x)", R, f" {self.title}"]
        for k, label in enumerate(self.options, 1):
            cur = "❯" if self.cursor == k else " "
            out.append(f" {cur} {k}. {label}" if self.numbered else f" {cur} {label}")
        out += ["", f" {self.footer}"]
        return "\n".join(out) + "\n"

    def key(self, k):
        self.keys.append(k)
        if self.frozen:
            return
        if k == "down":
            self.cursor = min(len(self.options), self.cursor + 1)
        elif k == "up":
            self.cursor = max(1, self.cursor - 1)
        elif k == "enter":
            self.chosen = self.cursor
        else:
            raise AssertionError(f"unexpected key {k!r}")

    def text(self, s):
        raise AssertionError("no text field")


class SimRex:
    def __init__(self, sim):
        self.sim = sim
        self.sends = []  # each send_keys call, as a tuple

    def capture(self, t, fmt="text"):
        return self.sim.render(vt=fmt == "vt")

    def send_keys(self, t, *keys):
        self.sends.append(keys)
        for k in keys:
            self.sim.key(k)

    def send_text(self, t, s):
        self.sends.append(("text:" + s,))
        self.sim.text(s)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def kw():
    c = FakeClock()
    return {"clock": c.now, "sleep": c.sleep, "timeout": 1.0}


INCIDENT = [
    {"header": "Pruning", "question": "How far should I cut?", "multi": False,
     "options": ["3 main protocols per server (Recommended)", "Remove only the failing ones", "Each server keeps just 1–2"]},
    {"header": "lisa", "question": "What about lisa?", "multi": False, "options": ["Remove it", "Keep it"]},
    {"header": "Airport", "question": "What about the airport?", "multi": False, "options": ["Delete both", "Leave"]},
    {"header": "Shadowrocket", "question": "Which collections?", "multi": True, "options": ["Main", "Shadowrocket"]},
]


class SimSanity(unittest.TestCase):
    """The simulator renders screens the real parser understands."""

    def test_parser_reads_sim(self):
        sim = AskSim(INCIDENT)
        st = screen.analyze(sim.render())
        self.assertEqual(st.kind, "question")
        self.assertEqual([t.label for t in st.menu.tabs], ["Pruning", "lisa", "Airport", "Shadowrocket", "Submit"])
        self.assertEqual(screen.active_tab(sim.render(vt=True))[1], 0)


class ReadAll(unittest.TestCase):
    def test_reads_every_page_and_returns_to_first(self):
        sim = AskSim(INCIDENT)
        rex = SimRex(sim)
        pages = menu.read_all(rex, T, **kw())
        self.assertEqual([p.tab for p in pages], ["Pruning", "lisa", "Airport", "Shadowrocket", "Submit"])
        self.assertTrue(pages[0].prompt.startswith("←  ☐ Pruning  ☐ lisa"))
        self.assertIn("How far should I cut?", pages[0].prompt)
        self.assertIn("Which collections?", pages[3].prompt)
        self.assertTrue(pages[3].menu["multi_select"])
        self.assertTrue(pages[4].menu["review"])
        self.assertEqual(sim.idx, 0)
        self.assertEqual(sim.answers, [None] * 4, "reading must not answer")
        self.assertEqual(sim.keys, ["right"] * 4 + ["left"] * 4)
        self.assertNotIn("1", sim.keys)

    def test_starts_from_a_later_page(self):
        sim = AskSim(INCIDENT, start=2)
        pages = menu.read_all(SimRex(sim), T, **kw())
        self.assertEqual(len(pages), 5)
        self.assertEqual(sim.keys[:2], ["left", "left"])
        self.assertEqual(sim.idx, 0)

    def test_single_page_menu(self):
        sim = ListSim("Do you want to proceed?", ["Yes", "No"])
        pages = menu.read_all(SimRex(sim), T, **kw())
        self.assertEqual(len(pages), 1)
        self.assertEqual(sim.keys, [])

    def test_no_menu_raises(self):
        sim = AskSim(INCIDENT)
        sim.closed = "submitted"
        with self.assertRaises(menu.MenuError):
            menu.read_all(SimRex(sim), T, **kw())


class AnswerQuestions(unittest.TestCase):
    def test_incident_menu(self):
        sim = AskSim(INCIDENT, start=1)
        rex = SimRex(sim)
        done = menu.answer(rex, T, ["1", "1", "2", "1"], **kw())
        self.assertEqual(sim.closed, "submitted")
        self.assertEqual(sim.answers[:3], ["3 main protocols per server (Recommended)", "Remove it", "Leave"])
        self.assertEqual(sim.checks[3], [True, False])
        self.assertIn("→ 3 main protocols per server (Recommended)", done["prompt"])
        self.assertEqual(sim.keys, ["left", "1", "1", "2", "1", "right", "1"])

    def test_no_submit_stops_on_review(self):
        sim = AskSim(INCIDENT)
        done = menu.answer(SimRex(sim), T, ["2", "2", "1", "1,2"], submit=False, **kw())
        self.assertIsNone(sim.closed)
        self.assertEqual(sim.idx, 4)
        self.assertIn("Review your answers", done["prompt"])
        self.assertIn("→ Main, Shadowrocket", done["prompt"])

    def test_multiselect_unticks_what_is_not_wanted(self):
        qs = [{"header": "Pets", "question": "Pets?", "multi": True, "options": ["Cat", "Dog", "Fish"]}]
        sim = AskSim(qs, checks=[[True, False, False]])
        menu.answer(SimRex(sim), T, ["2,3"], **kw())
        self.assertEqual(sim.checks[0], [False, True, True])
        self.assertEqual(sim.keys[:3], ["1", "2", "3"])
        self.assertEqual(sim.closed, "submitted")

    def test_free_text(self):
        qs = [{"header": "Fruit", "question": "Fruit?", "multi": False, "options": ["Apple", "Pear"]},
              {"header": "Size", "question": "Size?", "multi": False, "options": ["S", "L"]}]
        sim = AskSim(qs)
        menu.answer(SimRex(sim), T, ["text:芒果 mango", "2"], **kw())
        self.assertEqual(sim.answers, ["芒果 mango", "L"])
        self.assertEqual(sim.closed, "submitted")

    def test_single_question_chip_submits_at_once(self):
        qs = [{"header": "Fruit", "question": "Fruit?", "multi": False, "options": ["Apple", "Pear"]}]
        sim = AskSim(qs)
        done = menu.answer(SimRex(sim), T, ["2"], **kw())
        self.assertEqual((sim.closed, sim.answers), ("submitted", ["Pear"]))
        self.assertEqual(sim.keys, ["2"])
        self.assertIn("Fruit?", done["prompt"])

    def test_wrong_answer_count(self):
        sim = AskSim(INCIDENT)
        with self.assertRaises(menu.MenuError) as cm:
            menu.answer(SimRex(sim), T, ["1", "1"], **kw())
        self.assertIn("4 question page(s)", str(cm.exception))
        self.assertEqual(sim.keys, [])

    def test_option_out_of_range(self):
        sim = AskSim(INCIDENT)
        with self.assertRaises(menu.MenuError):
            menu.answer(SimRex(sim), T, ["9", "1", "1", "1"], **kw())
        self.assertEqual(sim.answers, [None] * 4)

    def test_type_something_needs_text(self):
        sim = AskSim(INCIDENT)
        with self.assertRaises(menu.MenuError):
            menu.answer(SimRex(sim), T, ["4", "1", "1", "1"], **kw())

    def test_menu_that_ignores_keys_raises(self):
        sim = AskSim(INCIDENT, stuck_digits=True)
        with self.assertRaises(menu.MenuError) as cm:
            menu.answer(SimRex(sim), T, ["1", "1", "1", "1"], **kw())
        self.assertIn("expected page 2", str(cm.exception))

    def test_bad_token(self):
        with self.assertRaises(menu.MenuError):
            menu.parse_answer("yes")
        self.assertEqual(menu.parse_answer("1,3"), ("numbers", [1, 3]))
        self.assertEqual(menu.parse_answer("text:a,b"), ("text", "a,b"))


class AnswerList(unittest.TestCase):
    def test_permission_moves_cursor_then_enter(self):
        sim = ListSim("Do you want to proceed?", ["Yes", "Yes, and always allow", "Yes, and switch to auto mode", "No"])
        done = menu.answer(SimRex(sim), T, ["4"], **kw())
        self.assertEqual(sim.chosen, 4)
        self.assertEqual(sim.keys, ["down", "down", "down", "enter"])
        self.assertEqual(done["picked"], "4. No")

    def test_trust_screen_without_numbers(self):
        sim = ListSim("Accessing workspace:", ["No, exit", "Yes, I trust this folder"], numbered=False,
                      footer="Enter to confirm · Esc to cancel")
        done = menu.answer(SimRex(sim), T, ["2"], **kw())
        self.assertEqual(sim.chosen, 2)
        self.assertEqual(done["picked"], "2. Yes, I trust this folder")

    def test_custom_key(self):
        class S(ListSim):
            def key(self, k):
                if k == "s":
                    self.keys.append(k)
                    self.chosen = self.cursor
                    return
                super().key(k)

        sim = S("Select model", ["Default", "Opus", "Sonnet"], footer="Enter to set as default · s to use this session only · Esc to cancel")
        sim.cursor = 2
        menu.answer(SimRex(sim), T, ["3"], key="s", **kw())
        self.assertEqual(sim.keys, ["down", "s"])
        self.assertEqual(sim.chosen, 3)

    def test_cursor_that_does_not_move_raises(self):
        sim = ListSim("Do you want to proceed?", ["Yes", "No"], frozen=True)
        with self.assertRaises(menu.MenuError):
            menu.answer(SimRex(sim), T, ["2"], **kw())
        self.assertNotIn("enter", sim.keys)

    def test_one_answer_only(self):
        sim = ListSim("Do you want to proceed?", ["Yes", "No"])
        with self.assertRaises(menu.MenuError):
            menu.answer(SimRex(sim), T, ["1", "2"], **kw())


if __name__ == "__main__":
    unittest.main()
