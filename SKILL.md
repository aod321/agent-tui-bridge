---
name: Drive Claude Code and Codex in a Mac terminal
description: Use when the user wants you to work alongside their interactive Claude Code CLI or Codex CLI (or the Codex panel in the ChatGPT Mac app) on their Mac using their own subscriptions - start a session in a terminal, send it prompts, wait for and read its replies, answer its prompts, or switch its model.
---
# Drive Claude Code and Codex in a Mac terminal

Runs the user's own interactive `claude` and `codex` sessions in a real terminal window on their Mac, so the work uses their logged-in subscriptions. You type into the terminal through macOS automation and read results from the session log files, not from screenshots.

Scripts live in this repo's `bin/` (clone it on the Mac, e.g. `~/agent-tui-bridge`). All commands run on the user's Mac.

## Requirements (one time)
- The app running your commands needs **Accessibility** permission (System Settings › Privacy & Security › Accessibility) for keystrokes and clicks, and **Screen Recording** for screenshots. After granting, the app usually has to restart.
- A terminal with tabs and Cmd+T / Cmd+1..9 (default `Rex Beta`; set `ATB_TERM="iTerm"` etc. to change).
- `claude` and/or `codex` on PATH and logged in. `swiftc` (Xcode CLT) for `mac-click`.

## Steps
1. **Start a session.** `bin/term-start "claude"` or `bin/term-start "codex"` opens a new tab and launches it. Note which tab number it is (Cmd+N order) and pass it as `-t N` later. Start in a dedicated project folder when possible (`term-start "cd ~/proj && claude"`).
2. **Handle the first-run screen.** Take `bin/mac-shot` and look. Claude asks once per folder whether to trust it; choose Yes with `bin/term-key -t N down enter` (only if the user has said to trust it). Trust is remembered per folder.
3. **Find the log file.** `F=$(bin/agent-log latest claude --cwd DIR)` or `... latest codex --cwd DIR`. Logs: Claude `~/.claude/projects/<cwd with / and . replaced by ->/<session>.jsonl`; Codex `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (first line holds the cwd). A new session's file appears after its first message, so look it up after sending the first prompt.
4. **Send a prompt and wait.** Always mark first, then send, then wait:
   `N=$(bin/agent-log mark "$F"); bin/term-send -t N "prompt"; bin/agent-log wait claude "$F" --from $N --timeout 600`
   `wait` returns the final assistant reply once the turn ends (Claude writes `system/turn_duration`, Codex writes `event_msg/task_complete`). `term-send` pastes via the clipboard, so Chinese text and `/slash` commands arrive intact.
5. **If `wait` times out**, the agent is probably blocked on an on-screen prompt (permission, choice menu). Screenshot, then answer with `term-key` (`up`, `down`, `enter`, `esc`, or a letter).
6. **Read history any time:** `bin/agent-log show claude "$F" --last 10`. Both tools write each whole message as soon as it is complete (no partial tokens), so the file is current to the last finished message.
7. **Switch model.**
   - Claude: `term-send -t N "/model"`, screenshot to see the list, move with `term-key -t N down|up`, then `s` for this session only or `enter` to make it the default. If it asks to confirm a switch mid-conversation, `enter` on "Yes".
   - Codex CLI: `term-send -t N "/model"`, pick a model with `up/down` + `enter`, then a reasoning level, then `s` for this session only or `enter` for default.
   - Verify with `bin/agent-log model claude|codex "$F"` after the next turn.
   - Default to session-only unless the user asked to change the default.
8. **GUI apps (Codex in the ChatGPT app).** Keyboard works (Cmd+N new chat, Cmd+V, Enter). Buttons need a real mouse event: System Events `click at` does not trigger them. Use `bin/mac-shot` (it prints `screen_points=WxH`), map image pixels to points by `point = pixel * screen_width_points / image_width`, then `bin/mac-click X Y`. Re-screenshot after every click; coordinates break when windows move. Prefer the CLI over the GUI whenever both exist.

## Rules
- Each keystroke goes to the frontmost window; the scripts activate the terminal first, but do not run them while the user is typing elsewhere without telling them.
- Never answer a permission or trust prompt the user has not approved in principle. Report what the prompt asks.
- Use screenshots only for on-screen state (menus, prompts); read replies from the logs.
- `term-send` briefly replaces the clipboard and restores its text afterwards (non-text clipboard contents are lost).
