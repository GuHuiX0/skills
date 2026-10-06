# Recipe: sign in to a desktop application

Goal: reach an authenticated main window when the credentials are in files and the
user has explicitly asked for the login to be performed.

Preconditions:

- the app window exists (check with `windows`)
- credential files are readable, one value per file, no trailing prompts
- the user consented to this specific login (never store or echo secrets in logs)

## Steps

```bash
# 0. locate the window
python scripts/visual_control.py windows --limit 20

# 1. look before touching anything; note the field coordinates from the image
python scripts/visual_control.py observe --window "<App Window>" --grid 100 --out login.png

# 2. focus, then clear + fill the user name field
python scripts/visual_control.py focus --window "<App Window>"
python scripts/visual_control.py click --window "<App Window>" --at <user_field_x>,<user_field_y> --focus
python scripts/visual_control.py hotkey --keys ctrl+a
python scripts/visual_control.py type --text-file ./secrets/user.txt

# 3. tab to the password field rather than aiming at it
python scripts/visual_control.py hotkey --keys tab
python scripts/visual_control.py hotkey --keys ctrl+a
python scripts/visual_control.py type --text-file ./secrets/password.txt

# 4. submit
python scripts/visual_control.py hotkey --keys enter
# or: python scripts/visual_control.py click --window "<App Window>" --at <submit_x>,<submit_y>

# 5. verify - a new window (or a changed title) is the success signal
python scripts/visual_control.py observe --window "<App Window>" --out after-login.png
python scripts/visual_control.py windows --limit 20
```

## Failure handling

| Observation | Meaning | Next step |
| --- | --- | --- |
| password field still empty in `after-login.png` | focus never reached the field | re-observe, click the field, slow typing with `--interval 0.05` |
| an error banner appeared | wrong credential or extra prompt (2FA, captcha) | stop and report to the user - do not retry blindly |
| window vanished | the app closed or crashed | report; do not relaunch without asking |
| 2FA / captcha / hardware key prompt | not automatable | hand control back to the user |

## Do not

- retry a failed login more than twice (account lockout)
- leave credentials in shell history (`--text-file`, not `--text 'secret'`)
- automate a login the user has not asked for
