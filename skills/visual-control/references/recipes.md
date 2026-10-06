# Recipes: composing the six actions

The six commands are primitives. Real tasks are loops: capture, decide, act,
verify. Below are the patterns that work reliably, then how to store your own.

## Pattern: the observe-act-verify loop

```bash
python scripts/visual_control.py observe --with-cursor --out step1.png
# read step1.png, locate the control, note its centre in physical pixels
python scripts/visual_control.py click --at 742,318
python scripts/visual_control.py observe --out step2.png      # confirm the change
```

Rules that prevent most failures:

- Re-observe immediately before acting; dialogs, tooltips and lazy loading move
  controls between two captures.
- Act on the *centre* of a control, not its edge or a text baseline.
- After a click that opens a menu/list, capture again - the old coordinates are
  usually meaningless one frame later.
- Prefer keyboard entry over clicking a specific text field when the field already
  has focus.

## Pattern: drive one window, not the desktop

```bash
python scripts/visual_control.py windows --limit 20          # find the handle
python scripts/visual_control.py click --window 1234567 --at 200,80 --focus
python scripts/visual_control.py type --text-file ./payload.txt
python scripts/visual_control.py hotkey --keys ctrl+s
```

`--window` makes `--at` window-relative, which survives the window being moved.
Add `--focus`, and if the first click is swallowed, run `focus` then sleep briefly
before clicking - some apps animate activation.

## Pattern: fill a form field reliably

```bash
python scripts/visual_control.py click --window "Sign in" --at 300,210 --focus
python scripts/visual_control.py hotkey --keys ctrl+a          # select existing text
python scripts/visual_control.py type --text-file ./email.txt
python scripts/visual_control.py hotkey --keys tab
python scripts/visual_control.py type --text-file ./password.txt
```

Use `tab` between fields instead of hunting coordinates; it is faster and does not
break when the layout shifts. `ctrl+a` first avoids appending to stale content.

## Pattern: scroll until a target appears

```bash
# repeat: observe -> if the target is visible, click it; otherwise scroll and retry
python scripts/visual_control.py scroll --direction down --amount 5 --at 900,600
python scripts/visual_control.py observe --region 300,200,1200,800 --out scan.png
```

Stop after a fixed number of iterations (10-15) and report failure - endless
scrolling usually means the target is in a different pane.

## Pattern: walk a long history to its oldest entry

A fixed notch count cannot express "go back to the beginning" - the distance
depends on how much history there is. Use the iterative action, which stops when
the view stops changing:

```bash
python scripts/visual_control.py scroll-until-end --window "Microsoft Teams" \
    --direction up --amount 4 --max-scrolls 60 --out ./oldest.png
python scripts/visual_control.py observe --window "Microsoft Teams" --out ./verify.png
```

Then read `oldest.png` to confirm the first message is really there. If the result
said `reason: max-scrolls`, run the same command again from where it stopped - the
walk is stateless, so resuming is just re-running it.

For a targeted search (a date, a name) there is no text matcher to lean on: walk in
chunks with `--out-dir ./shots --snapshot-each` and inspect the numbered frames.
Prefer smaller `--amount` values for virtualised lists, which discard items that
were never rendered.

## Pattern: drag and drop

```bash
# hover first (some drop targets need it), then drag with a slow duration
python scripts/visual_control.py click --at 320,240
python scripts/visual_control.py drag --start 320,240 --to 980,640 --duration 0.9
python scripts/visual_control.py observe --out dropped.png
```

For file managers use the window-relative form so both endpoints share one frame:

```bash
python scripts/visual_control.py drag --start 100,300 --to 700,300 --duration 1.2
```

## Pattern: multiple monitors

```bash
python scripts/visual_control.py screens            # note each monitor's x/y
python scripts/visual_control.py observe --screen 1 --out monitor2.png
python scripts/visual_control.py click --at 3100,540   # physical, cross-monitor
```

Coordinates are global physical pixels; a monitor to the left of the primary has
negative x.

## Pattern: safe destructive actions

```bash
python scripts/visual_control.py --dry-run click --at 480,300 --count 2
```

`--dry-run` covers argument validation, coordinate parsing, key names, buttons and
the whole plan (`journal`). It cannot know that the target button says "Delete" -
confirm those with the user, and observe before and after.

## Storing your own recipes

`recipes/` holds reusable, task-specific procedures. A recipe is a short Markdown
file (or a shell/Python script) with a stable name, the observable precondition,
the exact command sequence, and the check that proves success.
`recipes/login-flow.md` is a worked example.

```bash
python scripts/visual_control.py --backend <name> ...   # per-recipe backend override
```

Write a recipe when you find yourself inventing the same sequence twice; keep it
in this folder so the next run starts from a known-good path instead of guessing.

For composite actions that need real code (loops, retries, image matching), add
one Python file under `scripts/` that calls
`visual_control.cli.main([...])` - it returns the exit code and prints the same
JSON - or import the driver directly:

```python
from visual_control import driver

d = driver.load(("capture", "input"))
x, y, w, h = d.screens()[0].x, d.screens()[0].y, 400, 300
frame = d.grab((x, y, w, h))
d.click(x + 200, y + 150)          # coordinates are the same space as the frame
```
