# agent-tui-bridge

Let an assistant drive your **interactive** Claude Code and Codex CLI sessions in a Mac terminal, using your own subscriptions: send prompts, wait for replies by watching their session logs, answer on-screen prompts, and switch models.

The default path uses the [Rex CLI](https://www.superlogical.com/rex/docs/reference/cli) (`rex send`, `rex send-key`, `rex capture`, `rex new`) so input goes to a named session without focusing the app or using the clipboard. AppleScript and click helpers remain as a fallback for other terminals and for the Codex panel in the ChatGPT Mac app.

See [SKILL.md](SKILL.md) for the full workflow.

| script | what it does |
|---|---|
| `bin/rex ...` | locate the bundled Rex CLI and run it (`ATB_REX` overrides) |
| `bin/term-start [-s LABEL] [-c CWD] "cmd"` | `rex new` a labeled session and run a command |
| `bin/term-send [-s SESSION] "text"` | `rex send` text and press Enter (`-n` skips Enter) |
| `bin/term-key [-s SESSION] keys...` | `rex send-key`: `up down enter esc tab space`, `ctrl+c`, or a character |
| `bin/term-capture [-s SESSION]` | print the pane's screen and scrollback |
| `bin/agent-log latest\|mark\|wait\|show\|model` | find and read Claude/Codex JSONL session logs; `wait` blocks until the turn ends |
| `bin/mac-shot [out.png]` | screenshot + print screen size in points (GUI / fallback) |
| `bin/mac-click X Y` | real CGEvent mouse click (works in Electron apps) |

Quick example:

```bash
REPO=~/agent-tui-bridge
$REPO/bin/term-start -s claude -c ~ "claude"
F=$($REPO/bin/agent-log latest claude --cwd ~)
N=$($REPO/bin/agent-log mark "$F")
$REPO/bin/term-send -s claude "hello"
$REPO/bin/agent-log wait claude "$F" --from $N
```

`term-start` / `term-send` / `term-key` accept `-a APP` (and `-t TAB`) to drive Terminal, iTerm, and similar via AppleScript. That path needs macOS Accessibility (and Screen Recording for screenshots) for the app running the scripts. Force it with `ATB_BACKEND=osascript`. The default terminal name for that path is `Rex Beta`; override with `ATB_TERM`.
