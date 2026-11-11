import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from atb import screen

FIX = os.path.join(HERE, "fixtures", "screens")


def load(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def analyze(name: str) -> screen.ScreenState:
    return screen.analyze(load(name))


class IncidentMenu(unittest.TestCase):
    """The four-question menu that made `agent-log wait` hang for 13 minutes."""

    def test_detected_as_question(self):
        st = analyze("claude_ask_pruning_page1.txt")
        self.assertTrue(st.needs_input)
        self.assertEqual(st.kind, "question")
        self.assertIn("Enter to select · Tab/Arrow keys to navigate · Esc to cancel", st.reason)

    def test_tabs_and_options(self):
        m = analyze("claude_ask_pruning_page1.txt").menu
        self.assertEqual([t.label for t in m.tabs], ["Pruning", "lisa", "Airport", "Shadowrocket", "Submit"])
        self.assertEqual([t.submit for t in m.tabs], [False, False, False, False, True])
        self.assertFalse(any(t.answered for t in m.tabs))
        self.assertTrue(m.title.startswith("Node pruning for the main profile."))
        self.assertEqual([o.number for o in m.options], [1, 2, 3, 4, 5])
        self.assertEqual(m.options[0].label, "3 main protocols per server (Recommended)")
        self.assertTrue(m.options[0].cursor)
        self.assertEqual(m.options[1].description,
                         "Drop the protocols that fail the test and keep the rest. Around 16\nnodes.")
        self.assertEqual(m.options[3].label, "Type something.")
        self.assertEqual(m.options[4].label, "Chat about this")
        self.assertFalse(m.multi_select)

    def test_prompt_is_verbatim_panel_only(self):
        st = analyze("claude_ask_pruning_page1.txt")
        lines = st.prompt.split("\n")
        self.assertEqual(lines[0], "←  ☐ Pruning  ☐ lisa  ☐ Airport  ☐ Shadowrocket  ✔ Submit  →")
        self.assertEqual(lines[-1], "Enter to select · Tab/Arrow keys to navigate · Esc to cancel")
        self.assertNotIn("All three servers", st.prompt)
        # the panel is copied unchanged, including the rule above "Chat about this"
        self.assertIn("─" * 80 + "\n  5. Chat about this", st.prompt)

    def test_active_tab_from_vt(self):
        tabs, idx = screen.active_tab(load("claude_ask_pruning_page1.vt"))
        self.assertEqual(idx, 0)
        self.assertEqual([t.label for t in tabs], ["Pruning", "lisa", "Airport", "Shadowrocket", "Submit"])
        self.assertEqual([t.active for t in tabs], [True, False, False, False, False])
        _tabs, idx = screen.active_tab(load("claude_ask_pruning_page3.vt"))
        self.assertEqual(idx, 2)


class ClaudeQuestionPages(unittest.TestCase):
    def test_single_select_page(self):
        st = analyze("claude_ask_multi_page1.txt")
        self.assertEqual(st.kind, "question")
        m = st.menu
        self.assertEqual([t.label for t in m.tabs], ["Color", "Pets", "Size", "Submit"])
        self.assertEqual(m.title, "Which color do you prefer?")
        self.assertEqual([o.label for o in m.options], ["Red", "Green", "Blue", "Type something.", "Chat about this"])
        self.assertEqual(m.options[0].description, "A warm, bold color.")
        self.assertNotIn("This is a UI test", st.prompt)

    def test_multi_select_page(self):
        m = analyze("claude_ask_multi_page2_multiselect.txt").menu
        self.assertTrue(m.multi_select)
        self.assertEqual([o.checked for o in m.options[:4]], [False, False, False, False])
        self.assertEqual(m.options[0].label, "Cat")
        self.assertEqual(m.options[0].description, "Independent and low-maintenance.")
        self.assertTrue(m.has_next_button)
        self.assertIsNone(m.options[4].checked)  # "Chat about this"

    def test_submit_page_without_footer(self):
        st = analyze("claude_ask_multi_submit_unanswered.txt")
        self.assertTrue(st.needs_input)
        self.assertEqual(st.reason, "submit page")
        self.assertEqual(st.kind, "question")
        self.assertTrue(st.menu.review)
        self.assertTrue(st.menu.unanswered_warning)
        self.assertEqual([o.label for o in st.menu.options], ["Submit answers", "Cancel"])

    def test_submit_page_answered(self):
        st = analyze("claude_ask_multi_submit_answered.txt")
        self.assertTrue(st.menu.review)
        self.assertFalse(st.menu.unanswered_warning)
        self.assertTrue(all(t.answered for t in st.menu.tabs if not t.submit))
        self.assertIn("→ Cat, Fish", st.prompt)

    def test_submit_tab_highlight_in_real_vt(self):
        tabs, idx = screen.active_tab(load("claude_ask_multi_submit_unanswered.vt"))
        self.assertEqual(idx, 3)
        self.assertTrue(tabs[3].submit)

    def test_single_question_chip(self):
        st = analyze("claude_ask_single.txt")
        self.assertEqual(st.kind, "question")
        self.assertEqual([t.label for t in st.menu.tabs], ["Fruit"])
        self.assertFalse(st.menu.tabs[0].submit)
        self.assertEqual(st.prompt.split("\n")[0], " ☐ Fruit")

    def test_free_text_field_focused(self):
        st = analyze("claude_ask_free_text.txt")
        self.assertTrue(st.needs_input)
        cur = [o for o in st.menu.options if o.cursor]
        self.assertEqual([(o.number, o.label) for o in cur], [(3, "芒果 mango")])

    def test_single_question_multiselect_has_submit_page(self):
        m = analyze("claude_ask_single_multiselect.txt").menu
        self.assertEqual([t.label for t in m.tabs], ["Tools", "Submit"])
        self.assertTrue(m.tabs[0].answered)
        self.assertEqual([o.checked for o in m.options[:4]], [True, False, True, False])
        self.assertTrue(m.has_next_button)


class OtherPrompts(unittest.TestCase):
    def test_claude_permission(self):
        st = analyze("claude_permission_bash.txt")
        self.assertEqual(st.kind, "permission")
        self.assertTrue(st.prompt.startswith(" Bash command"))
        self.assertTrue(st.prompt.endswith(" Esc to cancel · Tab to amend"))
        m = st.menu
        self.assertIn("Do you want to proceed?", m.title)
        self.assertEqual([o.label for o in m.options][0], "Yes")
        self.assertEqual(m.options[3].label, "No")
        self.assertIn("project", m.options[1].description)  # wrapped label continuation
        self.assertTrue(m.options[0].cursor)

    def test_claude_trust_folder_unnumbered(self):
        st = analyze("claude_trust_folder.txt")
        self.assertEqual(st.kind, "trust")
        m = st.menu
        self.assertEqual([(o.index, o.number, o.label, o.cursor) for o in m.options],
                         [(1, None, "No, exit", True), (2, None, "Yes, I trust this folder", False)])
        self.assertIn("Accessing workspace:", m.title)
        self.assertNotIn("No, exit", m.title)

    def test_claude_trust_cursor_moved(self):
        m = analyze("claude_trust_folder_cursor_on_yes.txt").menu
        self.assertEqual([(o.label, o.cursor) for o in m.options],
                         [("No, exit", False), ("Yes, I trust this folder", True)])
        self.assertNotIn("No, exit", m.title)

    def test_claude_model_menu(self):
        st = analyze("claude_model_menu.txt")
        self.assertEqual(st.kind, "menu")
        self.assertTrue(st.prompt.lstrip().startswith("Select model"))
        m = st.menu
        self.assertEqual([o.number for o in m.options], [1, 2, 3])
        self.assertEqual(m.options[0].label, "Default (recommended)")
        self.assertEqual(m.options[1].label, "Opus 5.5 ✔")
        self.assertTrue(m.options[1].cursor)
        self.assertEqual(m.options[2].label, "Sonnet 5.5")

    def test_codex_exec_approval(self):
        st = analyze("codex_exec_approval.txt")
        self.assertEqual(st.kind, "permission")
        self.assertTrue(st.prompt.startswith("  Would you like to run the following command?"))
        self.assertNotIn("• Running", st.prompt)
        self.assertIn("$ touch hello.txt", st.prompt)
        m = st.menu
        self.assertEqual([o.label for o in m.options],
                         ["Yes, proceed (y)",
                          "Yes, and don't ask again for commands that start with `touch hello.txt` (p)",
                          "No, and tell Codex what to do differently (esc)"])
        self.assertTrue(m.options[0].cursor)
        self.assertEqual(m.footer, "Press enter to confirm or esc to cancel")

    def test_codex_model_menu(self):
        st = analyze("codex_model_menu.txt")
        self.assertEqual(st.kind, "menu")
        self.assertTrue(st.prompt.startswith("  Select Model and Effort"))
        self.assertNotIn("Worked for", st.prompt)
        m = st.menu
        self.assertEqual(len(m.options), 8)
        self.assertEqual((m.options[0].label, m.options[0].description),
                         ("GPT-6.1-Sol", "Latest workhorse model for coding and everyday work."))
        self.assertTrue(m.options[1].cursor)

    def test_codex_hooks_review(self):
        st = analyze("codex_hooks_review.txt")
        self.assertEqual(st.kind, "trust")
        self.assertEqual(len(st.menu.options), 3)
        self.assertIn("Hooks need review", st.prompt)


class NotWaiting(unittest.TestCase):
    def test_idle_and_working_screens(self):
        for name in ("claude_idle_after_turn.txt", "claude_working.txt", "codex_idle.txt", "codex_working.txt"):
            with self.subTest(name=name):
                self.assertFalse(analyze(name).needs_input)

    def test_reply_quoting_a_menu_is_not_a_menu(self):
        self.assertFalse(analyze("claude_idle_quoting_menu.txt").needs_input)

    def test_blank(self):
        self.assertFalse(screen.analyze("\n\n   \n").needs_input)

    def test_busy(self):
        self.assertTrue(screen.looks_busy(screen.normalize(load("claude_working.txt"))))
        self.assertTrue(screen.looks_busy(screen.normalize(load("codex_working.txt"))))
        self.assertFalse(screen.looks_busy(screen.normalize(load("claude_idle_after_turn.txt"))))
        self.assertFalse(screen.looks_busy(screen.normalize(load("codex_idle.txt"))))


class VT(unittest.TestCase):
    def test_cursor_forward_becomes_spaces(self):
        cells = screen.vt_cells("a\x1b[3Cb")
        self.assertEqual("".join(c for c, _ in cells), "a   b")

    def test_background_tracking(self):
        cells = screen.vt_cells("x\x1b[48;2;1;2;3my\x1b[0mz")
        self.assertEqual([bg for _, bg in cells], [None, "1,2,3", None])

    def test_inverse_video_counts_as_highlight(self):
        tabs, idx = screen.active_tab("←  ☐ A  \x1b[7m☐ B\x1b[27m  ✔ Submit  →\n")
        self.assertEqual(idx, 1)

    def test_no_highlight_raises(self):
        with self.assertRaises(ValueError):
            screen.active_tab("←  ☐ A  ☐ B  ✔ Submit  →\n")

    def test_no_tabbar_raises(self):
        with self.assertRaises(ValueError):
            screen.active_tab("hello\n")


if __name__ == "__main__":
    unittest.main()
