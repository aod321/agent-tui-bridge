---
name: Drive Claude Code and Codex in a Mac terminal
description: Use when the user wants you to work alongside their interactive Claude Code CLI or Codex CLI (or the Codex panel in the ChatGPT Mac app) on their Mac using their own subscriptions - start a session in a terminal, send it prompts, wait for and read its replies, answer its prompts, or switch its model.
---
# Drive Claude Code and Codex in a Mac terminal

Runs the user's own interactive `claude` and `codex` sessions in a real terminal on their Mac, so the work uses their logged-in subscriptions. Prefer the **Rex CLI** to type into a session and read its screen; read replies from the session log files, not from screenshots.

The scripts and the canonical, versioned copy of this skill live in the user's `agent-tui-bridge` git repo (cloned on the Mac, usually `~/agent-tui-bridge`). Read its `SKILL.md` first; if it differs from a saved copy, the repo wins. All commands run on the user's Mac (machine-targeted Shell). Set `REPO` to the clone path and call `$REPO/bin/...`.

Rex CLI reference: https://www.superlogical.com/rex/docs/reference/cli

## Requirements (one time)
- **Rex** (default: the `Rex Beta` app). The CLI is usually bundled and not on PATH; `bin/rex` finds it, or set `ATB_REX` to the binary. Official docs: `rex send`, `rex send-key`, `rex capture`, `rex new` / `rex run`, `rex ls`.
- `claude` and/or `codex` on PATH (including via `~/.zshrc`) and logged in.
- The Rex path does **not** need Accessibility, a frontmost window, or the clipboard.
- AppleScript fallback (`-a` / `ATB_BACKEND=osascript`) and GUI clicking still need Accessibility; screenshots need Screen Recording. After granting, the app running the commands usually has to restart. `swiftc` (Xcode CLT) is needed for `mac-click`.

## Steps
1. **Start a session.** Prefer a labeled Rex session whose working directory is the project:
   ```bash
   $REPO/bin/term-start -s claude -c ~/proj "claude"
   $REPO/bin/term-start -s codex -c ~/proj "codex"
   ```
   That runs `rex new LABEL --keep-open --interactive -c DIR -- command`, so the command is the pane's root process, and prints `session=LABEL`. A session with no command is a default login shell (`--interactive` is omitted; Rex requires a command for that flag). A single argument that looks like a shell snippet (for example `cd ~/proj && claude`) is run with `zsh -c`. Pass the label as `-s` later, or export `ATB_SESSION=claude`. If the label already exists, the script exits and tells you to reuse it or `bin/rex kill LABEL`.

2. **Handle the first-run screen.** `$REPO/bin/term-capture -s claude` prints the pane. Claude asks once per folder whether to trust it; choose Yes with `$REPO/bin/term-key -s claude down enter` only if the user has said to trust that folder (or has a standing "always trust folders" preference). Trust is remembered per folder.

3. **Find the log file.** `F=$($REPO/bin/agent-log latest claude --cwd DIR)` or `... latest codex --cwd DIR`. Logs: Claude `~/.claude/projects/<cwd with / and . replaced by ->/<session>.jsonl`; Codex `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (first line holds the cwd). A new session's file appears after its first message, so look it up after sending the first prompt.

4. **Send a prompt and wait.** Always mark first, then send, then wait:
   ```bash
   N=$($REPO/bin/agent-log mark "$F")
   $REPO/bin/term-send -s claude "prompt"
   $REPO/bin/agent-log wait claude "$F" --from $N --timeout 600
   ```
   `wait` returns the final assistant reply once the turn ends (Claude writes `system/turn_duration`, Codex writes `event_msg/task_complete`). `term-send` uses `rex send` plus `rex send-key enter` (`-n` skips Enter), so Chinese text and `/slash` commands arrive intact, without touching the clipboard or focusing the app.

5. **If `wait` times out**, the agent is probably blocked on an on-screen prompt (permission, choice menu). Read `$REPO/bin/term-capture -s claude`, then answer with `term-key` (`up`, `down`, `enter`, `esc`, a letter, or a Rex binding such as `ctrl+c`).

6. **Read history any time:** `$REPO/bin/agent-log show claude "$F" --last 10`. Both tools write each whole message as soon as it is complete (no partial tokens), so the file is current to the last finished message.

7. **Switch model.** Default to session-only unless the user asked to change the default.
   - Claude: `term-send -s claude "/model"`, `term-capture` to see the list, move with `term-key -s claude down|up`, then `s` for this session only or `enter` to make it the default. If it asks to confirm a switch mid-conversation, `enter` on "Yes".
   - Codex CLI: `term-send -s codex "/model"`, pick a model with `up/down` + `enter`, then a reasoning level, then `s` for this session only or `enter` for default.
   - Verify with `$REPO/bin/agent-log model claude|codex "$F"` after the next turn.

8. **GUI apps (Codex in the ChatGPT app)** still need macOS automation. Keyboard works (Cmd+N new chat, Cmd+V, Enter). Buttons need a real mouse event: System Events `click at` does not trigger them. Use `$REPO/bin/mac-shot` (it prints `screen_points=WxH`), map image pixels to points by `point = pixel * screen_width_points / image_width`, then `$REPO/bin/mac-click X Y`. Re-screenshot after every click; coordinates break when windows move. Prefer the CLI over the GUI whenever both exist.

9. **Non-Rex terminals** (Terminal.app, iTerm, and so on): `term-start -a "iTerm" "claude"`, `term-send -a "iTerm" -t N "prompt"`, `term-key -a "iTerm" -t N down enter`. Or set `ATB_TERM` and `ATB_BACKEND=osascript`. This path activates the app, uses the clipboard to paste, and needs Accessibility. Tab numbers are Cmd+1..9.

## If `rex ls` is empty
The CLI talks to a local server through a unix socket (`rex whoami` shows the endpoint, pid, and version). If the Rex app has tabs but `bin/rex ls` lists none, the CLI is likely connected to a stale or different server. Check Settings › Server › Rex Server in the app, restart the server so it matches the app, and confirm `rex whoami` / `rex ls` then show the sessions you see on screen. Global flags: `-S` server, `-C` client.

## Rex `skill setup` (optional, ask first)
`rex skill setup --agent claude --agent codex` installs Rex's own skill and hooks into those agents' settings. Do **not** run it unless the user asks; it edits Claude Code / Codex config. `rex skill status` / `rex skill show` are read-only.

## Rules
- The Rex CLI path does not steal focus and does not use the clipboard; it is safe to use while the user is in another app. Still tell them before creating or killing sessions, or before answering prompts on their behalf.
- Never answer a permission or trust prompt the user has not approved in principle. Report what the prompt asks.
- Use `term-capture` (or screenshots only for GUI / non-Rex) for on-screen state; read replies from the logs.
- AppleScript `term-send` briefly replaces the clipboard and restores its text afterwards (non-text clipboard contents are lost).
- To improve the skill, edit the repo, test, commit, and push; then update any saved copy.
