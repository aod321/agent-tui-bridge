# agent-tui-bridge

Let an assistant drive your **interactive** Claude Code and Codex CLI sessions in a Mac terminal, using your own subscriptions: send prompts, wait for replies by watching their session logs, answer prompts, switch models, and click GUI buttons when needed.

See [SKILL.md](SKILL.md) for the full workflow.

| script | what it does |
|---|---|
| `bin/term-start "cmd"` | new terminal tab (Cmd+T) and run a command |
| `bin/term-send [-t TAB] "text"` | paste text into a tab and press Enter (CJK and `/commands` safe) |
| `bin/term-key [-t TAB] keys...` | send keys: `up down enter esc tab space` or single chars |
| `bin/agent-log latest\|mark\|wait\|show\|model` | find and read Claude/Codex JSONL session logs; `wait` blocks until the turn ends |
| `bin/mac-shot [out.png]` | screenshot + print screen size in points |
| `bin/mac-click X Y` | real CGEvent mouse click (works in Electron apps) |

Quick example:

```bash
bin/term-start "claude"
F=$(bin/agent-log latest claude --cwd ~)
N=$(bin/agent-log mark "$F"); bin/term-send -t 1 "hello"; bin/agent-log wait claude "$F" --from $N
```

Requires macOS Accessibility (and Screen Recording for screenshots) for the app running these scripts. Terminal defaults to `Rex Beta`; override with `ATB_TERM`.
