# agent-tui-bridge

Let an assistant drive your **interactive** Claude Code and Codex CLI sessions in a Mac terminal, using your own subscriptions: send prompts, wait for replies by watching their session logs, notice when the agent stops to ask a person (question menus, permission and trust prompts, `/model`), relay those prompts verbatim, answer them, and switch models.

The default path uses the [Rex CLI](https://www.superlogical.com/rex/docs/reference/cli) (`rex send`, `rex send-key`, `rex capture`, `rex new`, `rex block call`) so input goes to a named session without focusing the app or using the clipboard. AppleScript and click helpers remain as a fallback for other terminals and for the Codex panel in the ChatGPT Mac app.

See [SKILL.md](SKILL.md) for the full workflow.

| script | what it does |
|---|---|
| `bin/rex ...` | locate the bundled Rex CLI and run it (`ATB_REX` overrides) |
| `bin/term-start [-s LABEL] [-c CWD] "cmd"` | `rex new` a labeled session, run a command, print `session_id=` / `block_id=` |
| `bin/term-send [-s SESSION] "text"` | `rex send` text and press Enter (`-n` skips Enter) |
| `bin/term-key [-s SESSION] keys...` | `rex send-key`: `up down left right enter esc tab space`, `ctrl+c`, or a character |
| `bin/term-capture [-s SESSION]` | print the pane's screen and scrollback |
| `bin/agent-watch mark\|log claude\|codex -s SESSION` | line count / path of the pane's session log |
| `bin/agent-watch claude\|codex -s SESSION --from N` | wait until `turn_end`, `needs_input`, `exited`, or `timeout`; print a status line and the reply or the prompt verbatim |
| `bin/agent-menu show\|read\|answer -s SESSION` | print the waiting prompt; read every page of a multi-question menu without answering; answer by option number |
| `bin/agent-log latest\|mark\|wait\|show\|model` | find and read Claude/Codex JSONL session logs; `wait` blocks until the turn ends (log only, unless `-s`) |
| `bin/mac-shot [out.png]` | screenshot + print screen size in points (GUI / fallback) |
| `bin/mac-click X Y` | real CGEvent mouse click (works in Electron apps) |

Quick example:

```bash
REPO=~/agent-tui-bridge
out=$($REPO/bin/term-start -s claude -c ~/proj claude)
SID=$(printf '%s\n' "$out" | sed -n 's/^session_id=//p')    # use the ID: Rex hooks may rename the session

N=$($REPO/bin/agent-watch mark claude -s "$SID")
$REPO/bin/term-send -s "$SID" "hello"
$REPO/bin/agent-watch claude -s "$SID" --from "$N" --timeout 1500
# status=turn_end    -> the reply follows
# status=needs_input -> the prompt follows, verbatim; relay it, then for example:
$REPO/bin/agent-menu read -s "$SID"               # every page of a multi-question menu
$REPO/bin/agent-menu answer -s "$SID" 1 2 1,3     # one answer per page
$REPO/bin/agent-watch claude -s "$SID" --from "$N" # same N: still the same turn
```

Status lines look like
`status=needs_input kind=question source=rex_status tool=claude session=session:… block=block:… log=… from=66 lines=70 elapsed=7.1 rex_state=blocked tabs=4`
(shell-quoted `key=value` pairs; `--json` for one JSON object). Exit codes: 0 turn_end, 4 needs_input, 5 exited, 3 timeout.

Detection combines Rex's program status (Claude Code and Codex report `blocked` with `kind=question|permission` to Rex), the screen's key-hint footer (`Enter to select · … · Esc to cancel` and similar, which also catches the trust-folder screen and `/model`), the session log (turn-end markers, unanswered `AskUserQuestion`), and the pane's process. No AppleScript or screenshots are involved.

`term-start` / `term-send` / `term-key` accept `-a APP` (and `-t TAB`) to drive Terminal, iTerm, and similar via AppleScript. That path needs macOS Accessibility (and Screen Recording for screenshots) for the app running the scripts. Force it with `ATB_BACKEND=osascript`. The default terminal name for that path is `Rex Beta`; override with `ATB_TERM`.

## Tests

```bash
python3 -m unittest discover -s tests
```

The parsers are tested against captured screens and JSONL samples in `tests/fixtures/` (paths and personal details replaced), including a four-page question menu. `tests/test_menu.py` drives `agent-menu` against a simulator of Claude Code's question menu.
