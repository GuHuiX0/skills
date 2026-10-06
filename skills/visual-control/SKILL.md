---
name: visual-control
description: Observe the screen and drive the real mouse and keyboard on Windows (screenshot, click, type text, hotkeys, scroll, drag) through bundled Python scripts with zero dependencies. Use when the task requires GUI automation or when text-only tools are not enough - looking at what is on screen / taking a screenshot / reading a window, clicking a button or icon, double-clicking, right-clicking, typing into an application, pressing shortcuts such as ctrl+c or alt+tab, scrolling a page or list, drag and drop, selecting text or moving files in a file manager, or automating any Windows desktop app or game that has no CLI/API.
---

# Visual Control (Windows)

Full observe-act loop for the Windows desktop: capture the screen, read
coordinates off the image, then inject real mouse and keyboard input. Everything
is one Python CLI that prints JSON, so every step is verifiable.

Scripts live next to this file:

```
scripts/visual_control.py            # the only entry point you call
scripts/visual_control/              # implementation (pure stdlib)
scripts/visual_control/backends/     # Windows GDI capture + SendInput input
scripts/e2e_input_test.ps1           # end-to-end regression test (Windows)
```

Windows 10/11, Python 3.8+, and nothing else: no pip packages, no pyautogui, no
setup. Capture uses GDI `BitBlt`, input uses `SendInput`, both through `ctypes`.

This distribution is **Windows-only**. Other platforms are rejected with a clear
message; porting means adding one module under `scripts/visual_control/backends/`
(see `references/backends.md`).

## The loop

1. **Observe** - `observe` writes a PNG and returns its path plus the exact
   physical pixel region it covers. Read the image, decide where to act.
2. **Act** - pass the coordinates straight back to `click`, `drag` or `scroll`.
   Never guess: the coordinates in the image *are* the coordinates the input
   commands accept.
3. **Verify** - observe again, or read window state with `windows`. Screenshots
   are cheap; blind clicking is not.
4. **Dry-run anything risky first** - `--dry-run` validates a plan (including key
   names) without touching the pointer or keyboard.

Run from this skill directory (or use absolute paths when the workspace differs):

```bash
python scripts/visual_control.py <command> [options]
```

## Targeting an app, a window, or the active window

`--window` is accepted by `observe`, `click`, `type`, `hotkey`, `scroll`, `drag`
and `focus`. The reference can be:

| Reference | Meaning |
| --- | --- |
| `active` (aliases `fg`, `foreground`, `current`, `focused`) | the window in the foreground right now - "operate on whatever the user is looking at" |
| `last` (alias `prev`) | the window the previous command resolved (persisted in a temp state file, so it survives across calls) |
| `chrome.exe` / `proc:chrome.exe` | a process; if several windows match, the active/largest one wins |
| `pid:12345` | the largest visible window owned by that process id |
| `Notepad` / `"Some Window Title"` | title substring (exact titles win; case-insensitive) |
| `1234567` | a raw HWND from `windows` |

With `--window` set, `--at` becomes **window-relative**, and it also accepts
fractions of the window: `--at 50%,50%` is the centre, `--at 0.1,0.9` the
bottom-left area (handy for buttons that stretch with the window). Without
`--window`, `--at` stays absolute physical pixels.

```bash
# operate on whatever app is active, no title needed
python scripts/visual_control.py observe --window active --with-cursor
python scripts/visual_control.py click --window active --at 50%,50%

# aim at a natively-sized button in a resizable window
python scripts/visual_control.py click --window "Sign in" --at 90%,95%

# switch apps yourself first, then let the agent use it
python scripts/visual_control.py windows --match active          # confirm what is active
python scripts/visual_control.py click --window last --at 320,240

# bring a specific app forward when you need it focused
python scripts/visual_control.py focus --window "Visual Studio Code"
```

Focus behaviour, and why it matters:

- **Already active** → reported as `"focus": "already-active"`; nothing is raised,
  no flicker. This is the cheapest and most reliable mode: ask the user to click
  the app, then use `--window active`.
- **`--focus`** → activates the target first. Windows frequently refuses a
  foreground change made by a background process (the *foreground lock*), and the
  command then fails with a message instead of clicking the wrong place.
- **`--force-focus`** → escalates through `AttachThreadInput`. It usually wins
  where plain activation is refused, but it can briefly flash the previous window,
  so it is opt-in.
- **`--no-activate`** (the default for minimised targets) → leave focus alone and
  just act. Use it when you must not disturb what the user is doing.
- Keystrokes always go to the **focused control**, not to the window you name:
  `type`/`hotkey` with `--window` and without `--focus` return a `warning` telling
  you so. For keyboard work, pair `--window` with `--focus` (or use `active`).

`windows` lists every visible window with `handle`, `title`, `process`, physical
bounds and a `foreground` flag, plus the `active` window on its own. Use
`--match <text>` (or `--match active`) to filter before you pick.

## Commands

### observe - capture the screen

```bash
# whole primary screen, tell me where the cursor is and what windows exist
python scripts/visual_control.py observe --with-cursor --with-windows

# one window (by title, process, HWND, 'active' or 'last'), optional ruler + scale
python scripts/visual_control.py observe --window active --with-cursor
python scripts/visual_control.py observe --window "Photoshop" --grid 100 --scale 0.5
python scripts/visual_control.py observe --window chrome.exe --out shot.png

# a region / a secondary monitor / an explicit path
python scripts/visual_control.py observe --region 0,0,800,600 --out shot.png
python scripts/visual_control.py observe --screen 1 --out-dir ./shots
```

Returns `path`, `region` (`x`,`y`,`width`,`height` in physical pixels),
`image` (`width`,`height`,`scale`), the resolved `window` when targeted, and
optionally `cursor` and `windows`. `--scale` only shrinks the PNG; reported
coordinates stay physical. Observing never changes focus.

### click

```bash
python scripts/visual_control.py click --at 640,360                 # absolute
python scripts/visual_control.py click --at 640,360 --count 2       # double click
python scripts/visual_control.py click --at 640,360 --button right  # context menu
python scripts/visual_control.py click --window "Notepad" --at 40,20 --focus
python scripts/visual_control.py click --window active --at "50%,50%"   # centre of what's active
python scripts/visual_control.py click --window last --at 10,10         # same window as before
python scripts/visual_control.py click --here                        # click under the cursor
python scripts/visual_control.py click --at 640,360 --duration 0.3   # animate the pointer
```

`--at` is absolute unless `--window` is given (then window-relative, accepting
`%`/decimal fractions). Without `--at`, a targeted click uses the window centre.

### type - type text

```bash
python scripts/visual_control.py type --text "hello world"
python scripts/visual_control.py type --text-file notes.txt          # big or quoted text
python scripts/visual_control.py type --window active --text-file notes.txt
python scripts/visual_control.py type --window "Notepad" --focus --text "hi"
Get-Content body.txt -Raw | python scripts/visual_control.py type --text-stdin
python scripts/visual_control.py type --text "line1
line2"                                                               # embedded newline
python scripts/visual_control.py type --text "密码" --method unicode  # non-ASCII
```

Click the target field first, or use `--window ... --focus`. `unicode` (default)
is layout independent and handles CJK/emoji. Use `key` only when the app ignores
synthetic unicode (some games/remote terminals); `clipboard` for very long text.
Prefer `--text-file`/`--text-stdin` over `--text` when the string contains quotes,
backticks, `$` or newlines - that avoids shell escaping entirely. Keystrokes follow
the focused control, so without `--focus` a named window may not receive them (the
result carries a `warning`).

### hotkey - key combinations

```bash
python scripts/visual_control.py hotkey --keys ctrl+shift+s
python scripts/visual_control.py hotkey --keys alt+tab
python scripts/visual_control.py hotkey --window active --keys ctrl+s
python scripts/visual_control.py hotkey --keys enter --repeat 5
python scripts/visual_control.py hotkey --keys f5
python scripts/visual_control.py hotkey --keys ctrl+shift+left
```

Separators are `+` or `,`. Canonical names: `ctrl`, `shift`, `alt`, `win`,
`enter`, `esc`, `tab`, `space`, `backspace`, `delete`, `home`, `end`, `pgup`,
`pgdn`, `left/right/up/down`, `f1`-`f24`, `numpad0`-`numpad9`, and single
characters. Unknown names fail before any key is pressed.

### scroll

```bash
python scripts/visual_control.py scroll --direction down --amount 4
python scripts/visual_control.py scroll --direction up --amount 10 --at 900,500
python scripts/visual_control.py scroll --direction down --amount 5 --window active
python scripts/visual_control.py scroll --direction custom --horizontal -3
```

One "notch" is one wheel click (120 units). Move the pointer over the scrollable
area first (`--at`, or `--window` to use that window's centre) - the wheel goes to
the window under the pointer, not to the focused window.

### drag - press, move, release

```bash
python scripts/visual_control.py drag --to 500,400                       # from here
python scripts/visual_control.py drag --start 100,100 --to 600,500
python scripts/visual_control.py drag --start 20,900 --to 20,300 --duration 0.8
python scripts/visual_control.py drag --start 300,200 --to 700,200 --button right
python scripts/visual_control.py drag --window active --start 10%,10% --to 80%,10%
```

Use a longer `--duration` for drag-and-drop targets that need hover time, and for
canvas/paint style tools where intermediate points matter. With `--window`, both
`--start` and `--to` are window-relative, so one window-relative pair covers the
whole gesture.

### helpers

```bash
python scripts/visual_control.py screens                      # monitors + virtual desktop
python scripts/visual_control.py windows --limit 20           # titles, bounds, HWND, process
python scripts/visual_control.py windows --match active       # just the active window
python scripts/visual_control.py windows --match chrome.exe   # just that app's windows
python scripts/visual_control.py focus --window active        # no-op confirm + reports it
python scripts/visual_control.py focus --window "Firefox" --force-focus
python scripts/visual_control.py backends                     # what works on this machine
python scripts/visual_control.py selftest                     # non-destructive health check
```

## Reading the output

Every command prints one JSON object and sets the exit code (0 ok, 1 failed,
2 bad arguments). Failures are structured, so branch on them:

```json
{"ok": false, "command": "click", "error": "CliError", "message": "--at expects 'X,Y'"}
```

`windows` gives you `handle` (HWND), `title`, `process`, `x/y/width/height`, and
`foreground` - use it to pick the target window and to compute window-relative
points. `screens` gives per-monitor bounds for multi-monitor setups.

## Shell notes (important)

The agent shell on Windows is PowerShell, which mangles comma arguments:

```powershell
python scripts/visual_control.py click --at 640,360     # OK: the CLI rejoins split args
python scripts/visual_control.py click --at 640, 360    # OK too
python scripts/visual_control.py type --text 'hi'       # quote text containing spaces
```

Coordinates are accepted as `640,360`, `640 360` or `640;360`. For text, prefer
`--text-file`. Quote any argument containing spaces or shell metacharacters.

## Safety and limits

- Input is synthetic but real: it moves the user's pointer and types into whatever
  has focus. Confirm before destructive actions (delete, send, purchase, submit).
- `--dry-run` (before the subcommand) plans and validates without acting.
- A click can wake/activate windows and steal focus. Prefer `--window active` when
  the user has already picked the app, or `--window <ref> --focus`; observe again
  afterwards.
- UAC/secure desktops and elevated windows ignore synthetic input. Games using
  anti-cheat may too. `SendInput` is blocked while the secure desktop is up.
- Screen capture of protected content (DRM, some banking apps) returns black.
- Do not use this to bypass authentication, accept terms, or act on behalf of a
  user who has not asked for that.

## Extending

- Coordinate math, new composite actions: `references/recipes.md`.
- Remote desktop, VNC, WebDriver, a mock recorder, or a port to another OS:
  `references/backends.md` (drop a module into `scripts/visual_control/backends/`).
- Selection override without editing code: `VISUAL_CONTROL_BACKEND=windows` (or
  `VISUAL_CONTROL_BACKENDS=a,b`). `VISUAL_CONTROL_STATE_DIR` moves the small
  `last-window.json` state file used by `--window last`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `visual-control supports win32 only` | this skill is Windows-only; port a backend (see `references/backends.md`) |
| `no driver provides ['capture']` | run `backends`; check that Python is 64-bit and GDI is reachable |
| `failed to focus window ... foreground change` | Windows' foreground lock: retry with `--force-focus`, or ask the user to click the app and use `--window active`, or use `--no-activate` |
| `no window matching 'X'` | the message lists the visible titles; use a substring, `--match` first, or `active` |
| `--window last` says nothing to reuse | the temp state file is gone or no command has resolved a window yet; name the window once |
| clicks land on the wrong spot | observe again right before acting; the UI moved |
| clicks ignored in one app | that window is DPI-unaware or elevated: observe it, then click the pixels you see |
| typed text missing characters | slow down with `--interval 0.05`, or use `--method clipboard` |
| hotkey ignored | the window is not focused - add `--focus`, or the app blocks synthetic keys |
| scroll does nothing | pointer is not over the scrollable area - pass `--at` or `--window` |
| PNG all black | protected/DRM surface, or a locked desktop |
| `unknown key name` | use a canonical key name (see `hotkey`) |
