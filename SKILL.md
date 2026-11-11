---
name: Drive Claude Code and Codex in a Mac terminal
description: Use when the user wants you to work alongside their interactive Claude Code CLI or Codex CLI (or the Codex panel in the ChatGPT Mac app) on their Mac using their own subscriptions - start a session in a terminal, send it prompts, wait for and read its replies, notice and relay its questions and permission prompts, answer them, or switch its model.
---
# Drive Claude Code and Codex in a Mac terminal

Runs the user's own interactive `claude` and `codex` sessions in a real terminal on their Mac, so the work uses their logged-in subscriptions. Prefer the **Rex CLI** to type into a session and read its screen; read replies from the session log files, not from screenshots.

The scripts and the canonical, versioned copy of this skill live in the user's `agent-tui-bridge` git repo (cloned on the Mac, usually `~/agent-tui-bridge`). Read its `SKILL.md` first; if it differs from a saved copy, the repo wins. All commands run on the user's Mac (machine-targeted Shell). Set `REPO` to the clone path and call `$REPO/bin/...`.

Rex CLI reference: https://www.superlogical.com/rex/docs/reference/cli

## Requirements (one time)
- **Rex** (default: the `Rex Beta` app). The CLI is usually bundled and not on PATH; `bin/rex` finds it, or set `ATB_REX` to the binary. Official docs: `rex send`, `rex send-key`, `rex capture`, `rex new` / `rex run`, `rex ls`.
- `claude` and/or `codex` on PATH (including via `~/.zshrc`) and logged in. `python3` for the `agent-*` scripts (standard library only; tested with 3.14).
- The Rex path does **not** need Accessibility, a frontmost window, or the clipboard.
- AppleScript fallback (`-a` / `ATB_BACKEND=osascript`) and GUI clicking still need Accessibility; screenshots need Screen Recording. After granting, the app running the commands usually has to restart. `swiftc` (Xcode CLT) is needed for `mac-click`.

## Use session IDs, not labels
`term-start` prints `session_id=session:…` and `block_id=block:…`. Keep the ID and pass it as `-s` everywhere. Claude Code with Rex hooks installed renames its own session mid-run (the SessionStart hook asks it to), so a label that worked a minute ago can stop matching. Labels still work in every script; `agent-watch` and `agent-menu` resolve a label to the ID once, at start. ID suffixes as shown by `bin/rex ls` (e.g. `f714b9`) also work.

## The loop: mark → send → watch
```bash
REPO=~/agent-tui-bridge
out=$($REPO/bin/term-start -s claude -c ~/proj claude)      # or: codex
SID=$(printf '%s\n' "$out" | sed -n 's/^session_id=//p')

N=$($REPO/bin/agent-watch mark claude -s "$SID")            # 1. mark the log
$REPO/bin/term-send -s "$SID" "prompt"                       # 2. send
$REPO/bin/agent-watch claude -s "$SID" --from "$N" --timeout 1500   # 3. watch
```
`agent-watch` returns as soon as **one** of these happens. Its first line is the status:

| first line | exit | meaning | what to do |
|---|---|---|---|
| `status=turn_end …` | 0 | the turn finished | the final reply is between `----- reply -----` markers. Next prompt: start the loop again with a new mark. |
| `status=needs_input kind=… …` | 4 | a menu or prompt is waiting for a person | relay it (below), answer, then **watch again with the same `--from "$N"`** (the turn is still the same one). |
| `status=exited reason=… …` | 5 | the agent process exited, or the pane/session was closed | report it; the screen tail is printed. |
| `status=timeout …` | 3 | nothing of the above within `--timeout` | the screen tail is printed. Usually it is still working: watch again. |

The status line is shell-quoted `key=value` pairs (`shlex.split` it). `--json` prints one JSON object instead (with `menu`, `questions`, `prompt`, `reply`, `rex_status`). `kind` is `question` (AskUserQuestion), `permission` (tool approval, Codex command approval), `trust` (trust-folder screen, Codex hook review), `auth`, or `menu` (e.g. `/model`). `source` says which signal fired.

### When it says needs_input
1. **Relay it verbatim.** Copy the block between `----- prompt (screen, verbatim) -----` and `----- end prompt -----` to the person unchanged. When the log already has the questions, a `----- questions (session log) -----` block lists every question with numbered options.
2. **Multi-question menus** (`tabs=N` in the status line, e.g. `←  ☐ Topic A  ☐ Topic B  ✔ Submit  →`) show only page 1 on screen. Read all pages without answering, then relay all of them:
   ```bash
   $REPO/bin/agent-menu read -s "$SID"
   ```
   It goes to page 1, presses → page by page capturing each, and returns to page 1. Or pass `--read-tabs` to `agent-watch` to include the pages in its output.
3. **Answer only what the person decided.** Never answer a permission, trust, or question prompt the user has not approved in principle.
   ```bash
   $REPO/bin/agent-menu answer -s "$SID" 1 2 1 1,2     # one answer per question page, in order
   $REPO/bin/agent-menu answer -s "$SID" text:"free text"   # "Type something" on a single-select page
   $REPO/bin/agent-menu answer -s "$SID" 4             # permission / trust / Codex approval: option 4
   ```
   - Question pages: `N` picks option N; `N,M` is the full set to tick on a multi-select page (others are unticked); `text:WORDS` types into "Type something". The menu is then submitted ("1. Submit answers"); `--no-submit` stops on the review page so you can show it first. The script checks every step on screen and fails loudly (exit 1, screen shown) if the menu does not react as expected, for example when the number of answers does not match the number of pages.
   - Other prompts take one `N`. The options without numbers (the trust screen: `❯ No, exit` / `Yes, I trust this folder`) are counted from the top. The cursor moves there and Enter is pressed; `--key s` presses `s` instead (Claude `/model`: this session only).
   - To dismiss a prompt: `$REPO/bin/term-key -s "$SID" esc`.
4. Watch again: `$REPO/bin/agent-watch claude -s "$SID" --from "$N"`. Repeat until `turn_end`.

**Never `term-send` while a prompt is waiting.** The text goes to the menu as key presses, and the Enter picks whatever the cursor is on (on the trust screen that is "No, exit", which quits Claude). Claude Code's empty input box shows a grey prompt suggestion, so it can look as if text is already typed after `❯`; pressing Enter on it does nothing, so send your own text with `term-send`.

### How it detects "needs a person"
It polls about once a second (`--interval`) and combines:
- **Rex program status.** Claude Code and Codex report their state to Rex themselves (OSC 7501; `rex block call process|program_status`). `state=blocked` with `kind=question|permission|auth` is the strongest signal; `rex_status:` repeats its message.
- **The screen** (`rex capture`): a key-hint footer on the last lines — `Enter to select · … · Esc to cancel`, `Enter to confirm · Esc to cancel`, `Esc to cancel · Tab to amend`, `Press enter to confirm or esc to cancel`, `enter confirm · esc skip`, `enter select · esc back` — or the `❯ 1. Submit answers` page. This is the only signal for the trust-folder screen, `/model`, and Codex's hook review, which report no blocked status. Only the bottom lines count, so a reply that quotes a menu is not mistaken for one.
- **The session log**: the turn-end marker after line N (`turn_duration` / `task_complete` / `turn_aborted`), and unanswered `AskUserQuestion` / `ExitPlanMode` / Codex `request_user_input` calls, whose questions are then printed. Claude Code 2.1.322 sometimes writes a pending AskUserQuestion to the log only *after* it is answered, which is why `agent-log wait` alone hung on such menus.
- **The pane**: the agent process exiting, or the session/block disappearing.

A needs_input signal must hold for two polls in a row. If Rex says blocked but the screen matches no known prompt, the last 30 screen lines are shown and `reason` says so.

### Finding the log
`agent-watch mark|log` and `agent-watch` find the log from the pane. For Claude this is exact (`~/.claude/sessions/<pid>.json` → session ID → `~/.claude/projects/*/<id>.jsonl`); before the folder is trusted that file does not exist yet, and `mark` prints `0`. For Codex it is the rollout whose session cwd matches the pane's and that was written since the process started; if several match it stops with an error, so pass `--log FILE` (e.g. from `$REPO/bin/agent-log latest codex --cwd DIR`). `agent-watch` waits up to `--start-timeout` (15 s) for claude/codex to appear in a pane that is still running `~/.zshrc`.

## Steps
1. **Start a session.** Prefer a labeled Rex session whose working directory is the project:
   ```bash
   $REPO/bin/term-start -s claude -c ~/proj "claude"
   $REPO/bin/term-start -s codex -c ~/proj "codex"
   ```
   That runs `rex new LABEL --keep-open --interactive -c DIR -- command`, so the command is the pane's root process, and prints rex's JSON, `session=LABEL`, `session_id=…` and `block_id=…`. A session with no command is a default login shell (`--interactive` is omitted; Rex requires a command for that flag). A single argument that looks like a shell snippet (for example `cd ~/proj && claude`) is run with `zsh -c`. If the label already exists, the script exits and tells you to reuse it or `bin/rex kill LABEL`.

2. **Handle the first-run screen.** Run `$REPO/bin/agent-watch claude -s "$SID" --from 0 --timeout 30` right after starting: a new folder gives `status=needs_input kind=trust`. Choose "Yes, I trust this folder" with `$REPO/bin/agent-menu answer -s "$SID" 2` only if the user has said to trust that folder (or has a standing "always trust folders" preference). Trust is remembered per folder. Codex may show `Hooks need review` (also `kind=trust`); `term-key -s "$SID" esc` skips it without trusting.

3. **Send prompts with the loop above.** `term-send` uses `rex send` plus `rex send-key enter` (`-n` skips Enter), so Chinese text and `/slash` commands arrive intact, without touching the clipboard or focusing the app.

4. **Look at the screen any time:** `$REPO/bin/term-capture -s "$SID"`, or `$REPO/bin/agent-menu show -s "$SID"` for just the waiting prompt.

5. **Read history any time:** `F=$($REPO/bin/agent-watch log claude -s "$SID")`, then `$REPO/bin/agent-log show claude "$F" --last 10`. Both tools write each whole message as soon as it is complete (no partial tokens).

6. **Switch model.** Default to session-only unless the user asked to change the default.
   - Claude: `term-send -s "$SID" "/model"`; `agent-watch` reports `kind=menu` with the list; `agent-menu answer -s "$SID" N --key s` for this session only, or `agent-menu answer -s "$SID" N` to make it the default. If it asks to confirm a switch mid-conversation, answer "Yes".
   - Codex CLI: `term-send -s "$SID" "/model"`, then `agent-menu answer -s "$SID" N` for the model and again for the reasoning level (`s` / Enter as the screen says).
   - Verify with `$REPO/bin/agent-log model claude|codex "$F"` after the next turn.

7. **GUI apps (Codex in the ChatGPT app)** still need macOS automation. Keyboard works (Cmd+N new chat, Cmd+V, Enter). Buttons need a real mouse event: System Events `click at` does not trigger them. Use `$REPO/bin/mac-shot` (it prints `screen_points=WxH`), map image pixels to points by `point = pixel * screen_width_points / image_width`, then `$REPO/bin/mac-click X Y`. Re-screenshot after every click; coordinates break when windows move. Prefer the CLI over the GUI whenever both exist.

8. **Non-Rex terminals** (Terminal.app, iTerm, and so on): `term-start -a "iTerm" "claude"`, `term-send -a "iTerm" -t N "prompt"`, `term-key -a "iTerm" -t N down enter`. Or set `ATB_TERM` and `ATB_BACKEND=osascript`. This path activates the app, uses the clipboard to paste, and needs Accessibility. Tab numbers are Cmd+1..9. `agent-watch` / `agent-menu` need Rex; with other terminals only `agent-log wait` (log only) is available.

## Older commands (still work)
- `agent-log latest claude|codex --cwd DIR`, `agent-log mark FILE`, `agent-log wait claude|codex FILE --from N [--timeout S]` behave as before: `wait` prints only the reply and exits 3 on timeout. It only sees the log, so it cannot notice a menu. Add `-s "$SID"` to `agent-log wait` to get the `agent-watch` behaviour and output; `agent-log latest claude -s "$SID"` finds the pane's log.

## If `rex ls` is empty
The CLI talks to a local server through a unix socket (`rex whoami` shows the endpoint, pid, and version). If the Rex app has tabs but `bin/rex ls` lists none, the CLI is likely connected to a stale or different server. Check Settings › Server › Rex Server in the app, restart the server so it matches the app, and confirm `rex whoami` / `rex ls` then show the sessions you see on screen. Global flags: `-S` server, `-C` client.

## Rex `skill setup` (optional, ask first)
`rex skill setup --agent claude --agent codex` installs Rex's own skill and hooks into those agents' settings. Do **not** run it unless the user asks; it edits Claude Code / Codex config. `rex skill status` / `rex skill show` are read-only. The program status that `agent-watch` reads is reported by the Claude Code and Codex processes themselves (seen with Claude Code 2.1.322 and Codex 0.167, with only Rex's SessionStart hooks installed). If an agent reports nothing, the screen and log signals still work.

## Rules
- The Rex CLI path does not steal focus and does not use the clipboard; it is safe to use while the user is in another app. Still tell them before creating or killing sessions, or before answering prompts on their behalf.
- Never answer a permission or trust prompt the user has not approved in principle. Relay what the prompt asks, verbatim.
- `agent-menu read` presses ←/→ in the pane; if the user is typing in that pane at the same moment, the keys mix. Tell them first when they might be.
- Use `agent-watch` / `term-capture` (or screenshots only for GUI / non-Rex) for on-screen state; read replies from the logs.
- AppleScript `term-send` briefly replaces the clipboard and restores its text afterwards (non-text clipboard contents are lost).
- To improve the skill, edit the repo, run `python3 -m unittest discover -s tests`, commit, and push; then update any saved copy.
