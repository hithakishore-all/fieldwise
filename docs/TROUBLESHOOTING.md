# Troubleshooting

## Setup

| Symptom | Cause | Fix |
| --- | --- | --- |
| `python3.12: command not found` | Python 3.12 isn't installed | Install it from [python.org](https://www.python.org/downloads/) or run `make setup PY=python3` with any Python 3.11 or newer |
| `make: command not found` (Windows) | No make | Use the commands in README, "Commands without make" |
| `playwright install` fails | No network or blocked download | Ignore it. Only the browser smoke test needs it, and that test skips itself |
| `pip` errors building `psycopg` | Old pip | `make setup` upgrades pip first; rerun it |

## Database

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Cannot reach the database at 127.0.0.1:5432/fieldwise: OperationalError` | PostgreSQL isn't running, or the database doesn't exist | Start PostgreSQL and run SETUP_POSTGRES.md step 2 |
| `password authentication failed for user "fieldwise"` | Password in `.env` doesn't match | Fix `DATABASE_URL` in `.env`, or reset the password in psql |
| `Database already has data. Use reset to start over.` | `make seed` only fills an empty database | `make reset` |
| Want to try without PostgreSQL | | `make offline` uses `./fieldwise.db` |

## Using the app

| Symptom | Cause | Fix |
| --- | --- | --- |
| Redirected to "Pick a demo identity" | No session yet | Pick a person. The picker is a demo stand-in for real sign-in |
| "Start and assign" doesn't appear | Model and revision aren't confirmed, or no approved current procedure applies | Confirm Model B rev 2 on C104 as Ana |
| Teo's answer buttons are greyed out | You're signed in as someone other than the assigned technician | Switch to Teo |
| `409 · This case changed since you loaded it` (or "This run changed") | Another tab or person changed it first | Reload the page and try again |
| `409 · Run is paused` | A reviewer withdrew the procedure or its manual, or Ana corrected the revision | Ana starts a fresh run once an applicable procedure is published |
| `403 · Authors cannot publish their own pathway` | Separation of duties | Switch to Ren to publish Ari's draft |
| Host update shows "failed" | The simulated outage was on | Click **Retry delivery**; the receipt is issued once |
| Everything is in a strange state | | `make reset` reloads the demo data |
