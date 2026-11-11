"""Read and answer on-screen menus of Claude Code and Codex through Rex keys.

Facts this relies on (checked with Claude Code 2.1.322 and Codex 0.167):

* A multi-question AskUserQuestion menu shows a tab bar
  "←  ☐ Q1  ☐ Q2  ✔ Submit  →". Left/Right move one page and stop at the
  ends (no wrap). The highlighted tab is only visible in a VT capture.
* On a single-select page a digit picks that option and moves to the next
  page. On a multi-select page a digit toggles that checkbox and stays; Right
  moves on. The Submit page lists the answers; "1. Submit answers" sends them.
* A single question with single-select has a chip "☐ Header" and no Submit
  page: a digit answers and submits at once.
* "Type something": press its number, type the text, press Enter.
* Other menus (permission, trust folder, /model, Codex approvals) are answered
  by moving the cursor to the option and pressing Enter. The trust screen has
  no option numbers, so positions are used.

Every key press is followed by a capture that checks the expected change; a
change that does not happen raises MenuError with the screen.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from . import screen
from .rex import Rex, Target


class MenuError(RuntimeError):
    pass


@dataclass
class Page:
    index: int
    tab: str | None
    prompt: str
    menu: dict

    def to_dict(self) -> dict:
        return asdict(self)


class Driver:
    def __init__(self, rex: Rex, target: Target, timeout: float = 4.0, step: float = 0.15,
                 clock=time.monotonic, sleep=time.sleep):
        self.rex, self.t = rex, target
        self.timeout, self.step = timeout, step
        self.clock, self.sleep = clock, sleep

    # -- observation -------------------------------------------------------
    def state(self) -> screen.ScreenState:
        return screen.analyze(self.rex.capture(self.t))

    def tab_index(self) -> tuple[list[screen.Tab], int]:
        return screen.active_tab(self.rex.capture(self.t, "vt"))

    def wait(self, what: str, pred):
        """Poll the screen until pred(state) is truthy; raise MenuError on timeout."""
        deadline = self.clock() + self.timeout
        while True:
            text = self.rex.capture(self.t)
            st = screen.analyze(text)
            got = pred(st)
            if got:
                return st
            if self.clock() >= deadline:
                tail = "\n".join(screen.normalize(text)[-25:])
                raise MenuError(f"timed out waiting for {what}. Screen:\n{tail}")
            self.sleep(self.step)

    def wait_tab(self, want: int):
        deadline = self.clock() + self.timeout
        while True:
            _tabs, idx = self.tab_index()
            if idx == want:
                return
            if self.clock() >= deadline:
                raise MenuError(f"menu stayed on page {idx + 1}; expected page {want + 1}")
            self.sleep(self.step)

    def goto(self, want: int) -> None:
        _tabs, idx = self.tab_index()
        if idx > want:
            self.rex.send_keys(self.t, *(["left"] * (idx - want)))
        elif idx < want:
            self.rex.send_keys(self.t, *(["right"] * (want - idx)))
        self.wait_tab(want)

    def require_prompt(self) -> screen.ScreenState:
        st = self.state()
        if not st.needs_input or st.menu is None:
            raise MenuError("no menu or prompt is waiting on screen")
        return st


def read_all(rex: Rex, target: Target, **kw) -> list[Page]:
    """Capture every page of the menu on screen without answering, then return to page 1."""
    d = Driver(rex, target, **kw)
    st = d.require_prompt()
    tabs = st.menu.tabs
    if len(tabs) <= 1:
        return [Page(0, tabs[0].label if tabs else None, st.prompt, st.menu.to_dict())]
    pages = []
    d.goto(0)
    for i in range(len(tabs)):
        if i:
            d.rex.send_keys(target, "right")
            d.wait_tab(i)
        st = d.state()
        if not st.needs_input:
            raise MenuError(f"page {i + 1} shows no prompt")
        pages.append(Page(i, tabs[i].label, st.prompt, st.menu.to_dict()))
    d.goto(0)
    return pages


def parse_answer(token: str):
    """'2' -> ('numbers', [2]); '1,3' -> ('numbers', [1, 3]); 'text:foo' -> ('text', 'foo')."""
    if token.startswith("text:"):
        return "text", token[5:]
    try:
        nums = [int(x) for x in token.split(",") if x.strip()]
    except ValueError:
        raise MenuError(f"bad answer {token!r}: use N, N,M for multi-select, or text:WORDS")
    if not nums:
        raise MenuError(f"bad answer {token!r}")
    return "numbers", nums


def _option(menu: screen.Menu, n: int) -> screen.Option:
    numbered = [o for o in menu.options if o.number is not None]
    pool = numbered if numbered else menu.options
    key = (lambda o: o.number) if numbered else (lambda o: o.index)
    hits = [o for o in pool if key(o) == n]
    if not hits:
        have = ", ".join(f"{key(o)}={o.label}" for o in pool)
        raise MenuError(f"no option {n} on this page (options: {have})")
    return hits[0]


def answer(rex: Rex, target: Target, answers: list[str], submit: bool = True, key: str = "enter", **kw) -> dict:
    """Answer the menu on screen.

    Returns {"prompt": the prompt as it was answered (the review page for a
    multi-question menu), "picked": "N. label" for a single-page menu}.
    """
    d = Driver(rex, target, **kw)
    st = d.require_prompt()
    if st.menu.tabs:
        return _answer_questions(d, st, answers, submit)
    if len(answers) != 1:
        raise MenuError(f"this {st.kind} prompt takes one answer, got {len(answers)}")
    kind, val = parse_answer(answers[0])
    if kind != "numbers" or len(val) != 1:
        raise MenuError("this prompt takes a single option number")
    return _pick(d, st, val[0], key)


def _pick(d: Driver, st: screen.ScreenState, n: int, key: str) -> dict:
    menu = st.menu
    want = _option(menu, n)
    cur = next((o for o in menu.options if o.cursor), None)
    if cur is None:
        raise MenuError("cannot see the cursor on this menu")
    delta = want.index - cur.index
    if delta:
        d.rex.send_keys(d.t, *(["down"] * delta if delta > 0 else ["up"] * -delta))
        d.wait(f"cursor on option {n}", lambda s: s.menu is not None and any(
            o.cursor and o.index == want.index for o in s.menu.options))
    before = st.prompt
    d.rex.send_keys(d.t, key)
    d.wait("the menu to close or change", lambda s: not s.needs_input or s.prompt != before)
    return {"prompt": before, "picked": f"{n}. {want.label}"}


def _answer_questions(d: Driver, st: screen.ScreenState, answers: list[str], submit: bool) -> str:
    tabs = st.menu.tabs
    qtabs = [t for t in tabs if not t.submit]
    has_submit = any(t.submit for t in tabs)
    if len(answers) != len(qtabs):
        labels = ", ".join(t.label for t in qtabs)
        raise MenuError(f"menu has {len(qtabs)} question page(s) ({labels}); got {len(answers)} answer(s)")
    specs = [parse_answer(a) for a in answers]
    if has_submit:
        d.goto(0)
    for i, (kind, val) in enumerate(specs):
        page = d.state()
        menu = page.menu
        if not page.needs_input or menu is None:
            raise MenuError(f"page {i + 1} shows no prompt")
        last = i == len(specs) - 1
        advance_to = i + 1 if has_submit else None
        if menu.multi_select:
            if kind != "numbers":
                raise MenuError(f"page {i + 1} is multi-select; free text there is not supported")
            want = set(val)
            for n in want:
                _option(menu, n)
            for o in menu.options:
                if o.checked is None or o.number is None:
                    continue
                if (o.number in want) != o.checked:
                    target_state = not o.checked
                    d.rex.send_keys(d.t, str(o.number))
                    d.wait(f"option {o.number} to toggle", lambda s, n=o.number, v=target_state: s.menu is not None
                           and any(x.number == n and x.checked == v for x in s.menu.options))
            if not has_submit:
                raise MenuError("multi-select page without a Submit page; answer it with term-key")
            d.rex.send_keys(d.t, "right")
            d.wait_tab(advance_to)
            continue
        if kind == "numbers":
            if len(val) != 1:
                raise MenuError(f"page {i + 1} is single-select; give one number")
            o = _option(menu, val[0])
            if o.label.lower().startswith("type something"):
                raise MenuError(f"option {val[0]} on page {i + 1} is free text; answer with text:WORDS")
            d.rex.send_keys(d.t, str(val[0]))
        else:
            o = next((x for x in menu.options if x.label.lower().startswith("type something")), None)
            if o is None or o.number is None:
                raise MenuError(f"page {i + 1} has no 'Type something' option")
            d.rex.send_keys(d.t, str(o.number))
            d.wait("the text field", lambda s, n=o.number: s.menu is not None
                   and any(x.cursor and x.number == n for x in s.menu.options))
            d.rex.send_text(d.t, val)
            d.rex.send_keys(d.t, "enter")
        if advance_to is not None:
            d.wait_tab(advance_to)
        elif last:
            before = page.prompt
            d.wait("the answer to be taken", lambda s: not s.needs_input or s.prompt != before)
            return {"prompt": before, "picked": None}
    review = d.wait("the Submit page", lambda s: s.menu is not None and s.menu.review)
    if review.menu.unanswered_warning:
        raise MenuError("the Submit page says not every question is answered:\n" + review.prompt)
    if submit:
        o = next((x for x in review.menu.options if x.label == "Submit answers"), None)
        if o is None or o.number is None:
            raise MenuError("no 'Submit answers' option on the Submit page:\n" + review.prompt)
        d.rex.send_keys(d.t, str(o.number))
        d.wait("the menu to close", lambda s: not s.needs_input or not (s.menu and s.menu.review))
    return {"prompt": review.prompt, "picked": None}
