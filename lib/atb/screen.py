"""Read Claude Code and Codex CLI screens captured with `rex capture`.

Everything here is a pure function of captured text (or VT bytes decoded to
str), so the heuristics can be tested against fixtures.

The signal we look for is "the program is showing a menu or prompt and is
waiting for a key". Both CLIs end such screens with a key-hint footer
("Enter to select · ... · Esc to cancel", "Press enter to confirm or esc to
cancel", "enter confirm · esc skip"). Only the last two non-blank lines are
checked for a footer, so an agent that merely *quotes* a footer in its reply
(followed by its normal input box) is not mistaken for a waiting prompt.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

SOLID_RULE_RE = re.compile(r"^\s*[─━▔═]{20,}\s*$")
DASHED_RULE_RE = re.compile(r"^\s*[╌┄┈-]{20,}\s*$")
# "❯ 1. Red", "  2. Green", "› 1. Yes, proceed (y)", "   ↓ 3.  Sonnet 5.5   ..."
OPTION_RE = re.compile(
    r"^(?P<indent>\s*)(?P<cursor>[❯›>])?\s*(?P<scroll>[↑↓])?\s*(?P<num>\d{1,2})\.\s+(?P<body>\S.*?)\s*$"
)
CURSOR_RE = re.compile(r"^(?P<indent>\s*)[❯›]\s+(?P<body>\S.*?)\s*$")
CHECKBOX_RE = re.compile(r"^\[(?P<mark>[ ✔✓xX×])\]\s*(?P<label>.*)$")
TAB_TOKEN_RE = re.compile(r"(?P<glyph>[☐☒✔☑✓])\s(?P<label>\S.*?)(?=\s{2,}[☐☒✔☑✓→]|\s*$)")
TABBAR_RE = re.compile(r"^\s*(?:←\s+)?[☐☒✔☑✓]\s\S.*?(?:\s+→)?\s*$")
SUBMIT_RE = re.compile(r"^\s*(?:[❯›]\s*)?\d+\.\s+Submit answers\s*$")
# Lines that belong to the transcript, not to a Codex prompt panel.
CODEX_STOP_RE = re.compile(r"^(?:[•⏺✻]|›\s+(?!\d+\.)|\s*└|\s*(?:─\s*)?Worked for\b)")

FOOTER_RES = [
    re.compile(r"\benter to (?:select|confirm|submit|continue)\b", re.I),
    re.compile(r"\besc to (?:cancel|go back|exit)\b", re.I),
    re.compile(r"\bpress enter to (?:confirm|continue)\b", re.I),
    # Codex: "enter confirm · esc skip", "enter select · esc back"
    re.compile(r"\benter\b[^·•|\n]{0,30}[·•|]\s*esc\b", re.I),
]

TRUST_RE = re.compile(
    r"trust (?:this|the) (?:folder|files|contents|directory)|do you trust|one you trust|hooks need review", re.I
)
PERMISSION_RE = re.compile(
    r"do you want to (?:proceed|make this edit|create|delete|overwrite|allow|run)"
    r"|would you like to (?:run|make|apply|allow)|\ballow\b.{1,40}\bto\b|\bapprove\b|\bpermission\b",
    re.I,
)


@dataclass
class Tab:
    label: str
    glyph: str
    answered: bool
    submit: bool
    active: bool | None = None  # only known from a VT capture


@dataclass
class Option:
    index: int  # 1-based position in the list
    number: int | None  # the number printed on screen, if any
    label: str
    description: str = ""
    cursor: bool = False
    checked: bool | None = None  # multi-select checkbox state


@dataclass
class Menu:
    tabs: list[Tab]
    title: str
    options: list[Option]
    footer: str
    multi_select: bool
    review: bool  # the "Review your answers" / Submit page of a multi-question menu
    unanswered_warning: bool
    has_next_button: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScreenState:
    needs_input: bool
    kind: str | None = None  # question | permission | trust | menu
    reason: str = ""
    prompt: str = ""  # verbatim screen region holding the prompt
    menu: Menu | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def normalize(text: str) -> list[str]:
    """Split captured text into lines without trailing spaces or trailing blank lines."""
    lines = [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "").split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _nonblank(lines: list[str]) -> list[str]:
    return [l for l in lines if l.strip()]


# A turn in progress: Claude "✢ Photosynthesizing…", Codex "• Working (12s • esc to interrupt)".
BUSY_RE = re.compile(r"^\s*[✢✳✶✻✽✺·*•]\s+\S[^\n]*…|esc to interrupt", re.I)


def looks_busy(lines: list[str]) -> bool:
    """True if the last lines show the agent's spinner (a turn is still running)."""
    return any(BUSY_RE.search(l) for l in _nonblank(lines)[-8:])


def footer_match(lines: list[str]) -> str | None:
    """Return the footer line if one of the last two non-blank lines is a key-hint footer."""
    for line in _nonblank(lines)[-2:]:
        for rx in FOOTER_RES:
            if rx.search(line):
                return line.strip()
    return None


def is_option_line(line: str) -> bool:
    return bool(OPTION_RE.match(line) or CURSOR_RE.match(line))


def prompt_region(lines: list[str], max_lines: int = 80) -> list[str]:
    """Return the lines of the prompt panel at the bottom of the screen."""
    n = len(lines)
    start = None
    # Claude Code draws a full-width rule (─ or ▔) above its prompt panels. Skip
    # rules inside the panel, such as the one above "Chat about this".
    for r in range(n - 1, -1, -1):
        if not SOLID_RULE_RE.match(lines[r]):
            continue
        below = lines[r + 1 :]
        if not any(is_option_line(l) or SUBMIT_RE.match(l) for l in below):
            continue
        first = next((l for l in below if l.strip()), "")
        if OPTION_RE.match(first):
            continue
        start = r + 1
        break
    if start is None:
        # Codex has no rules: walk up from the bottom-most option to the transcript.
        last_opt = next((i for i in range(n - 1, -1, -1) if is_option_line(lines[i])), None)
        if last_opt is None:
            start = max(0, n - 12)
        else:
            i = last_opt
            while i - 1 >= 0 and is_option_line(lines[i - 1]):
                i -= 1
            j = i - 1
            while j >= 0 and not CODEX_STOP_RE.match(lines[j]) and not SOLID_RULE_RE.match(lines[j]):
                j -= 1
            start = j + 1
    region = lines[start:]
    while region and not region[0].strip():
        region.pop(0)
    while region and not region[-1].strip():
        region.pop()
    if len(region) > max_lines:
        region = region[-max_lines:]
    return region


def parse_tabbar(line: str) -> list[Tab] | None:
    if not TABBAR_RE.match(line):
        return None
    tabs = []
    for m in TAB_TOKEN_RE.finditer(line):
        glyph, label = m.group("glyph"), m.group("label").strip()
        submit = glyph in "✔✓" and label.lower() == "submit"
        tabs.append(Tab(label=label, glyph=glyph, answered=glyph in "☒☑", submit=submit))
    return tabs or None


def _split_label(body: str) -> tuple[str, str]:
    """Split "Label     description" (two or more spaces) as /model menus print it."""
    parts = re.split(r"\s{2,}", body, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return body.strip(), ""


def parse_menu(region: list[str]) -> Menu:
    tabs: list[Tab] = []
    title_lines: list[str] = []
    options: list[Option] = []
    footer = ""
    has_next = False
    body = list(region)
    nb = _nonblank(body)
    if nb and footer_match(nb[-1:]):
        footer = nb[-1].strip()
        idx = len(body) - 1 - body[::-1].index(nb[-1])
        body = body[:idx]
    first = next((i for i, l in enumerate(body) if l.strip()), None)
    if first is not None:
        t = parse_tabbar(body[first])
        if t:
            tabs = t
            body = body[first + 1 :]

    numbered = any(OPTION_RE.match(l) for l in body)
    if not numbered:
        title_lines, options = _unnumbered(body)
        body = []
    current: Option | None = None
    text_col = 0
    for line in body:
        if not line.strip():
            continue
        if SOLID_RULE_RE.match(line) or DASHED_RULE_RE.match(line):
            continue
        m = OPTION_RE.match(line)
        if m:
            raw = m.group("body")
            checked = None
            cb = CHECKBOX_RE.match(raw)
            if cb:
                checked = cb.group("mark") != " "
                raw = cb.group("label")
            label, desc = _split_label(raw)
            current = Option(
                index=len(options) + 1,
                number=int(m.group("num")),
                label=label,
                description=desc,
                cursor=bool(m.group("cursor")),
                checked=checked,
            )
            options.append(current)
            text_col = len(line) - len(line.lstrip()) + 2
            continue
        if line.strip() in ("Next", "Submit") and options:
            # the button under multi-select options
            has_next = True
            continue
        if current is not None and _indent(line) >= text_col:
            current.description = (current.description + "\n" + line.strip()).strip()
            continue
        if not options:
            title_lines.append(line.strip())
        # text below the options that is not a description (e.g. "◉ xHigh effort") is ignored
    text = "\n".join(region)
    return Menu(
        tabs=tabs,
        title="\n".join(title_lines),
        options=options,
        footer=footer,
        multi_select=any(o.checked is not None for o in options),
        review="Review your answers" in text or any(o.label == "Submit answers" for o in options),
        unanswered_warning="You have not answered all questions" in text,
        has_next_button=has_next,
    )


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _unnumbered(body: list[str]) -> tuple[list[str], list[Option]]:
    """Parse a menu without option numbers, such as Claude's trust-folder screen:

         ❯ No, exit
           Yes, I trust this folder

    The options are the cursor line plus the adjacent lines whose text starts in
    the same column as the cursor line's text.
    """
    cursors = [i for i, l in enumerate(body) if CURSOR_RE.match(l)]
    if not cursors:
        return [l.strip() for l in body if l.strip()], []
    ci = cursors[-1]
    col = _indent(body[ci]) + 2

    def sibling(l: str) -> bool:
        return bool(l.strip()) and _indent(l) == col and not CURSOR_RE.match(l)

    lo = ci
    while lo - 1 >= 0 and sibling(body[lo - 1]):
        lo -= 1
    hi = ci
    while hi + 1 < len(body) and sibling(body[hi + 1]):
        hi += 1
    options = []
    for k in range(lo, hi + 1):
        if k == ci:
            label = CURSOR_RE.match(body[k]).group("body")
        else:
            label = body[k].strip()
        options.append(Option(index=len(options) + 1, number=None, label=label, cursor=k == ci))
    title = [l.strip() for l in body[:lo] if l.strip()]
    return title, options


def classify(region_text: str, menu: Menu | None) -> str:
    t = region_text.lower()
    if menu is not None and (menu.tabs or menu.review):
        return "question"
    if "type something" in t or "chat about this" in t:
        return "question"
    if TRUST_RE.search(region_text):
        return "trust"
    if PERMISSION_RE.search(region_text):
        return "permission"
    return "menu"


def analyze(text: str) -> ScreenState:
    """Decide whether the captured screen shows a prompt waiting for a key."""
    lines = normalize(text)
    if not _nonblank(lines):
        return ScreenState(needs_input=False, reason="blank")
    reason = None
    f = footer_match(lines)
    if f:
        reason = f"footer: {f}"
    else:
        for line in _nonblank(lines)[-12:]:
            if SUBMIT_RE.match(line):
                reason = "submit page"
                break
    if not reason:
        return ScreenState(needs_input=False)
    region = prompt_region(lines)
    menu = parse_menu(region)
    region_text = "\n".join(region)
    return ScreenState(
        needs_input=True, kind=classify(region_text, menu), reason=reason, prompt=region_text, menu=menu
    )


# ---------------------------------------------------------------------------
# VT parsing: which tab of a multi-question menu is highlighted

CSI_RE = re.compile(r"\x1b\[([0-9;:?<>=]*)([ -/]*)([@-~])")
OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def _apply_sgr(params: str, bg, inverse: bool):
    ps = [p for p in re.split(r"[;:]", params)] if params else ["0"]
    i = 0
    while i < len(ps):
        p = ps[i]
        n = int(p) if p.isdigit() else 0
        if n == 0:
            bg, inverse = None, False
        elif n == 7:
            inverse = True
        elif n == 27:
            inverse = False
        elif 40 <= n <= 47 or 100 <= n <= 107:
            bg = f"c{n}"
        elif n == 49:
            bg = None
        elif n in (38, 48, 58):
            mode = ps[i + 1] if i + 1 < len(ps) else ""
            if mode == "2":
                val = ",".join(ps[i + 2 : i + 5])
                i += 4
            elif mode == "5":
                val = f"p{ps[i + 2] if i + 2 < len(ps) else ''}"
                i += 2
            else:
                val = None
            if n == 48:
                bg = val
        i += 1
    return bg, inverse


def vt_cells(line: str) -> list[tuple[str, str | None]]:
    """Return (char, background) for each printed cell of one VT line."""
    bg = None
    inverse = False
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\x1b":
            m = CSI_RE.match(line, i)
            if m:
                params, _inter, final = m.groups()
                if final == "m":
                    bg, inverse = _apply_sgr(params, bg, inverse)
                elif final == "C":
                    out.extend((" ", None) for _ in range(int(params or "1")))
                i = m.end()
                continue
            m = OSC_RE.match(line, i)
            if m:
                i = m.end()
                continue
            i += 2
            continue
        if ch in "\r\x07":
            i += 1
            continue
        out.append((ch, ("inverse:" + (bg or "")) if inverse else bg))
        i += 1
    return out


def active_tab(vt: str) -> tuple[list[Tab], int]:
    """Find the tab bar in a VT capture and return its tabs and the highlighted index."""
    found = None
    for raw in vt.split("\n"):
        cells = vt_cells(raw)
        text = "".join(c for c, _ in cells)
        if parse_tabbar(text.rstrip()):
            found = cells
    if found is None:
        raise ValueError("no question tab bar found in the VT capture")
    text = "".join(c for c, _ in found)
    tokens = list(TAB_TOKEN_RE.finditer(text))
    inside = set()
    for m in tokens:
        inside.update(range(m.start(), m.end()))
    gaps = [found[k][1] for k in range(len(found)) if k not in inside and found[k][0] != " "]
    base = max(set(gaps), key=gaps.count) if gaps else None
    tabs = parse_tabbar(text.rstrip())
    assert tabs is not None and len(tabs) == len(tokens)
    hits = []
    for idx, m in enumerate(tokens):
        bgs = [found[k][1] for k in range(m.start(), m.end()) if found[k][0] != " "]
        if bgs and any(b is not None and b != base for b in bgs):
            hits.append(idx)
    if len(hits) != 1:
        raise ValueError(f"expected exactly one highlighted tab, found {len(hits)} in {text.strip()!r}")
    for idx, t in enumerate(tabs):
        t.active = idx == hits[0]
    return tabs, hits[0]
