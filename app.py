"""jobhunter - a local job-hunting assistant. Run: run.bat  ->  http://127.0.0.1:8777"""
import asyncio
import contextlib
import datetime
import base64
import collections, hashlib, io, json, os, pathlib, re, sqlite3, subprocess, sys, time, webbrowser
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Body, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from starlette.requests import Request

import creds, lang, llm, prefill, scrape

# Windows consoles default to cp1252, so a single print of a Romanian job title raises
# UnicodeEncodeError and takes the whole request down with it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

HERE = pathlib.Path(__file__).parent
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
PROFILE = HERE / "profile.json"
DB = HERE / "db.sqlite"

app = FastAPI(title="job")
tpl = Jinja2Templates(directory=HERE / "templates")
# the logo, and anything else that is part of the app rather than part of a person
(HERE / "static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# No password on a local tool is reasonable; accepting instructions from any website is not.
#
# Several endpoints take no parameters, so FastAPI never parses a body and accepts any content type -
# which makes them an ordinary cross-origin form post with no preflight. Any page open in the browser
# could delete rows through /api/recheck, drive Playwright against live board sessions through
# /api/board_states, or send real applications in the user's name through /api/auto/run.
#
# A browser always sends Origin on a cross-site POST and a page cannot forge it, and this app's own
# fetch() calls are same-origin - so one check covers every endpoint, including the ones that predate
# it. A request with NO Origin is allowed: that is curl, the scheduled task and the test client, none
# of which a hostile website can reach.
@app.middleware("http")
async def _only_our_own_page(request, call_next):
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        host = request.headers.get("host") or "127.0.0.1:8777"
        ok = {f"http://{host}", f"https://{host}",
              "http://127.0.0.1:8777", "http://localhost:8777"}
        if origin not in ok:
            return JSONResponse(
                {"detail": "That request came from another website, so it was refused and nothing "
                           "was changed. Open the dashboard yourself and try again there."},
                status_code=403)
    return await call_next(request)

# Measured against the live chain, not guessed: 12 real ads scored in 26.1s three at a
# time and 13.1s six at a time, with no 429 and the breaker untripped. Browser work is
# dispatched one at a time by apply_batch, so this never means six Chromiums.
WORKERS = 6
pool = ThreadPoolExecutor(max_workers=WORKERS)


_SCHEMA_DONE = False


@contextlib.contextmanager
def db():
    """A connection that commits, rolls back AND closes.

    sqlite3's own context manager does the first two and not the third, so every caller was
    leaving a handle open. Nothing complained - until a delete failed on Windows.
    """
    c = _connect()
    try:
        with c:                       # sqlite3's own: commit on success, roll back on error
            yield c
    finally:
        c.close()


def _connect():
    global _SCHEMA_DONE
    # Before connect(), because connect() CREATES the file - so asking afterwards always said
    # yes and the guard below could never fire. Delete db.sqlite under a running server and
    # every request 500'd with "no such table" until a restart, which is the exact thing that
    # check was added to prevent.
    ready = _SCHEMA_DONE and DB.exists()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")   # the weekly run may be writing at the same time
    # ...and the file it was set for still exists. Delete db.sqlite under a running server -
    # a purge, an antivirus quarantine, a second process - and every connection after that
    # opened a fresh empty file with no jobs table, so every request 500'd until a restart.
    if ready:
        return c
    # Set the schema up once per process, not once per connection. ALTER TABLE needs a write
    # lock, so doing this on every connection made every read - opening the dashboard, polling
    # the progress bar - queue behind whatever the search was writing, for up to the full
    # busy_timeout. That is what "it feels stuck, it needs a lot of refreshes" was.
    c.execute("PRAGMA journal_mode=WAL")     # and with WAL, a reader never waits for the writer
    c.execute("""CREATE TABLE IF NOT EXISTS jobs(
        url TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT,
        posted TEXT, description TEXT, fit INTEGER, why TEXT, gaps TEXT,
        -- found is UTC: that is what SQLite's datetime('now') returns, unlike every other
        -- timestamp here, which app.py writes from datetime.now() in local time. Deliberately
        -- left alone - every comparison against it is UTC too (date('now') in sweep_stale, and
        -- ORDER BY found against itself), and changing the default would put two conventions in
        -- one column of rows already written. Never shown in the UI. Worth knowing before you
        -- read it by hand and conclude a run saved nothing: 16:16 local is stored as 13:16.
        status TEXT DEFAULT 'new', cv TEXT, found TEXT DEFAULT (datetime('now')))""")
    for col in ("note TEXT", "lang TEXT", "applied_at TEXT", "untapped TEXT",
                "salary TEXT", "expires TEXT", "terms TEXT",
                # how many times scoring this ad has failed for a reason that is the AD's fault.
                # Without it, fit IS NULL means both "never tried" and "cannot be done", and
                # every search paid for the second kind again.
                "tries INTEGER DEFAULT 0",
                # How many people have already applied. BestJobs publishes it for every ad in
                # the response this app already makes; no other source here offers it.
                "applicants INTEGER",
                # the board's ESTIMATE of the pay, kept apart from `salary`, which is only ever
                # what the employer themselves stated
                "pay_est TEXT",
                # 1 = the board says this employer answers applications. Only BestJobs knows.
                "responsive INTEGER",
                # Where an application stands, according to the BOARD - sent, seen, or closed - and
                # when we last asked. Not the outcome tracker that was removed: nobody maintains
                # these, they come from the employer's side, and the date means an old answer
                # cannot pose as a current one.
                "board_state TEXT", "board_state_at TEXT",
                # Which model produced `fit`. A score only means something beside scores from the
                # same model - measured, the same advert is 85 to one and 35 to another - and the
                # chain falls through silently, so without this a list can hold several scales with
                # nothing to say which row is on which.
                "scored_by TEXT"):                                               # added later
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            fresh_col = True
        except sqlite3.OperationalError as e:
            # "duplicate column name" is the expected one. "database is locked" is not, and
            # swallowing it left the column permanently missing for this process while the
            # schema was marked done anyway.
            if "duplicate column" not in str(e).lower():
                raise
            fresh_col = False
        # Once, on the database that predates the column: every BestJobs figure stored so far is
        # the board's estimate wearing the employer's clothes. It arrived either in `note` (the
        # API value, drawn on the card as an amber warning) or in `salary` (scraped off the page,
        # which prints the estimate when the employer states nothing). Neither can be told apart
        # now, so both become an estimate, which is the weaker and safer claim - and the next
        # search puts the employer's real figure back, from the only source that knows.
        if fresh_col and col.startswith("pay_est"):
            c.execute("UPDATE jobs SET pay_est = salary, salary = '' "
                      "WHERE source='bestjobs' AND COALESCE(salary,'') <> ''")
            c.execute("UPDATE jobs SET pay_est = note "
                      "WHERE source='bestjobs' AND COALESCE(pay_est,'') = '' "
                      "AND note GLOB '[0-9]*'")
            # ...and `note` goes back to being what it is everywhere else - a warning. A bare
            # number there was drawn as an amber pill beside genuine ones like "mass posting".
            c.execute("UPDATE jobs SET note = '' "
                      "WHERE source='bestjobs' AND note GLOB '[0-9]*'")
    # BestJobs' flag was written as "applies on the employer site" and every filter looks for
    # "apply on the employer site", which is not a substring of it. The writer is fixed, but the
    # rows already stored outlive that fix - and each one is still invisible to the auto-apply
    # skip and to the dashboard's "you apply" badge, so it still takes one of the week's slots
    # and is still reported as a failure. Idempotent: the second run matches nothing.
    c.execute("UPDATE jobs SET note = replace(note, 'applies on the employer site', ?) "
              "WHERE note LIKE '%applies on the employer site%'", (EXTERNAL_NOTE,))
    # Committed here, before the caller gets the connection. db() wraps it in `with c:`, which
    # rolls back when the caller's body raises - and that rollback took these one-time migrations
    # with it. The damage is permanent rather than retried: _SCHEMA_DONE is already set for this
    # process, and on the next one the ALTER raises "duplicate column", so fresh_col is False and
    # the pay_est backfill is skipped for ever. One request raising inside `with db() as c` - an
    # Undo pressed too late is enough - and every BestJobs estimate stays filed as the employer's
    # own stated figure. The schema is not the caller's transaction and must not share its fate.
    c.commit()
    _SCHEMA_DONE = True
    return c


def _handed_over(url):
    """An application that stopped at the employer's screening questions and was opened in a
    browser window for you. Marked so the card says where it went and the next 'Select all
    shown' does not send it again."""
    with db() as c:
        c.execute("UPDATE jobs SET status=CASE WHEN status IN ('new','ready') THEN 'opened' "
                  "ELSE status END, note='screening questions - finish it in the browser window' "
                  "WHERE url=?", (url,))


def _mark_applied(c, url):
    """The only way a row becomes applied. Stamps the moment once - a second application to the
    same job (board says 'already applied') must not move the date of the first."""
    c.execute("UPDATE jobs SET status='applied', "
              "applied_at=COALESCE(applied_at, datetime('now','localtime')) WHERE url=?", (url,))


# Every read and every write of the two small JSON files this app keeps. FastAPI runs sync
# endpoints in a thread pool, so "only one user" never meant "only one writer": the profile page
# autosaves while /api/suggest/apply is mid-flight, and the weekly run writes settings while a
# click does. Readers are in here as well, because on Windows os.replace fails while anyone has
# the destination open - a reader alone was enough to break a save, and a save was enough to
# hand a reader an empty profile, which is the very read the anti-wipe guard trusts.
# Re-entrant, so a path that reads and then writes under one lock cannot deadlock on itself.
_FILES = threading.RLock()


# ---------- settings ----------
SETTINGS = HERE / "settings.json"
# what the dashboard remembers between visits. Secrets stay in .env; these are preferences,
# and they travel with a folder copy while .env deliberately does not.
DEFAULTS = {"lang": "auto", "headless": "", "cv_template": "", "cv_ask": True,
            # The language of the buttons and the help text, which is a separate question
            # from the language a CV is written in - plenty of people want the app in
            # Romanian and their CV in English. English until someone says otherwise.
            "ui_lang": "en",
            # which language the "Download my CV" buttons build. It was not saved at all:
            # picking Romanian and reloading put it back to English every time.
            "cv_lang": "en",
            # Romania writes the time as 14:30, so that is the default; "12" is for anyone who
            # reads a clock the other way. It only changes how a time is printed, never what is
            # stored - applied_at stays ISO in the database either way.
            "clock": "24",
            # The county you could actually take a job in. Asked for, never derived from the
            # address on the profile: plenty of people live in a village no town list places,
            # and guessing the wrong county would quietly mislabel every result. Blank means
            # "do not judge distance", which is the right answer until someone says otherwise.
            "home_county": "",
            # A photo is normal on a CV in Romania and unwelcome in the UK or the US, so it is
            # the person's call, per CV, and ignored entirely when there is no photo.
            "photo_in_cv": True,
            # Your own answer per template, once you have changed one. Empty means "use what
            # suits each template" - so the recommendation is a starting point, not a rule that
            # reasserts itself every time the page reloads.
            "cv_photo": {},
            # What the search bar had last time. It lived in the browser's localStorage, so it
            # never moved with the profile to another machine, and the county dropdown was not
            # saved at all - it reset on every reload.
            "search_query": "", "search_location": "", "search_county": "",
            "search_country": "ro",
            # ...and the four under "More filters", which were remembered nowhere at all, so
            # every reload made you narrow the search again. "fresh" matches the markup's own
            # default; the rest mean "any".
            "auto_fresh": "fresh", "auto_work_mode": "", "auto_seniority": "", "auto_ats": "",
            "search_fresh": "fresh", "search_work_mode": "", "search_seniority": "",
            "search_ats": "",
            # the weekly run (auto.py, started by Windows Task Scheduler)
            "auto_enabled": False,
            # Which days it runs. A list, because Windows takes a list - the only thing that
            # ever made this weekly was the app sending exactly one day. ["SUN"] is the old
            # behaviour; all seven is daily.
            "auto_days": ["SUN"], "auto_time": "09:00",
            "auto_query": "", "auto_location": "", "auto_county": "", "auto_country": "ro",
            "keep_signed_in": False,
            "auto_min_fit": 75,
            # applying without you there: off unless you turn it on, and deliberately stricter
            # than the score you would use when reading the ad yourself
            "auto_apply": False, "auto_apply_min_fit": 85, "auto_apply_cap": 5,
        # Job families you do not work in, skipped before an ad is read or scored. Empty by
        # default and deliberately so: "engineer" is junk for one person and the whole point of
        # the app for the next one. Families only - a city, a language or a seniority word here
        # would quietly hide ads you want.
        "skip_families": [],
        # Adult-industry work: videochat studios above all, which advertise constantly on the
        # Romanian boards. Off by default because that is the answer nobody has to think about,
        # and it is a preference rather than a rule - the people looking for it are looking for it.
        "allow_adult": False,
        # Whether the unattended run may answer an employer's screening questions and send.
        #
        # Off by default, and auto_apply.py's own header says why: a model writing answers into a
        # mini-interview and pressing Trimite with nobody watching is a different thing from
        # sending a CV that was already written. Some people want it - somebody running this for
        # another person, daily, cannot be at the keyboard for every posting that asks three
        # questions - so it is a choice rather than a rule, and the guards underneath it are real:
        # answers come only from the profile, anything unanswerable comes back empty, and a single
        # blank field stops the send.
        "auto_answer": False,
        # Ask the boards once a month which saved jobs they still have, and remove the ones they
        # say are gone. Off by default: it only ever deletes on an unambiguous answer, but it does
        # delete, and that is a choice to make rather than inherit.
        "recheck": False, "recheck_days": 30, "recheck_last": ""}


def _migrate_days(s):
    """auto_day (one string) -> auto_days (a list). Read once, so nobody who already had a
    weekly run set up has to set it up again."""
    if not s.get("auto_days") and s.get("auto_day") in DAYS:
        s["auto_days"] = [s["auto_day"]]
    s.pop("auto_day", None)
    saved = s.get("auto_days") or []
    # settings() runs on nearly every request and does not catch TypeError, so a hand-edited
    # "auto_days": 5 would 500 the whole app rather than falling back the way a bad file should
    days = [d for d in saved if d in DAYS] if isinstance(saved, (list, tuple)) else []
    s["auto_days"] = days or ["SUN"]
    return s


def settings():
    with _FILES:
      try:
        return _migrate_days({**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))})
      except FileNotFoundError:
        return dict(DEFAULTS)                 # first run: defaults are the answer, not a fault
      except (OSError, json.JSONDecodeError) as e:
        # Falling back silently would switch keep-signed-in off, blank the county and disable the
        # weekly run - while the Windows tasks carry on existing - and nothing would say so.
        print(f"[settings] {SETTINGS.name} is unreadable ({e}); using defaults until it is saved "
              f"again. Anything you had set is in that file.")
        return dict(DEFAULTS)


def save_settings_file(cur):
    """Write settings the way the profile is written.

    It was a plain write_text in two places: interrupt it and the file is left truncated, which
    the loader then reads as "no settings at all". Same write-then-replace as save_profile, so a
    half-finished save can never replace a good file.
    """
    with _FILES:
        _atomic_write(SETTINGS, json.dumps(cur, indent=1))


@app.get("/api/settings")
def get_settings():
    # `has_photo` rides along so the profile page can ask once instead of fetching the image and
    # taking a 404 in the console every time there is none

    return {**(settings()), "has_photo": bool(photo_path())}


# ---------- the weekly run ----------
# One scheduled task, owned by this folder. Windows keeps it after the app is closed, which is
# the whole point: the search happens whether or not anyone opens the dashboard.
# It was "jobhunter weekly search" until the run stopped being weekly. A scheduled task cannot
# be renamed in place - the rename is a new task plus a deletion - so OLD_TASKS exists to make
# sure the deletion actually happens. Two tasks running the same search at the same minute would
# otherwise be held apart only by the lock in auto.py, and one of them would report a skipped run.
TASK = "jobhunter scheduled search"
OLD_TASKS = ("jobhunter weekly search",)
KEEP_TASK = "jobhunter keep signed in"
# Hipo's session cookie is the shortest at about six hours, and it is renewed to a full
# six every time the site is visited. Every two hours, set by the only board that needs it.
#
# Measured by removing one cookie at a time from a copy of the session and visiting:
#   Hipo     ctlyst_hp_sss IS the session, and a visit rolls it back to a full 6h. Miss six
#            hours and it is gone. This is the constraint.
#   eJobs    a visit does NOT extend a live access token (0.90h -> 0.89h), but once the token
#            has gone a visit mints a fresh 1h one from the refresh token, which runs 13 months.
#            So eJobs heals itself on the next visit and frequent visiting buys nothing.
#   BestJobs ~6 months, renews on a visit. Nothing to do.
#
# Two hours rather than five, so the machine can sleep through a tick without losing Hipo.
KEEP_MINUTES = 120
DAYS = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday",
        "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}


def _ps(script):
    """Run a PowerShell snippet. The ScheduledTask cmdlets are used rather than schtasks.exe
    because their output is objects with English names - schtasks prints localised field labels,
    which is unparseable on a Romanian Windows."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as e:
        # A timeout raises, and nothing up the chain caught it: _task_state, task_state and
        # get_auto all let it through, so GET /api/auto answered 500 and loadAuto's `catch(e){
        # return; }` left the whole scheduled-run panel blank with no message at all. A wedged WMI
        # or a machine under load is enough. A non-zero code is reported the same way everywhere
        # else, so that is what this returns.
        print(f"[ps] {type(e).__name__}: {e}")
        return 1, "", f"{type(e).__name__}: PowerShell did not answer"
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


_TASK = [0.0, None]
_KEEP = [0.0, None]


def task_state():
    """-> what Windows knows about the scheduled task right now.

    Cached briefly: asking costs a PowerShell process, about a second, and it runs on every
    dashboard load for a value that changes only when you press Save.
    """
    if _TASK[1] is not None and time.monotonic() - _TASK[0] < 15:
        return _TASK[1]
    _TASK[:] = [time.monotonic(), _task_state()]
    return _TASK[1]


def keep_state():
    """-> what Windows knows about the keep-signed-in task. Same cache window as the other."""
    if _KEEP[1] is not None and time.monotonic() - _KEEP[0] < 15:
        return _KEEP[1]
    _KEEP[:] = [time.monotonic(), _task_state(KEEP_TASK)]
    return _KEEP[1]


def _task_state(which=None):
    code, out, _ = _ps(
        f"$ErrorActionPreference='SilentlyContinue';"
        f"$t = Get-ScheduledTask -TaskName '{which or TASK}';"
        f"if (-not $t) {{ '{{}}' }} else {{ $i = $t | Get-ScheduledTaskInfo;"
        f"[pscustomobject]@{{ exists=$true; state=[string]$t.State;"
        # ToString('o') - ISO 8601 with the offset - rather than [string], which is a type cast
        # whose format is PowerShell's to choose. It happens to produce US order even under a
        # ro-RO culture, which is lucky rather than guaranteed, and "04.10.2026" would be read as
        # 10 April by the page. _ps itself exists because schtasks printed localised field names;
        # this is the same trap one layer down, and ISO is the format that has no local reading.
        f" next=$(if ($i.NextRunTime) {{ $i.NextRunTime.ToString('o') }});"
        f" last=$(if ($i.LastRunTime) {{ $i.LastRunTime.ToString('o') }});"
        f" result=$i.LastTaskResult }} | ConvertTo-Json -Compress }}")
    try:
        state = json.loads(out) if code == 0 and out else {}
    except json.JSONDecodeError:
        state = {}
    # "we asked and Windows said no" and "we could not ask" are different answers, and both used to
    # come back as exists: False. The second one then read as drift, so a wedged PowerShell told
    # the person in red that their scheduled run was NOT set up, over a task sitting there working
    # perfectly well. An unknown answer is no grounds for an alarm in either direction.
    return {"exists": bool(state.get("exists")), "unknown": code != 0, **state}


def _drop_old_tasks():
    for name in OLD_TASKS:
        _ps(f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue")


def retire_old_tasks():
    """Move anyone still on the old task name across, once, without a gap in between.

    Registering the new one first and deleting second is the whole point: the reverse order, or a
    crash between the two, leaves the automation off with nothing on screen to say so. If Windows
    refuses the new registration, the old task is left alone and keeps doing the job.
    """
    try:
        if not any(_task_state(n)["exists"] for n in OLD_TASKS):
            return
        s = settings()
        if s.get("auto_enabled") and schedule(True, s["auto_days"], s["auto_time"]):
            return                       # Windows refused - the old task stays, still working
        _drop_old_tasks()
    except Exception:
        pass                             # a migration that failed must never stop the app booting


def schedule(on, days, at):
    """Create or remove the search task. Returns "" or a message explaining why it failed.

    `days` is a list of DAYS keys. Windows accepts several, so one day a week and every day are
    the same call with a different list.
    """
    _TASK[1] = None                  # we are about to change it, so do not serve the old answer
    if not on:
        _ps(f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue")
        _drop_old_tasks()                # switching it off has to switch off the old name too
        # Asked, not assumed. The call's exit code was ignored and "" returned regardless, so the
        # page said "turned off" whatever happened - and the drift check only ever looked for the
        # opposite case (switched on here, missing in Windows), so a task that refused to go stayed
        # invisible and kept running on its own schedule for ever.
        return "" if not _task_state()["exists"] else (
            "Windows would not remove the scheduled task - it may still run. Open Task Scheduler "
            f"and delete '{TASK}' by hand.")
    pyw = HERE / ".venv" / "Scripts" / "pythonw.exe"      # windowless: no console pops up
    if not pyw.exists():
        return "The Python environment is missing - start the app once through run.bat first."
    code, _, err = _ps(
        f"$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument 'auto.py' "
        f"-WorkingDirectory '{HERE}';"
        f"$t = New-ScheduledTaskTrigger -Weekly "
        f"-DaysOfWeek {','.join(DAYS[d] for d in days)} -At '{at}';"
        # StartWhenAvailable is what makes this work on a laptop: a run missed because the PC
        # was off happens the next time it is on, instead of being skipped for the week.
        f"$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew "
        f"-ExecutionTimeLimit (New-TimeSpan -Hours 2);"
        f"Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s "
        f"-Description 'jobhunter: job search and scoring' -Force | Out-Null")
    if code == 0:
        _drop_old_tasks()                # ...and only once the new one is actually there
        return ""
    return f"Windows refused to create the scheduled task: {err[:200]}"


def keep_signed_in(on):
    """Create or remove the timer that keeps the board sign-ins alive.

    Board sessions are renewed by being visited - measured on all three - so a visit every few
    hours is enough to stay signed in without typing a password again. Nothing is applied for
    and nothing is searched: it loads each board and saves the refreshed cookies.
    """
    _KEEP[1] = None          # whatever we are about to do, the cached answer is now stale
    _TASK[1] = None
    if not on:
        _ps(f"Unregister-ScheduledTask -TaskName '{KEEP_TASK}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue")
        # This one matters more than the search task, because touch() checks no setting before it
        # runs - unlike run(), which reads auto_enabled first. So a keep-alive task that refused to
        # go on keeps opening a browser every two hours AND keeps handing saved passwords to the
        # boards, while the page says it is off and the help text promises "nothing keeps running
        # in the background afterwards".
        return "" if not _task_state(KEEP_TASK)["exists"] else (
            "Windows would not remove the keep-alive task, so it may still be visiting the boards "
            f"every {KEEP_MINUTES} minutes. Open Task Scheduler and delete '{KEEP_TASK}'.")
    pyw = HERE / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        return "The Python environment is missing - start the app once through run.bat first."
    code, _, err = _ps(
        f"$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument 'auto.py --touch' "
        f"-WorkingDirectory '{HERE}';"
        f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {KEEP_MINUTES}) "
        # Without a duration Task Scheduler is free to stop repeating; 3650 days is "until you
        # turn it off", which is what the switch on the dashboard actually means.
        f"-RepetitionDuration (New-TimeSpan -Days 3650);"
        # No second trigger for "when the machine comes back": -StartWhenAvailable in the
        # settings below already runs a missed repetition as soon as the PC is awake, and both
        # -AtStartup and -AtLogOn are refused here without administrator rights - which fails
        # the WHOLE registration and leaves the old task in place.
        # No -WakeToRun either: waking a sleeping machine every couple of hours to hold a cookie
        # is a poor trade. A missed tick costs the Hipo session, and the scheduled run signs it
        # back in by itself where a saved password allows - that code lives in auto_apply, not here.
        f"$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew "
        f"-ExecutionTimeLimit (New-TimeSpan -Minutes 10);"
        f"Register-ScheduledTask -TaskName '{KEEP_TASK}' -Action $a -Trigger $t "
        f"-Settings $s "
        f"-Description 'jobhunter: keep the board sign-ins alive' -Force | Out-Null")
    return "" if code == 0 else f"Windows refused to create the keep-alive task: {err[:200]}"



def _run_history(limit=20):
    """The last scheduled runs, newest first. [] when there has never been one.

    auto.py writes this; nothing here does. A damaged or missing file is an empty list rather than
    an error, because this is one panel on a dashboard and the rest of it still works.
    """
    try:
        runs = json.loads((HERE / "auto_runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(reversed(runs))[:limit] if isinstance(runs, list) else []

@app.get("/api/auto")
def get_auto():
    s = settings()
    try:
        last = json.loads((HERE / "auto_last.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        last = None
    # keep_signed_in is not an auto_ key but the same panel owns it: without it here the
    # checkbox always drew itself unticked, however the scheduled task was actually set
    task, keep = task_state(), keep_state()
    # Two pieces of state that can drift apart: settings.json says what you asked for, Windows
    # says what is actually scheduled. Nothing compared them, so a task removed behind the
    # app's back - a purge, a failed registration, a tidy-up in Task Scheduler - left the
    # checkbox ticked over nothing at all, and the first symptom was sign-ins expiring again.
    # an answer we could not get is not an answer: neither alarm fires on a PowerShell that
    # did not come back
    pairs = [(n, w, bool(st.get("exists"))) for n, w, st in
             (("the scheduled run", bool(s.get("auto_enabled")), task),
              ("keep me signed in", bool(s.get("keep_signed_in")), keep))
             if not st.get("unknown")]
    drift = [name for name, want, got in pairs if want and not got]
    # ...and the other way round, which nothing looked for. A switch turned off whose task refused
    # to go is worse than the case above, not better: the page says off, and the thing carries on.
    # The keep-alive is the one that bites, because touch() reads no setting before it runs - it
    # goes on opening a browser and handing saved passwords to the boards every couple of hours
    # under a switch that reads OFF and help text promising nothing runs in the background.
    ghosts = [name for name, want, got in pairs if got and not want]
    return {"settings": {k: v for k, v in s.items()
                         if k.startswith("auto_") or k == "keep_signed_in"},
            "task": task, "keep": keep, "drift": drift, "ghosts": ghosts, "last": last,
            # the rolling history, newest first for the panel. Absent until the first run writes it.
            "runs": _run_history()}


@app.post("/api/auto")
def set_auto(body: dict = Body(...)):
    with _FILES:                  # the same read-modify-write as /api/settings, the same lock
        return _set_auto(body)


def _set_auto(body):
    cur = settings()
    for k in ("auto_enabled", "auto_days", "auto_time", "auto_query", "auto_location",
              "auto_county", "auto_country", "keep_signed_in", "skip_families", "recheck",
              "auto_answer",
              "allow_adult",
              "auto_fresh", "auto_work_mode", "auto_seniority", "auto_ats",
              "auto_min_fit", "auto_apply", "auto_apply_min_fit",
              "auto_apply_cap"):
        if k not in body:
            continue
        # The same check /api/settings does, for the same reason: every one of these is written
        # to disk and read back on every request, so the wrong type is not a request that fails
        # once - it is a file that breaks the app until someone edits it by hand.
        # {"auto_query": 123} got written, and then "type what it should search for" tried to
        # .strip() an int on every save after that.
        # the three numbers are clamped a few lines down, which also answers 8.5 and "90" with
        # a sentence about numbers rather than about types
        numeric = isinstance(DEFAULTS[k], int) and not isinstance(DEFAULTS[k], bool)
        if not _same_shape(body[k], DEFAULTS[k]) and not numeric:
            raise HTTPException(400, f"{k} must be {type(DEFAULTS[k]).__name__}, "
                                     f"not {type(body[k]).__name__}")
        if isinstance(body[k], str) and len(body[k]) > 2000:
            raise HTTPException(400, f"{k} is too long")
        cur[k] = body[k]
    cur["auto_days"] = [d for d in (cur.get("auto_days") or []) if d in DAYS]
    if not cur["auto_days"]:
        raise HTTPException(400, "Pick at least one day for it to run on.")
    _guard_auto(cur)
    if cur["auto_enabled"] and not (cur["auto_query"] or "").strip():
        raise HTTPException(400, "Type what the scheduled run should search for.")
    save_settings_file(cur)
    problem = schedule(cur["auto_enabled"], cur["auto_days"], cur["auto_time"])
    if problem:
        raise HTTPException(400, problem)
    # independent of the weekly run on purpose: staying signed in is useful even to someone who
    # never switches the automation on, because it is what stops "not signed in" mid-apply
    problem = keep_signed_in(bool(cur.get("keep_signed_in")))
    if problem:
        raise HTTPException(400, problem)
    return {"ok": True, "task": task_state()}


@app.post("/api/history/import")
async def import_history(body: dict = Body(...)):
    """Fold the applications a board already knows about into the Applied history.

    You apply on Hipo in your own browser, so this app never sees it - the job sits at 'new' and
    keeps offering itself. The board's own list is the truth, and this copies it across. It only
    ever marks things applied; nothing is undone, and the date comes from the board.
    """
    board = body.get("board", "hipo")
    if board not in prefill.APPLICATIONS:
        raise HTTPException(400, f"{board} does not publish a list of your applications")
    if not prefill.session_for(board):
        raise HTTPException(400, f"Not signed in to {board}. Use the sign-in button first.")
    try:
        apps = await off(prefill.board_applications, board)
    except Exception as e:
        raise HTTPException(400, f"Could not read your {board} applications: {e}")

    # prefill.posting_id: the board's own id, because the slug after it differs between the
    # application list and the search results (diacritics, punctuation). One definition, shared
    # with refresh_board_states, which spent a while matching on the whole url instead.
    jid = prefill.posting_id

    marked, unknown = [], []
    with db() as c:
        mine = {jid(r["url"]): r["url"] for r in c.execute(
            "SELECT url FROM jobs WHERE source=?", (board,)) if jid(r["url"])}
        for a in apps:
            url = mine.get(jid(a["url"]))
            if not url:
                unknown.append(a["title"])
                continue
            row = c.execute("SELECT status FROM jobs WHERE url=?", (url,)).fetchone()
            if row and row["status"] == "applied":
                continue
            # ...and today when the board did not say. COALESCE(applied_at, NULL) is NULL, so
            # an import without a date marked the row applied with no date at all - which the
            # card can only render as "date not recorded", and which undo refuses to touch
            # because it compares against a timestamp that is not there.
            c.execute("UPDATE jobs SET status='applied', "
                      "applied_at=COALESCE(applied_at, ?, datetime('now','localtime')) "
                      "WHERE url=?",
                      (f"{a['when']} 00:00:00" if a["when"] else None, url))
            marked.append(a["title"])
    return {"ok": True, "found": len(apps), "marked": marked, "not_in_your_list": unknown}


@app.get("/api/auto/preview")
def auto_preview(min_fit: int = 85, cap: int = 5):
    """What automatic applying would send right now, at these limits.

    The dashboard shows this inside the confirmation, because "5 real applications a week" is
    an abstraction and a list of five employers is not.
    """
    import auto_apply
    me = sys.modules[__name__]            # candidates() only needs db(), which lives here
    picks = auto_apply.candidates(me, prefill, max(0, min(100, min_fit)),
                                  max(1, min(BATCH_CAP, cap)))
    # what a stricter floor would do, so the count is not the only thing you can judge by
    at = {f: len(auto_apply.candidates(me, prefill, f, 10000)) for f in (min_fit, 90, 95)}
    return {"picks": picks, "at_floor": at,
            "boards": {b: prefill.session_for(b) for b in prefill.AUTO_APPLY}}


_RUNNING = []                         # the last process this button started, if it is still alive


@app.post("/api/auto/run")
def run_auto():
    """Run the scheduled search now, in the same way Windows will run it."""
    # auto.py holds the real guard - it has to, because Task Scheduler starts it without asking
    # the app. This is only so a second click can say so, rather than starting a process that
    # takes the lock's word for it and exits a second later looking like it worked.
    if _RUNNING and _RUNNING[-1].poll() is None:
        return {"ok": False, "already_running": True}
    py = HERE / ".venv" / "Scripts" / "python.exe"
    _RUNNING.append(subprocess.Popen([str(py), str(HERE / "auto.py")], cwd=str(HERE),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    del _RUNNING[:-1]
    return {"ok": True}


@app.get("/api/auto/progress")
def auto_progress():
    """How far the run in flight has got - whoever started it.

    The run is its own process, so the progress bar this server keeps is empty while one works:
    step() fills app.PROGRESS in THAT process. Pressing "Run it now" therefore looked like nothing
    happening at all, for minutes - on 27 search terms the first phase alone is 108 requests - and
    the only feedback was a poll every 15 seconds for the finished report.

    Read from the file the run writes every couple of seconds, which also covers the run Windows
    starts on its own. Recent, not merely present: a crashed run leaves its last file behind, and
    "still going" over something that died twenty minutes ago is worse than saying nothing.
    """
    try:
        d = json.loads((HERE / ".auto_now.json").read_text(encoding="utf-8"))
        fresh = (time.time() - float(d.get("when") or 0)) < 20
    except (OSError, ValueError, TypeError):
        return {"running": False}
    if not fresh:
        return {"running": False}
    return {"running": True, "phase": d.get("phase") or "", "pct": d.get("pct") or 0,
            "done": d.get("done") or 0, "total": d.get("total") or 0,
            "note": str(d.get("note") or "")[:200]}


def _same_shape(value, default):
    """Is this value the kind of thing that default is? bools are not ints here."""
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, type(default))


@app.post("/api/settings")
def save_settings(body: dict = Body(...)):
    # One lock across read AND write. Locking settings() and save_settings_file() separately
    # still loses an update: this endpoint and /api/auto both read the whole file, change their
    # own keys and write it all back, so whichever finishes second erases the other's change.
    # Measured: saving the clock while switching the weekly run on kept only one of them.
    with _FILES:
        return _save_settings(body)


def _guard_auto(cur):
    """The rules that decide whether real applications get sent, in one place.

    They used to live only in _set_auto, behind the Save button - and /api/settings writes every
    key in DEFAULTS, which includes auto_apply, auto_apply_min_fit, auto_apply_cap and auto_time,
    checking only the TYPE. So one POST could switch unattended applying on at a floor of 0 and a
    cap of 9999 without ever meeting the rule that applying needs the scheduled run, or the
    confirmation the dashboard shows. Nothing in the page does that and cross-site posts are
    already refused, so this was a missing guard rather than a live hole - but it is the one
    setting in the app that spends somebody's name on an employer's desk, so it should not be
    guarded by the browser alone.

    auto_time matters for a duller reason: /api/settings would accept "99:99", and then every
    later POST /api/auto fails its format check, including the keep-signed-in toggle. The panel
    becomes unsavable until the file is edited by hand.
    """
    try:
        cur["auto_min_fit"] = max(0, min(100, int(cur["auto_min_fit"])))
        cur["auto_apply_min_fit"] = max(0, min(100, int(cur["auto_apply_min_fit"])))
        cur["auto_apply_cap"] = max(1, min(BATCH_CAP, int(cur["auto_apply_cap"])))
    except (TypeError, ValueError):
        raise HTTPException(400, "the score and the cap must be numbers")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cur["auto_time"])):
        raise HTTPException(400, "time must be HH:MM, e.g. 09:00")
    if cur["auto_apply"] and not cur["auto_enabled"]:
        raise HTTPException(400, "Applying happens during the scheduled run, so switch that on too.")


def _save_settings(body):
    cur = settings()
    for k in DEFAULTS:
        if k not in body:
            continue
        # Every setting is written to disk and read back on every request, so a value of the
        # wrong type is not a bad request that fails once - it is a file that breaks the app
        # until someone edits it by hand. {"home_county": 123} made GET /api/jobs 500 on every
        # load, through a restart, while the rest of the page carried on looking fine.
        if not _same_shape(body[k], DEFAULTS[k]):
            raise HTTPException(400, f"{k} must be "
                                     f"{type(DEFAULTS[k]).__name__}, not "
                                     f"{type(body[k]).__name__}")
        if isinstance(body[k], str) and len(body[k]) > 2000:
            raise HTTPException(400, f"{k} is too long")
        cur[k] = body[k]
    if cur["cv_template"] and cur["cv_template"] not in cv_templates():
        raise HTTPException(400, f"no such CV template: {cur['cv_template']}")
    # the same rules the Save button meets, because this endpoint writes the same keys
    _guard_auto(cur)
    save_settings_file(cur)
    return cur


# "English (Advanced)" / "German - B2" / "German: B2" - but not "Serbo-Croatian", so the
# hyphen only counts as a separator when it has spaces around it
LEVEL_SPLIT = re.compile(r"^\s*(.+?)\s*(?:[(:]|\s[-–]\s)\s*([^)]+?)\s*\)?\s*$")


# These four are plain lists of strings, but llm.parse_cv reads a CV written by a human and
# sometimes hands back [{"name": "Driving license Category B"}] instead. That rendered on the
# profile page as "[object Object]" and would have gone into a tailored CV just as literally.
STR_LIST_KEYS = ("links", "skills", "certifications", "hobbies")


def _strs(v):
    """-> a list of non-empty strings, whatever shape the model used for them."""
    # A bare string is ONE item. Iterating it spelled "python, sql" out as ten one-letter
    # skills - on the page and, at the next save, on disk - and a non-list raised, which 500'd
    # every page that reads the profile and left no way to fix it but a text editor.
    if isinstance(v, str):
        v = [v]
    elif not isinstance(v, (list, tuple)):
        v = []
    out = []
    for x in v:
        if isinstance(x, dict):
            # the usual shapes, in the order the models actually emit them
            x = next((x[k] for k in ("name", "title", "value", "text", "label")
                      if isinstance(x.get(k), str) and x[k].strip()), "")
        elif not isinstance(x, str):
            x = "" if x is None else str(x)
        if x.strip():
            out.append(x.strip())
    return out


def _langs(v):
    """Languages are {name, level}. Older profiles stored 'English (Advanced)' strings, and the
    model occasionally still returns one, so normalise both shapes here rather than at each caller."""
    if isinstance(v, str):
        v = [v]                           # "English" is one language, not seven letters
    elif not isinstance(v, (list, tuple)):
        v = []
    out = []
    for x in v:
        if not x:
            continue                      # else None would become the language "None"
        if isinstance(x, dict):
            # str(), because a model that answers {"name": 5} must not take the profile page
            # down with it
            out.append({"name": str(x.get("name") or "").strip(),
                        "level": str(x.get("level") or "").strip()})
        else:
            m = LEVEL_SPLIT.match(str(x))
            out.append({"name": m.group(1), "level": m.group(2)} if m else {"name": str(x).strip(), "level": ""})
    return [x for x in out if x["name"]]


# Set while profile.json is present but cannot be read. An empty profile and an unreadable one
# look identical to every caller, and that is what let a byte-order mark destroy a CV: the page
# rendered blank, the browser saved the blank page back, and the wipe guard - which asks whether
# the profile HAD substance - was asking the unreadable file, which said no.
_PROFILE_BROKEN = [False]


def profile():
    with _FILES:
      _PROFILE_BROKEN[0] = False
      try:
        # utf-8-sig, not utf-8: Notepad and Excel write a byte-order mark, and a person who
        # hand-edits this file is exactly the person whose CV is in it. A BOM is not damage.
        p = json.loads(PROFILE.read_text(encoding="utf-8-sig")) if PROFILE.exists() else {}
        if not isinstance(p, dict):
            raise ValueError("profile.json is not an object")
      except (OSError, ValueError) as e:
        # never 500 the whole app over a damaged file - the profile page must stay reachable
        print(f"[profile] unreadable ({e}); starting from an empty profile")
        _PROFILE_BROKEN[0] = bool(PROFILE.exists())
        p = {}
    p = {**llm.EMPTY, **p}
    p["languages"] = _langs(p.get("languages"))
    for k in STR_LIST_KEYS:
        p[k] = _strs(p.get(k))
    return p


PROFILE_BAK = HERE / "profile.previous.json"


def _has_substance(p):
    """-> True if this profile is worth something, so replacing it with nothing is a mistake."""
    return bool((p or {}).get("experience") or (p or {}).get("skills")
                or ((p or {}).get("summary") or "").strip()
                or ((p or {}).get("name") or "").strip())




def _atomic_write(path, text):
    """Write, then replace, with a temp name nobody else can be holding.

    One fixed "profile.tmp" meant overlapping saves raced each other: on Windows os.replace then
    fails with WinError 32, and a reader landing in the gap got an EMPTY profile - which is the
    same read the wipe guard asks for permission from, so the guard could be walked straight
    past. Measured: 178 of 200 concurrent saves raised, and an empty profile reached disk.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + "-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def save_profile(p):
  with _FILES:
    # The guard belongs HERE, not in post_profile: upload, paste and apply_suggestion all write
    # through this function and none of them went past that check. A weak parse - a scanned PDF
    # whose text layer is noise, a fallback provider making a mess of it - replaced a complete
    # profile and answered 200. _FILES is an RLock, so the profile() call below is fine.
    if not _has_substance(p):
        had = _has_substance(profile())          # also sets _PROFILE_BROKEN
        if had or _PROFILE_BROKEN[0]:
            raise HTTPException(400, "That would have emptied your whole profile, so nothing "
                                     "was saved. If a CV you uploaded came back almost empty, "
                                     "the file probably has no readable text - try the PDF, or "
                                     "paste the text in instead.")
    p["languages"] = _langs(p.get("languages"))
    for k in STR_LIST_KEYS:
        p[k] = _strs(p.get(k))
    # Keep the copy this one replaces. A refusal can only catch the wipes it knows to look for;
    # a previous copy covers the ones it does not - half a CV overwritten, an upload that parsed
    # badly, an edit regretted ten minutes later.
    try:
        if PROFILE.exists() and not _PROFILE_BROKEN[0]:
            # never copy a file we could not read: doing that put the damaged bytes in the
            # backup too, and then "restore the previous copy" had nothing to restore
            _atomic_write(PROFILE_BAK, PROFILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print(f"[profile] could not keep the previous copy: {e}")
    # write-then-replace: a crash or an overlapping save must not leave a half-written profile
    _atomic_write(PROFILE, json.dumps(p, ensure_ascii=False, indent=2))


async def off(fn, *a):
    """Run a blocking call (LLM, http, playwright) off the event loop."""
    return await asyncio.get_running_loop().run_in_executor(pool, fn, *a)


@app.exception_handler(llm.QuotaError)
async def quota_error(request: Request, exc: llm.QuotaError):
    """Out of budget is the user's problem to act on, not a server crash. Deliberately narrow:
    a bare RuntimeError is a bug and should surface as a 500 with a traceback."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(llm.NoModel)
async def no_model(request: Request, exc: llm.NoModel):
    """Same reasoning: a fresh copy with no key yet is a setup step, not a bug. Without this it
    reaches the browser as a 500, and "internal error, restart the app" is the wrong advice -
    restarting changes nothing, pasting a key does."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ---------- pages ----------
# ---------- the interface in two languages ----------
# The templates stay written in English and the translation happens on the way out, keyed by the
# English string. Wrapping 431 strings in t("...") by hand would be 431 chances to break the
# page, and every string nobody has translated yet would have to be found again later; this way
# an unknown string simply stays English, which is a worse interface but never a broken one.
_SKIP = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>)", re.S | re.I)
_TEXT = re.compile(r">([^<>]+)<")
_ATTR = re.compile(r'\b(placeholder|title|aria-label)="([^"<>]+)"')


def ui_lang():
    v = settings().get("ui_lang")
    return v if v in ("en", "ro") else "en"


def t(s, ui=None):
    """One string, translated. Falls back to the English it was given."""
    return lang.RO.get(" ".join(str(s).split()), s) if (ui or ui_lang()) == "ro" else s


def _swap_text(m):
    raw = m.group(1)
    ro = lang.RO.get(" ".join(raw.split()))
    if not ro:
        return m.group(0)
    # keep the indentation and line breaks around it, or the html reflows and diffs become noise
    head = raw[:len(raw) - len(raw.lstrip())]
    tail = raw[len(raw.rstrip()):]
    return f">{head}{ro}{tail}<"


def _swap_attr(m):
    ro = lang.RO.get(" ".join(m.group(2).split()))
    return f'{m.group(1)}="{ro}"' if ro else m.group(0)


def localise(html_text, ui):
    """The rendered page in `ui`. English is returned untouched, byte for byte."""
    if ui != "ro":
        return html_text
    out = []
    # never inside a script or a style block: the page's own JavaScript is not prose
    for i, part in enumerate(_SKIP.split(html_text)):
        out.append(part if i % 2 else _ATTR.sub(_swap_attr, _TEXT.sub(_swap_text, part)))
    return "".join(out)


def page(request, name, **ctx):
    """Render a template and hand it over in the language this person chose."""
    ui = ui_lang()
    html = tpl.TemplateResponse(request, name, {"ui": ui, "T": lang.RO if ui == "ro" else {},
                                                **ctx}).body.decode("utf-8")
    return HTMLResponse(localise(html, ui))


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    # the county list lives in scrape.py, where the matching also happens - rendering the
    # dropdown from it means the two can never drift apart
    return page(request, "dashboard.html",
                counties=[(slug, name) for slug, (name, _towns) in sorted(
                    scrape.COUNTIES.items(), key=lambda kv: kv[1][0])],
                # Same reason as the counties: the template used to keep its own list of which
                # boards this app can submit on, and it drifted twice. The first time BestJobs was
                # missing, so a failed /api/boards left every BestJobs card as a plain link; the
                # comment written about that is still there, and then Hipo did it again. Rendered
                # from prefill, the copy cannot be stale.
                auto_apply=list(prefill.AUTO_APPLY),
                manual_apply=list(prefill.MANUAL_APPLY))


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    return page(request, "profile.html")


# ---------- profile ----------
@app.get("/api/profile")
def get_profile():
    return profile()


# Only what a browser will reliably draw and Chromium will embed. Checked by signature, not by
# the name: a .png that is really something else is either a mistake or an attack.
PHOTO_KINDS = {b"\xff\xd8\xff": ("jpg", "image/jpeg"),
               b"\x89PNG\r\n\x1a\n": ("png", "image/png")}
PHOTO_MAX = 6 * 1024 * 1024


def photo_path():
    """-> the stored photo, or None. Checked by its bytes, not by its name.

    The upload checks the signature and nothing checked it again, so a file left by another
    tool, a hand-copied one, or an interrupted write was base64'd into the CV and declared
    image/jpeg on the strength of its extension - a broken-image box on a document being sent
    to an employer, with no warning anywhere.
    """
    for ext in ("jpg", "png"):
        f = HERE / f"photo.{ext}"
        try:
            if f.exists() and _photo_kind(f.read_bytes()[:16]):
                return f
        except OSError:
            continue
    return None


def _photo_kind(head):
    """-> ("jpg", "image/jpeg") from the leading bytes, or None."""
    return next((v for sig, v in PHOTO_KINDS.items() if head.startswith(sig)), None)


def photo_data_uri(use=None):
    """-> the photo as a data: URI for the CV, or "" when there is none or it is switched off.

    A data URI rather than a file path: the PDF is rendered with set_content, which has no base
    url, so a relative src would silently draw nothing and the first anyone would know is a CV
    with a blank square where a face should be.
    """
    # `use` is the choice made for THIS cv; None means "whatever the profile page says". A photo
    # suits the European one and not the Traditional, so it cannot be a single global answer.
    if not (settings().get("photo_in_cv") if use is None else use):
        return ""
    f = photo_path()
    if not f:
        return ""
    kind = "image/jpeg" if f.suffix == ".jpg" else "image/png"
    return f"data:{kind};base64," + base64.b64encode(f.read_bytes()).decode()


@app.post("/api/profile/photo")
async def upload_photo(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > PHOTO_MAX:
        raise HTTPException(400, f"That image is {len(data)//1024//1024} MB. Please use one "
                                 f"under {PHOTO_MAX//1024//1024} MB.")
    kind = next((v for sig, v in PHOTO_KINDS.items() if data.startswith(sig)), None)
    if not kind:
        raise HTTPException(400, "That does not look like a JPG or a PNG. Those are the two a "
                                 "CV can carry safely.")
    ext, _mime = kind
    for old_file in (HERE / "photo.jpg", HERE / "photo.png"):
        old_file.unlink(missing_ok=True)          # one photo, not a collection
    (HERE / f"photo.{ext}").write_bytes(data)
    return {"ok": True, "kind": ext, "bytes": len(data)}


@app.get("/api/profile/photo")
def get_photo():
    f = photo_path()
    if not f:
        raise HTTPException(404, "no photo saved")
    return FileResponse(f, media_type="image/jpeg" if f.suffix == ".jpg" else "image/png")


@app.delete("/api/profile/photo")
def delete_photo():
    for f in (HERE / "photo.jpg", HERE / "photo.png"):
        f.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/purge")
def purge(body: dict = Body(...)):
    """Delete every trace of this person from this folder. Not undoable, by design."""
    if (body or {}).get("confirm") != "ERASE":
        raise HTTPException(400, "Not confirmed, so nothing was erased.")
    removed, failed = [], []

    # the scheduled tasks first: a weekly run that fires after the data is gone would search
    # against an empty profile and quietly log a failure every week
    for on, fn in ((False, lambda: schedule(False, "SUN", "09:00")),
                   (False, lambda: keep_signed_in(False))):
        try:
            fn()
        except Exception as e:
            failed.append(f"scheduled task: {type(e).__name__}")

    # Empty it before deleting it. A handle held anywhere - another request in flight, a weekly
    # run - would otherwise leave every job and every application on disk while the button said
    # it had erased them.
    try:
        con = sqlite3.connect(DB)
        con.executescript("DROP TABLE IF EXISTS jobs;")
        con.commit()
        con.close()
    except sqlite3.Error as e:
        failed.append(f"emptying the database: {e}")

    files = [PROFILE, PROFILE_BAK, SETTINGS, DB,
             DB.with_name(DB.name + "-wal"), DB.with_name(DB.name + "-shm"),
             HERE / "photo.jpg", HERE / "photo.png",
             prefill.STATE, prefill.BOARD_STATE,
             HERE / "auto.log", HERE / "auto_last.json",
             HERE / "signin.log", HERE / "srv.log", HERE / "srv.err.log"]
    for f in files:
        try:
            if f.exists():
                f.unlink()
                removed.append(f.name)
        except OSError as e:
            failed.append(f"{f.name}: {e}")

    # the tailored CVs, and the browser profile the sign-ins live in
    for d in (OUT, HERE / ".browser"):
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d.name + "/")
        except OSError as e:
            failed.append(f"{d.name}: {e}")

    # the next request rebuilds an empty database, and the process must not serve the old schema
    global _SCHEMA_DONE
    _SCHEMA_DONE = False
    print(f"[purge] removed {len(removed)} item(s): {', '.join(removed)}")
    if failed:
        print(f"[purge] could not remove: {failed}")
    OUT.mkdir(exist_ok=True)      # tailoring writes straight into it and 500s when it is gone
    # "ok" has to mean it. This is the one button whose entire purpose is a promise, and it was
    # answering 200/ok while the database - every job, every application - was still on disk
    # because something held it open.
    return {"ok": not failed, "removed": removed, "failed": failed}


@app.get("/api/profile/cv")
async def profile_cv(template: str = "", lang: str = "en", photo: str = ""):
    """The profile as a PDF, untailored. No model call, so it costs nothing and is instant."""
    me = profile()
    if not _has_substance(me):
        raise HTTPException(400, "Fill in your profile first - there is nothing to put on a CV.")
    if template not in cv_templates():
        template = settings().get("cv_template") or DEFAULT_CV
    if lang not in LABELS:
        lang = "en"
    OUT.mkdir(exist_ok=True)
    # [:56], as the tailored path already does. A 500-character name is what a bad CV parse
    # produces, and it built a path Windows refuses outright.
    who = "".join(ch if ch.isalnum() else "-"
                  for ch in (me.get("name") or "CV"))[:56].strip("-")
    want = None if photo == "" else photo not in ("0", "false", "no")
    path = OUT / f"{who or 'CV'}-{lang}-{template}.pdf"
    await off(lambda: _pdf(me, path, lang, template, want))
    return FileResponse(path, media_type="application/pdf", filename=path.name,
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.post("/api/profile")
def post_profile(p: dict = Body(...)):
    # A page that failed to render shows empty fields, and empty fields collect() as an empty
    # profile. Clearing a CV on purpose is done field by field and leaves a name or a summary
    # behind; arriving with nothing at all is a bug somewhere, not an intention.
    incoming = {**llm.EMPTY, **p}
    had = _has_substance(profile())      # sets _PROFILE_BROKEN as a side effect - read it after
    if _PROFILE_BROKEN[0] and not _has_substance(incoming):
        # There IS a profile on disk; we just could not read it. Saving now writes the blank
        # page over a CV that is perfectly intact, which is how a byte-order mark from Notepad
        # used to destroy one.
        raise HTTPException(400, "Your profile file is on disk but could not be read, so this "
                                 "page came up blank and the save was refused rather than "
                                 "writing that blank page over it. Check profile.json is valid "
                                 "JSON - your data is still in there.")
    if had and not _has_substance(incoming):
        raise HTTPException(400, "That would have emptied your whole profile, so it was not "
                                 "saved. Reload the page - if the fields come back, the page "
                                 "had failed to load rather than your data being gone.")
    save_profile(incoming)
    return {"ok": True}


@app.post("/api/profile/restore")
def restore_profile():
    """Put back the copy from before the last save."""
    try:
        prev = json.loads(PROFILE_BAK.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise HTTPException(400, "There is no previous copy to go back to yet.")
    save_profile({**llm.EMPTY, **prev})
    return profile()


def _untriple(line):
    """Many CV templates fake bold by drawing each glyph 2-4x with a tiny offset, so text
    extraction yields 'CCCGGGSSS' for 'CGS'. Collapse a line only when every run of repeated
    characters divides evenly by the same factor - ordinary prose never does."""
    runs = [(ch, len(list(g))) for ch, g in __import__("itertools").groupby(line)]
    if len(runs) < 3:
        return line
    for n in (4, 3, 2):
        if all(c % n == 0 for _, c in runs) and sum(1 for _, c in runs if c == n) >= 3:
            return "".join(ch * (c // n) for ch, c in runs)
    return line


def _docx_text(data):
    """Every line of a .docx, tables included, in the order they appear on the page.

    python-docx's `paragraphs` skips tables entirely, and a table is how a great many CVs are
    laid out - dates in the left column, the job in the right. Reading only the paragraphs
    returned the name and nothing else, and the profile was built from that without complaint.
    Walking the body in document order keeps each date beside the role it belongs to, which is
    what the parser needs.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = docx.Document(io.BytesIO(data))
    out = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                # a cell can hold its own paragraphs; join them before the row is joined
                cells = [" ".join(x.text.strip() for x in c.paragraphs if x.text.strip())
                         for c in row.cells]
                # a merged cell repeats across the row, and repeating it in the text too makes
                # the model read one job as several
                seen, kept = set(), []
                for c in cells:
                    if c and c not in seen:
                        seen.add(c)
                        kept.append(c)
                if kept:
                    out.append("  ".join(kept))
    return "\n".join(out)


# The whole CV goes to a model, and a model call is the expensive thing this app does. A 22 MB
# text file read fine, took five seconds, and handed 23 million characters straight to it.
CV_MAX = 8 * 1024 * 1024


def _cv_text(name, data):
    ext = str(name or "").lower().rsplit(".", 1)[-1]
    if len(data) > CV_MAX:
        raise HTTPException(400, f"That file is {len(data) // (1024 * 1024)} MB. A CV is a few "
                                 f"pages - please use one under {CV_MAX // (1024 * 1024)} MB.")
    if ext == "pdf":
        import pypdf
        # The advice for a .doc is "Save As a .docx", and the commonest response to that is to
        # RENAME the file - which then reached the library as a zip that is not a zip and came
        # back as a 500 with nothing a person could act on.
        try:
            raw = "\n".join(pg.extract_text() or ""
                            for pg in pypdf.PdfReader(io.BytesIO(data)).pages)
        except Exception:
            raise HTTPException(400, "That file is named .pdf but does not open as one. If you "
                                     "renamed it, use Save As in Word instead - or paste the "
                                     "text in.")
    elif ext == "docx":
        try:
            raw = _docx_text(data)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "That file is named .docx but does not open as one. If you "
                                     "renamed a .doc, use Save As in Word to make a real .docx "
                                     "- or paste the text in.")
    elif ext == "doc" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        # Word 97. Decoding it as text yields a couple of hundred characters of binary noise,
        # which is long enough to pass the "did we read anything" check and be parsed as a CV.
        raise HTTPException(400, "That is an old Word (.doc) file, which this app cannot read. "
                                 "Open it in Word and use Save As to make a .docx or a PDF - or "
                                 "paste the text in instead.")
    else:
        raw = data.decode("utf-8", "ignore")
    return "\n".join(_untriple(l) for l in raw.splitlines())


@app.post("/api/profile/upload")
async def upload_cv(file: UploadFile = File(...)):
    text = _cv_text(file.filename, await file.read())
    if len(text.strip()) < 50:
        raise HTTPException(400, "Could not read text from that file (scanned image PDF?). Paste the text instead.")
    p = _keep_answers(await off(llm.parse_cv, text))
    save_profile(p)
    return p


# No CV states your salary expectation, your notice period or your earliest start - you type
# those on the profile page, and the board's screening questions are answered from them. Reading
# a new CV must not silently blank them.
KEEP = ("salary_expectation", "notice_period", "earliest_start")


def _keep_answers(parsed):
    old = profile()
    for k in KEEP:
        if not (parsed.get(k) or "").strip() and (old.get(k) or "").strip():
            parsed[k] = old[k]
    # Same reasoning, different type: "I am new to the workforce" is something the person ticked
    # about themselves, and no CV says it. parse_cv never returns the key, so EMPTY's False won
    # and every upload quietly untied the search from entry-level work.
    parsed["new_to_work"] = bool(old.get("new_to_work"))
    return parsed


@app.post("/api/profile/paste")
async def paste_cv(body: dict = Body(...)):
    p = _keep_answers(await off(llm.parse_cv, body.get("text", "")))
    save_profile(p)
    return p


# ---------- which LLM ----------
@app.get("/api/llm")
def get_llm():
    cur = {"provider": None, "model": None, "error": None}
    try:
        cur["provider"], cur["model"], _ = llm.active()
        if llm.active(usable_only=True) is None:
            # every provider is breaker-marked: ask() will refuse them all, so the panel must
            # not draw a live marker next to one of them
            cur["error"] = ("Every provider is rate limited or out of quota right now. They "
                            "come back on their own - or add another key.")
            cur["stalled"] = True
        if cur["provider"] == "ollama" and not llm.ollama_up():
            cur["error"] = ("Ollama is selected but is not running on this PC. Start Ollama, "
                            "or pick another provider and paste its key.")
    except RuntimeError as e:
        cur["error"] = str(e)
    live = (cur["provider"], cur["model"])
    return {**cur,
            "chain": [{"provider": p, "model": m, "live": (p, m) == live,
                       "blocked": llm._breaker((p, m)) or ""} for p, m, _ in llm.chain()],
            "paused": sorted(llm.paused()),
            # Automatic is not the same as silent. A switch changed which model answers, and the
            # scores this app produces come from whichever model produced them - so it is said out
            # loud rather than left in a log nobody opens.
            "notes": llm.notes(),
            "providers": {n: {"env": env, "default": dflt,
                              "keyed": bool(llm.cfg(env)) if env else llm.ollama_up(),
                              "paused": n in llm.paused(),
                              # ollama has no key to forget, and a provider with none saved has
                              # nothing to remove either
                              "removable": bool(env and llm.cfg(env))}
                          for n, (env, _, dflt) in llm.PROVIDERS.items()}}


@app.post("/api/llm")
async def set_llm(body: dict = Body(...)):
    p = body.get("provider")
    if p not in llm.PROVIDERS:
        raise HTTPException(400, f"unknown provider {p!r}")
    env = llm.PROVIDERS[p][0]
    key = (body.get("key") or "").strip()
    model = body.get("model") or None

    # A new key replaces the old one for that provider - but only once it has answered. Writing
    # first and testing afterwards means a typo destroys a key that was working, and the person
    # has no way back to it.
    if env and key:
        wrong = llm.key_looks_wrong(p, key)
        if wrong:
            raise HTTPException(400, f"That looks like a {wrong} key, and {p} is selected. "
                                     f"Pick {wrong} in the list, or paste a {p} key. "
                                     f"Nothing was changed.")
        try:
            # this exact key against this exact provider, not the chain: otherwise a dead key
            # gets reported as working because a different provider answered the test
            await off(llm.test_key, p, model, key)
        except Exception as e:
            had = " Your previous key is untouched." if llm.cfg(env) else ""
            # _call marks the breaker before it raises, so a typo used to park the provider for
            # five minutes - taking the WORKING saved key out of the chain with it, while this
            # message promised the opposite.
            llm._BLOWN.pop((p, model or llm.PROVIDERS[p][2]), None)
            llm._save_down()     # the scheduled run reads this from disk, so it must hear it too
            raise HTTPException(400, f"{p} would not accept that key: {e}.{had}")

    # Choosing a provider you have no key for, and leaving the key box blank, skipped the
    # test entirely - then the final check call was answered by some OTHER provider in the
    # chain and reported as "it answered a test call". Say what is actually true instead.
    if env and not key and not llm.cfg(env):
        raise HTTPException(400, f"No key is saved for {p}, and the box is empty. Paste its key "
                                 f"here - nothing was changed.")
    kv = {"LLM_PROVIDER": p, "LLM_MODEL": model}
    if env and key:                      # blank key = keep the one already saved
        kv[env] = key
    # saving a key for a provider you had paused means you want it back
    if p in llm.paused():
        llm.set_paused(p, False)
    llm.set_cfg(**kv)
    try:
        # off the event loop, like every other model call in this file: a chain walk can take
        # a minute with a retrying provider, and on the loop that freezes the whole dashboard
        check = await off(lambda: llm.ask("Reply with JSON only.", 'Return {"ok": true}', 100))
        return {**get_llm(), "check": check}
    except Exception as e:
        raise HTTPException(400, f"Saved, but the test call failed: {e}")


@app.post("/api/llm/pause")
def pause_llm(body: dict = Body(...)):
    """Stop using one provider, or start again. Its key is left exactly where it is."""
    p = body.get("provider")
    if p not in llm.PROVIDERS:
        raise HTTPException(400, f"unknown provider {p!r}")
    try:
        llm.set_paused(p, bool(body.get("paused")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    # Refusing to pause the last one standing: an empty chain fails every call with "no model
    # configured", which reads as a broken app rather than a choice somebody made.
    if not llm.chain():
        llm.set_paused(p, False)
        raise HTTPException(400, "That is the only provider left, so pausing it would stop the "
                                 "app doing anything. Add another one first.")
    return get_llm()


@app.post("/api/llm/order")
def order_llm(body: dict = Body(...)):
    """Put the fallback chain in the order asked for. The first one becomes the model in charge.

    The order mattered and could not be set. The head came from whichever provider was last saved
    in the panel, and the rest followed in alphabetical order - so "use nvidia first, then groq"
    was not expressible, and the list on screen was sorted alphabetically too, which showed a
    first row that was not the one actually leading.

    The head is not only about which model answers first. It is the SCALE every score is compared
    on: scored_by stamps it, the unattended run refuses to apply on a score from a different one,
    and the search re-scores stale rows towards it. Changing it is therefore a real decision, and
    the panel says so rather than treating this as cosmetic.
    """
    want = [str(p) for p in (body.get("order") or [])]
    if not want or any(p not in llm.PROVIDERS for p in want):
        raise HTTPException(400, "order must be a list of known providers")
    if len(set(want)) != len(want):
        raise HTTPException(400, "the same provider twice")
    have = {e[0]: e[1] for e in llm.chain()}
    keep = [p for p in want if p in have]
    if not keep:
        raise HTTPException(400, "none of those providers is usable, so that would be an empty "
                                 "chain and nothing could be scored")
    head, rest = keep[0], keep[1:]
    # The head is stored as the chosen provider, the rest as the pinned order - which is how
    # chain() reads them back. Models are pinned with each one, or a provider that was deliberately
    # set to a specific model would silently fall back to its default.
    llm.set_cfg(LLM_PROVIDER=head, LLM_MODEL=have.get(head) or "",
                LLM_CHAIN=",".join(f"{p}:{have[p]}" if have.get(p) else p for p in rest))
    return get_llm()


@app.post("/api/llm/forget")
def forget_llm(body: dict = Body(...)):
    """Delete a provider's saved key. Not undoable - the key is gone and has to be pasted again."""
    p = body.get("provider")
    if p not in llm.PROVIDERS:
        raise HTTPException(400, f"unknown provider {p!r}")
    if body.get("confirm") != "FORGET":
        raise HTTPException(400, "Not confirmed.")
    llm.forget(p)
    return get_llm()


# How many models one press may try. Each is a real scoring call, so this is the quota the button
# spends - and the dialog says so before it is pressed.
BENCH_TRIES = 6
# How many off-scale rows one run may put back on the primary's scale. A cap because the alternative
# is unbounded: a comparison bug here re-scored the whole backlog every run, rewriting every fit, and
# a bounded version of that mistake costs one batch instead of a quota.
RESCALE_CAP = 25


def _bench_prompt():
    """The real scoring prompt, built from a real advert. -> (system, user, max_tokens)

    Captured by letting llm.score build it and intercepting the call, so it cannot drift from what
    scoring actually sends. A synthetic prompt would be the mistake this button exists to undo.
    """
    with db() as c:
        ad = c.execute("SELECT title, company, location, description FROM jobs "
                       "WHERE LENGTH(description) > 600 ORDER BY found DESC LIMIT 1").fetchone()
    job = (dict(ad) if ad else
           # no adverts yet, so a stand-in - still a whole advert, not a toy
           {"title": "Customer Support Officer", "company": "Example", "location": "Bucuresti",
            "description": "Answer customer questions by phone and email, record them in the CRM, "
                           "and escalate what you cannot resolve. English required. " * 8})
    # Captured through score()'s own `send` hook rather than by swapping llm.ask, which is a module
    # global that concurrent scoring is reading: an 11ms window where every in-flight advert came
    # back fit=0 with no stamp, and 0 is below every floor so the row then became age-sweepable.
    held = {}

    def capture(system, user, max_tokens=8000, tries=5):
        held["args"] = (system, user, max_tokens)
        return {"fit": 0}

    llm.score(profile(), job, send=capture)
    return held["args"]


@app.post("/api/llm/bench")
async def llm_bench(body: dict = Body(default={})):
    """Try this provider's models on a real scoring prompt and report which can do the job.

    Spends quota: one real scoring call per candidate. The dialog in front of it says so.

    Returns every row, including the failures, because the failures are the point - of eight
    candidates measured by hand, four never produced the shape the app needs and one of those was
    the model this app was configured to use.
    """
    provider = (body.get("provider") or "").strip() or llm.cfg("LLM_PROVIDER")
    if provider not in llm.PROVIDERS:
        raise HTTPException(400, "Pick a provider first.")
    entry = llm._entry(provider)
    if not entry:
        raise HTTPException(400, f"No key saved for {provider}. Paste one and save it first.")
    _, current, key = entry
    system, user, max_tokens = await off(_bench_prompt)
    # best-first only to decide what to TRY; what wins is decided by the result, never by the order
    cands = await off(lambda: llm.candidates_for(provider))
    order = ([current] + [m for m in cands if m != current])[:BENCH_TRIES] if current else \
        cands[:BENCH_TRIES]
    rows = await off(lambda: llm.try_models(provider, key, system, user, max_tokens, order))
    best = llm.best_of(rows)
    return {"provider": provider, "current": current, "best": best, "rows": rows,
            "tried": len(rows),
            # said plainly, because it is the cost of accepting the suggestion rather than a detail:
            # every score already in the database came from whichever model produced it
            "scale_shift": sorted({r["fit"] for r in rows if r["ok"]})}


@app.post("/api/llm/bestmodel")
async def llm_best_model(body: dict = Body(default={})):
    """Try this provider's models, best first, and return the first that actually answers.

    A listing says what EXISTS, not what this key may CALL, and nothing in it distinguishes the two -
    so the only honest way to choose is to ask. Saves nothing: the answer goes in the box and the
    person presses Save & test, because this is their model choice and every score the app produces
    comes from whichever model produced it.
    """
    provider = (body.get("provider") or "").strip()
    if provider not in llm.PROVIDERS:
        raise HTTPException(400, "Pick a provider first.")
    entry = llm._entry(provider)
    if not entry:
        raise HTTPException(400, f"No key saved for {provider}. Paste one and save it first.")
    _, current, key = entry
    # Tries more than an automatic repair would: somebody is watching this one, and the wait is the
    # point rather than an interruption to a search.
    # capped and shape-checked: it goes to difflib, which is O(n*m) on a value a caller controls
    want = (body.get("model") or "")[:120]
    if want and not llm.MODEL_ID.fullmatch(want):
        want = ""
    found, tried = await off(lambda: llm.best_working(provider, key, want, limit=8))
    if not found:
        raise HTTPException(400, "None of the models {p} lists would answer for this key. "
                                 "Tried: {t}".format(p=provider, t=", ".join(tried) or "none"))
    return {"model": found, "tried": tried}


@app.get("/api/llm/models")
async def llm_models(provider: str = ""):
    """Models for the provider the dropdown is showing, not whichever one the chain picked."""
    try:
        return await off(lambda: llm.models(provider or None))
    except Exception as e:
        raise HTTPException(400, str(e))


def dead_words(floor=75, seen=6):
    """Words that keep turning up in ads and have NEVER turned up in one that scored well.

    The same count that made a terrible skip list makes good advice. Silently dropping an ad
    because a word in its title has no good hits yet is a 34-sample accident deciding someone's
    week; telling a model "this person has seen 41 ads saying consultant and wanted none of them"
    is just handing over what the evidence says, for a human to overrule by typing anyway.

    Nothing is hidden on the strength of this - it only shapes what gets SUGGESTED.
    """
    bad, kept = collections.Counter(), []
    with db() as c:
        for title, fit in c.execute("SELECT title, fit FROM jobs WHERE fit IS NOT NULL"):
            if fit >= floor:
                kept.append((title or "").lower())
            else:
                bad.update({w for w in re.findall(r"[A-Za-zÀ-ɏ]{4,}",
                                                  (title or "").lower())})
    # Substring, not whole word, and deliberately generous. Tokenising called "lead" unseen while
    # "Team Leader (Sibiu)" was scored 85 - and advising a model away from "lead" is advising it
    # away from Team Leader. When the evidence is this thin the error worth avoiding is
    # discouraging a direction that has already worked.
    if not kept:
        # Nothing has reached the floor, so there is no evidence about any word - and "appears in no
        # good title" is vacuously true of all of them. Returning the lot would have the suggestion
        # endpoint enforce a ban on every common word and hand back nothing.
        return []
    return sorted((w for w, n in bad.items()
                   if n >= seen and not any(w in t for t in kept)),
                  key=lambda w: -bad[w])[:20]


@app.post("/api/terms/from_cv")
def terms_from_cv(body: dict = Body(default={})):
    """Job titles read out of the CV, for the person to pick from. Nothing is applied here.

    Deliberately a separate button rather than part of loading the page: it costs a model call, and
    a suggestion nobody asked for is not worth spending someone's quota on.
    """
    p = profile()
    if not any((p.get(k) or "") for k in ("title", "summary", "skills")) and not p.get("experience"):
        raise HTTPException(400, "Fill in your profile first - there is nothing here to read yet.")
    already = [q.strip() for q in re.split(r"[,;]", body.get("already") or "") if q.strip()]
    dead = dead_words(int(settings().get("auto_min_fit", 75)))
    out = llm.search_terms(p, already, dead, reply_in=ui_lang())
    if not isinstance(out, dict):
        out = {}                     # a salvaged bare array is a legitimate reply, not a traceback
    terms = [_tidy(t) for t in (out.get("terms") or [])
             if isinstance(t, dict) and (t.get("term") or "").strip()]
    # The prompt asks the model to avoid these, and it obeyed on one run and ignored it on the
    # next - returning "Customer Engagement Specialist", built on the one word this person's own
    # results show has never once produced a job they wanted. So it is enforced here rather than
    # requested. Safe to enforce because nothing is hidden from SEARCH by dropping a suggestion:
    # type the term yourself and it is searched exactly as typed.
    lower = [w for w in dead if w]
    kept = [t for t in terms if not any(w in (t["term"] or "").lower() for w in lower)]
    return {"terms": kept[:12], "dropped": len(terms) - len(kept)}


@app.post("/api/suggest")
async def suggestions():
    # What employers actually asked for, from the jobs already scored. Counted locally, so this
    # costs nothing extra and the advice stops being generic CV polish.
    #
    # Filtered to what the profile can ALREADY back, which is the only use the prompt sanctions:
    # lifting something the CV mentions and buries. recurring_gaps returns what the scorer said was
    # MISSING, so left unfiltered it is a list of things this candidate does not have - measured, 14
    # of 15 - handed to a model with "do not mention these", which is about the least reliable
    # instruction there is. It produced a summary claiming banking, ERP and financial advisory
    # experience for somebody whose profile contains none of those words. A model cannot write in a
    # skill it was never shown.
    me = json.dumps(profile(), ensure_ascii=False).lower()
    skip = [f.lower() for f in (settings().get("skip_families") or []) if f.strip()]
    top = recurring_gaps(min_fit=50, limit=15)["gaps"]
    market = [(g["gap"], g["jobs"]) for g in top
              if g["jobs"] > 1 and g["gap"].lower() in me
              # and never towards work they have told the app to skip: steering a CV at a family
              # the search itself filters out is advice against their own stated choice
              and not any(f in g["gap"].lower() for f in skip)]
    out = await off(lambda: llm.suggest(profile(), market, avoid=skip))
    # a model asked for "ONLY a JSON array" returned a single object on one run in four, and the
    # page does list.map() on this - so the panel died with a TypeError and showed nothing
    if isinstance(out, dict) and "path" in out:
        out = [out]
    elif isinstance(out, dict):
        out = next((v for v in out.values() if isinstance(v, list)), [])
    elif not isinstance(out, list):
        out = []
    return _applicable(_no_invented_skills(_no_invented_numbers(out, me), profile()), profile())


# Every digit-run the profile contains. A suggestion may reuse these - rephrasing that keeps "30%"
# is the whole point - but it may not introduce one.
_DIGITS = re.compile(r"\d+")


# Words that carry no claim on their own, so a skill written as "Customer Support (phone)" is not
# refused over the bracket. Everything else in a skills line is a competence being asserted.
_SKILL_FILLER = {"and", "or", "with", "for", "the", "of", "in", "on", "to", "a", "an", "using",
                 "including", "e", "g", "etc", "systems", "system", "skills", "level", "advanced"}


def _applicable(out, prof):
    """Drop suggestions that apply_suggestion would refuse anyway.

    It compares the type at the path before writing, so a string proposed for `education` - which is
    a list of objects - is rejected. Correct, and the person finds out by pressing Use this and
    getting a 400 on a suggestion that was never applicable. Checked here instead, with the same
    walk, so what reaches the panel is what can actually be accepted.
    """
    kept = []
    for s in out:
        node, parts = prof, str(s.get("path") or "").split(".")
        if not parts or not all(parts):
            continue
        # How to reach you is not writing to be improved. The reviewer is asked to sharpen how the
        # CV reads, and every one of these is a fact the person typed - an address or a phone
        # number arriving as a "suggestion" is either a model straying well outside its brief or
        # something worse, and either way the answer is no. Name included: it goes on the PDF and
        # into every application.
        if parts[0] in ("email", "phone", "name", "links", "location"):
            print(f"[suggest] dropped {str(s.get('label'))[:40]!r}: {parts[0]} is yours to set")
            continue
        for k in parts[:-1]:
            if isinstance(node, list) and k.isdecimal() and int(k) < len(node):
                node = node[int(k)]
            elif isinstance(node, dict) and k in node:
                node = node[k]
            else:
                node = None
                break
        last = parts[-1]
        if isinstance(node, list):
            old = node[int(last)] if last.isdecimal() and int(last) < len(node) else None
        elif isinstance(node, dict):
            old = node.get(last)
        else:
            print(f"[suggest] dropped {str(s.get('label'))[:40]!r}: path is not in the profile")
            continue
        if old is not None and type(old) is not type(s.get("value")):
            print(f"[suggest] dropped {str(s.get('label'))[:40]!r}: would change {s.get('path')} "
                  f"from {type(old).__name__} to {type(s.get('value')).__name__}")
            continue
        kept.append(s)
    return kept


def _no_invented_skills(out, prof):
    """A proposed skill may use the profile's own words and no others.

    Measured across three runs: 20 of 20 proposed skills introduced something the profile does not
    contain - API errors, cloud services, CSAT/NPS analysis, automation, data analytics - for a
    profile whose skills are "Technical Support", "CRM Systems", "Salesforce", "Troubleshooting".
    A skills line is read as a flat claim of competence, with no sentence around it to soften it,
    so an addition here is the baldest kind of invention this app can produce.

    Checkable exactly, because the only honest edit to a skills list is to merge, drop or reorder
    what is already there. The redundant-list suggestion that prompted all this still passes.

    Prose is deliberately not treated this way: rephrasing a bullet legitimately introduces ordinary
    words, and the same filter over a summary would reject every honest rewrite.
    """
    # words, not whitespace-split tokens: _fold lowercases and drops diacritics but keeps
    # punctuation, so splitting a JSON blob gives '"customer' and '(salesforce)' and every honest
    # suggestion looked like an invention
    words = lambda t: set(re.findall(r"[a-z0-9]+", scrape._fold(t)))
    known = words(json.dumps(prof, ensure_ascii=False))
    kept = []
    for s in out:
        path = str(s.get("path") or "")
        if not path.startswith("skills"):
            kept.append(s)
            continue
        vals = s["value"] if isinstance(s.get("value"), list) else [s.get("value")]
        new = sorted({w for v in vals for w in words(str(v))
                      if w not in known and w not in _SKILL_FILLER and not w.isdigit()})
        if new:
            print(f"[suggest] dropped a skills rewrite: words not in the profile {new[:8]}")
            continue
        kept.append(s)
    return kept


def _no_invented_numbers(out, me):
    """Drop suggestions that put a number in the CV which the profile does not contain.

    Measured on one profile across two runs of the same reviewer: the first wrote "[X]% of customer
    enquiries", which is the design, and the second wrote "Resolved 150+ monthly enquiries,
    escalating 10% of cases with a 98% satisfaction score". None of those numbers exist anywhere in
    the profile - its only digits are dates, a phone number and a salary. That is a fabricated
    achievement going to an employer, and the prompt has forbidden it the whole time.

    The behaviour varies run to run, which is exactly why this is here: an instruction is advice to
    a model, and "the CV contains nothing the person cannot defend" has to be a fact about the
    program. 7 of 10 survived on a live run, so it trims the dishonest ones rather than the feature.

    [X] passes, having no digits - a blank the person fills in beats a number nobody can account for.
    """
    if not isinstance(out, list):
        return out
    mine = set(_DIGITS.findall(me))
    kept = []
    for s in out:
        if not isinstance(s, dict):
            continue
        made_up = [n for n in _DIGITS.findall(json.dumps(s.get("value"), ensure_ascii=False))
                   if n not in mine]
        if made_up:
            print(f"[suggest] dropped {str(s.get('label'))[:40]!r}: invented {made_up}")
            continue
        kept.append(s)
    return kept


@app.post("/api/suggest/apply")
def apply_suggestion(s: dict = Body(...)):
    if not isinstance(s, dict) or not isinstance(s.get("path"), str):
        raise HTTPException(400, "path must be a dotted string into the profile")
    # Models write **bold** into text they were asked to keep plain, and this text goes into the
    # profile and from there into a PDF an employer reads. _tidy is what the scorer's words already
    # go through; the prompt below also bans it, and both is deliberate - one is an instruction and
    # the other is a rule.
    s = {**s, "value": _tidy(s.get("value"))}
    """Write one accepted suggestion into the profile at its dotted path.

    The path and the value are both model output, so both are checked before anything is
    written. An unchecked walk 500s on an index past the end of a list, and an unchecked value
    of the wrong type (a comma-joined string where the page expects a list) corrupts the profile
    page until you hand-edit the JSON.
    """
    p = profile()
    parts = (s.get("path") or "").split(".")
    if not parts or not all(parts):
        raise HTTPException(400, "suggestion has no path")
    node = p
    for k in parts[:-1]:
        if isinstance(node, list):
            # isdecimal, not isdigit: "\u00b2".isdigit() is True and int("\u00b2") raises, so a
            # superscript in a model-written path came out as a 500 rather than a refusal
            if not k.isdecimal() or int(k) >= len(node):
                raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
            node = node[int(k)]
        elif isinstance(node, dict) and k in node:
            node = node[k]
        else:
            raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
    last, new = parts[-1], s.get("value")
    if isinstance(node, list):
        if not last.isdecimal() or int(last) >= len(node):
            raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
        old = node[int(last)]
    else:
        if not isinstance(node, dict):
            raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
        old = node.get(last)
    # A key the profile does not have is not a correction to it. Without this, a path of
    # "experience.0.headcount" walks fine, finds None, skips the type check below because there is
    # nothing to compare against, and writes an invented field into the entry.
    if old is None and (not isinstance(node, dict) or last not in node):
        raise HTTPException(400, f"the profile has no {s['path']} to improve")
    if old is not None and type(old) is not type(new):
        raise HTTPException(400, f"suggestion would change {s['path']} from "
                                 f"{type(old).__name__} to {type(new).__name__}")
    # The three guards ran over the LISTING only, so they shaped what was offered and nothing
    # checked what was written. A panel left open while the profile changed, or any direct POST,
    # went through on the type check alone - and the docstring's own standard is that "the CV
    # contains nothing the person cannot defend" has to be a fact about the program, not advice.
    if not _applicable([s], p):
        raise HTTPException(400, f"that suggestion no longer fits {s['path']}")
    if not _no_invented_numbers([s], json.dumps(p, ensure_ascii=False).lower()):
        raise HTTPException(400, "that suggestion adds a number your profile does not contain")
    if not _no_invented_skills([s], p):
        raise HTTPException(400, "that suggestion claims something your profile does not")
    if isinstance(node, list):
        node[int(last)] = new
    else:
        node[last] = new
    save_profile(p)
    return p


# ---------- jobs ----------
# Every column except the ad itself. The full text of 500 ads is over a megabyte, it is re-sent
# on every action, and it is only read when someone opens one card - so it is fetched per job
# instead, from /api/job/description.
# How contested a job is, in the two currencies this app can actually measure. QUIET and BUSY
# mirror the dashboard's own colouring of the applicant count; FRESH_DAYS and STALE_DAYS stand in
# for it on the three boards that publish no count. Median age of a waiting job is 3 days, so
# three days really is "nobody has got here yet".
QUIET, BUSY = 25, 150
FRESH_DAYS, STALE_DAYS = 3, 14

LIST_COLS = ("url, source, title, company, location, posted, fit, why, gaps, untapped, "
             "status, cv, found, note, salary, expires, terms, lang, applied_at, "
             "applicants, pay_est, responsive, board_state, board_state_at, scored_by, "
             "LENGTH(description) AS desc_len")


# Words that say nothing about WHAT is missing. "Experience with SQL", "SQL experience",
# "knowledge of SQL" and "SQL" are one shortfall, and counting them apart is why the panel used
# to report the commonest thing employers asked for as appearing in two ads.
FILLER = re.compile(
    r"^(?:prior|previous|proven|demonstrated|strong|solid|deep|good|basic|advanced|hands[\s-]?on|"
    r"formal|relevant|direct|explicit|specific|some|extensive)\s+"
    r"|\b(?:experience|knowledge|proficiency|expertise|familiarity|understanding|background|"
    r"exposure|skills?|competency|competencies|ability)\b"
    # "on" is deliberately absent: stripping it turned "on-site presence in Bucharest" into
    # "site presence bucharest", and this tally is read by a person, not only counted
    r"|\b(?:with|in|of|using|related to|as a|as an)\b", re.I)
# a non-breaking and a non-breaking-hyphen reach us inside model output, and split the tally
GAP_CHARS = str.maketrans({"\u2011": "-", "\u2013": "-", "\u2014": "-", "\u00a0": " ",
                           "\u2019": "'"})


def _gap_key(text):
    """The missing thing itself: '' when nothing is left, which means the gap was all filler."""
    t = FILLER.sub(" ", " ".join(str(text or "").translate(GAP_CHARS).split()).lower())
    return " ".join(t.replace(",", " ").split()).strip(" -.")


@app.get("/api/gaps")
def recurring_gaps(min_fit: int = 0, limit: int = 12):
    """What employers keep asking for that this profile does not answer.

    Every scored job already carries its own gaps and they were only ever shown one card at a
    time. Read together they say something no single card can: the one thing worth learning, or
    the thing you do have and never wrote down. Pure counting - no model call, no quota.
    """
    seen, jobs = collections.Counter(), collections.defaultdict(list)
    with db() as c:
        rows = c.execute("SELECT title, fit, gaps FROM jobs WHERE gaps IS NOT NULL "
                         # applied and opened rows count too: those are the jobs this
                         # person actually went after, which is exactly the signal wanted here
                         "AND gaps != '' AND fit >= ? AND status IN "
                         "('new','ready','opened','applied')",
                         (max(0, min(100, min_fit)),)).fetchall()
    for r in rows:
        try:
            items = json.loads(r["gaps"]) or []
        except (TypeError, ValueError):
            continue
        # Only the short ones. Scoring now asks for the missing thing in 1-4 words, which counts
        # cleanly across ads; rows scored by the older prompt hold whole sentences, and no amount
        # of word-picking turns those into a tally - "experience" and "e.g." win every time. They
        # are skipped rather than mined, and the panel fills up as jobs are scored.
        # normalise first, then judge the length: "experience with order processing systems"
        # is five words of which two are filler, and it belongs in the tally
        for g in {_gap_key(x) for x in items if str(x).strip()}:
            if 0 < len(g.split()) <= 4:
                seen[g] += 1
                jobs[g].append(r["title"])
    return {"scored": len(rows), "counted": sum(seen.values()),
            "gaps": [{"gap": g, "jobs": n, "examples": jobs[g][:3]}
                     for g, n in seen.most_common(max(1, min(50, limit)))]}


@app.get("/api/jobs")
def list_jobs():
    # `far` is computed here rather than stored: the answer changes the moment someone moves, and
    # a stored flag would keep the old answer on every row already scored.
    home = (settings().get("home_county") or "").strip().lower()
    with db() as c:
        rows = [dict(r) for r in c.execute(
            f"SELECT {LIST_COLS} FROM jobs "
            # Inside a score band the order used to be the date found, which is noise: 98% of
            # scores land on a multiple of 5, so the whole "best for you" band is two values
            # wide and everything in it tied. Measured: of 20 jobs at 75+, all sit on 85 or 75
            # and NINETEEN have no applicant count, so the top of the list was ordered by
            # nothing at all.
            #
            # Both signals answer the same question - how many people got there first - and they
            # cover each other exactly. The count is BestJobs only; the posting date is known for
            # 585 of 716 waiting jobs and covers eJobs, Hipo and freehire. A fresh ad has had
            # less time to gather applicants, and an employer three weeks in may be interviewing
            # already.
            #
            # (The previous version claimed uncounted rows "sit between" and did the opposite:
            # every counted row came first, so 1207 applicants outranked an unknown.)
            f"ORDER BY (fit IS NULL), fit DESC, "
            f"CASE "
            f"  WHEN applicants IS NOT NULL AND applicants <= {QUIET} THEN 0 "
            f"  WHEN applicants IS NULL AND COALESCE(posted,'') <> '' "
            f"       AND julianday('now') - julianday(posted) <= {FRESH_DAYS} THEN 0 "
            f"  WHEN applicants IS NOT NULL AND applicants <= {BUSY} THEN 1 "
            f"  WHEN applicants IS NULL AND COALESCE(posted,'') <> '' "
            f"       AND julianday('now') - julianday(posted) <= {STALE_DAYS} THEN 1 "
            f"  ELSE 2 END, "
            # inside a tier: fewest competitors first where that is known, then freshest
            f"COALESCE(applicants, 1000000) ASC, COALESCE(posted,'') DESC, found DESC")]
    # Adult work is kept out of the LIST too, not only out of new searches and out of applying.
    # Otherwise the box says "those never reach your list" while four of them sit in it - every ad
    # found before the box existed, or before it was unticked.
    #
    # Dropped rather than deleted: ticking the box brings them straight back. The extra read is
    # needed because the list query returns the description's LENGTH and not the description, and a
    # videochat studio's title often says nothing at all - one here is called "Trainer/Teamleader".
    if rows and not settings().get("allow_adult"):
        with db() as c:
            adult = {r["url"] for r in c.execute(
                "SELECT url, title, company, description FROM jobs") if scrape.adult_job(dict(r))}
        rows = [r for r in rows if r["url"] not in adult]

    for r in rows:
        loc = (r.get("location") or "").strip()
        # A remote job is near everybody, which is the whole of what the "Near me / remote" filter
        # promises. in_county reads the location field alone, so an ad that is genuinely remote
        # with a head office in Madrid came back far - and remote work is the one case where the
        # office does not matter.
        #
        # ponytail: title and location only, because the list query returns the description's
        # LENGTH and not the description - deliberately, it is the biggest column in the table.
        # So an ad that states remote only in its body is still missed here. A stored flag would
        # catch those (unlike `far`, remoteness does not change when somebody moves house); worth
        # it only if the gap shows up in use.
        if scrape.remote_job(r):
            r["far"] = False
        elif not home:
            # No home county set, so there is no "me" to be near - and this used to leave the key
            # off every row, which made the filter match NOTHING and the empty list blame the
            # filters the person had picked. Remote still answers the question honestly.
            r["far"] = None
        else:
            # Three answers, not two. An ad that names no location is unknown: calling it
            # far puts a warning on every row that omits one, and calling it near prints a
            # "near you" badge this app has no grounds for.
            r["far"] = (not scrape.in_county(loc, home)) if loc else None
    return rows


@app.get("/api/job/description")
def job_description(url: str):
    """The ad text for one job, fetched when you actually open it."""
    with db() as c:
        row = c.execute("SELECT description FROM jobs WHERE url=?", (url,)).fetchone()
    if not row:
        raise HTTPException(404, "unknown job")
    return {"description": row["description"] or ""}


# How far the running search has got. A search is one long POST, so the only way the page can
# show progress is to ask separately while it waits. Three phases, weighted by how long they
# actually take: asking each board is quick, reading the ads is slower, and scoring - one model
# call per job - is most of the wait.
PHASES = {"searching the boards": (0, 10), "reading the ads": (10, 30), "scoring": (30, 100)}
PROGRESS = {"active": False, "phase": "", "done": 0, "total": 0, "pct": 0}


def _finish():
    """The bar is done. Called from a finally, because a search that raised used to leave it
    saying "16%, still going" until the 360-second staleness rule noticed - six minutes with the
    Search button disabled and nothing to explain it."""
    PROGRESS.update(active=False, phase="", done=0, total=0, pct=100)


def step(phase, done=0, total=0):
    lo, hi = PHASES.get(phase, (0, 100))
    share = (done / total) if total else 0
    PROGRESS.update(active=True, phase=phase, done=done, total=total, at=time.monotonic(),
                    pct=round(lo + (hi - lo) * min(1.0, share)))


@app.get("/api/search/progress")
def search_progress():
    # A search that crashed - or a server restarted mid-search - would otherwise leave this
    # saying "62%, still going" for ever, and the page would sit there waiting on it. Nothing
    # updates for a minute means nothing is running.
    # Longer than a provider's breaker wait (300s), because a search that is backing off is
    # still a search that is running - a minute was short enough to declare a healthy one dead.
    if PROGRESS["active"] and time.monotonic() - PROGRESS.get("at", 0) > 360:
        PROGRESS.update(active=False, phase="", done=0, total=0)
    return PROGRESS


def _next_width(width, quota_hits, cap):
    """How many jobs to score at once next, given how the last batch went.

    Halve on any quota error - stepping down one at a time would keep hammering a provider that
    is already refusing - and creep back up one at a time once it stops complaining, so a single
    blip does not cost the rest of the run its speed.
    """
    if quota_hits:
        return max(1, width // 2)
    return min(cap, width + 1)


@app.post("/api/search")
async def search(body: dict = Body(...)):
    p = profile()
    # Education or personal projects count. Someone who has never been paid for work still has
    # something to match against, and refusing them here was the app's only outright block.
    if not any(p.get(k) for k in ("experience", "skills", "education", "projects")):
        raise HTTPException(400, "Fill in your profile first - there is nothing to match jobs "
                                 "against. Your studies or a project counts, not only paid work.")
    try:
        return await _search(body, p)
    finally:
        _finish()


def _gate_pass(p, judged, todo):
    """Re-run the language gate over every stored row -> (todo, vetoed, freed).

    Over everything, not just the unscored rows: without it, widening the language table or
    correcting the gate leaves every previously judged row sitting at its old verdict for ever.
    """
    todo_urls = {j["url"] for j in todo}
    vetoed, freed = [], []
    dropped = set()
    for j in judged:
        ok, reason = llm.language_gate(p, j)
        if not ok:
            vetoed.append((j, reason))
            dropped.add(j["url"])
        elif j["status"] == "vetoed":
            freed.append(j)                    # the gate changed its mind: score it again
            if j["url"] not in todo_urls:
                todo.append(j)
                todo_urls.add(j["url"])
    # one pass at the end: the list was rebuilt per vetoed row, which is O(n*m) over two lists
    # that are both the size of the table
    return [t for t in todo if t["url"] not in dropped], vetoed, freed


def refresh_board_states(boards=None):
    """Ask each board where your applications stand, and write it against the jobs. -> a summary.

    This is what the removed outcome tracker could never be: it costs the user nothing. Four
    buttons that have to be pressed produce an empty tracker, and "3 waiting to hear" that nobody
    updated is a false claim about the world. The boards already know, and all three publish it.

    Matched on the url, then on the board's own posting id within that board - never on a title,
    which would be guessing which application a status belongs to, and a wrong status is worse than
    none. The id is needed because one advert has more than one url: eJobs saves a /user/ prefix its
    application list does not use, and Hipo's company and title segments differ by diacritics.
    Measured on url alone: 10 of 15 applied jobs matched, eJobs only 4 of 8.

    But an id is not unique either - eJobs and Hipo both reuse one across different adverts from the
    same employer (1988726 is two different Intesa roles) - so it decides only where it names exactly
    one stored advert. Where it names several, nothing is written and `ambiguous` counts it.
    """
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = {"read": 0, "matched": 0, "adopted": 0, "ambiguous": 0, "states": {}, "unknown": [],
           "failed": {}}
    for board in (boards or sorted(prefill.APPLICATIONS)):
        try:
            got = prefill.board_applications(board)
        except Exception as e:
            out["failed"][board] = f"{type(e).__name__}: {str(e)[:90]}"
            continue
        out["read"] += len(got)
        with db() as c:
            known = {r["url"]: r["status"] for r in c.execute(
                "SELECT url, status FROM jobs WHERE source = ?", (board,))}
        # the board's id -> every stored advert carrying it. A list, not one url: the id is reused
        # across different adverts from one employer, and keeping the last would file a board's
        # answer about one job against another.
        mine = {}
        for u in known:
            pid = prefill.posting_id(u)
            if pid:
                mine.setdefault(pid, []).append(u)

        def whose(url):
            """-> the stored url this application belongs to, or None rather than a guess."""
            if url in known:
                return url                      # exact: nothing to work out
            same = mine.get(prefill.posting_id(url), ())
            if len(same) > 1:
                # Every row in an application list IS an application, so among adverts sharing an
                # id the applied one is the one being reported. Measured: this is what separates
                # eJobs 1989320, two TELUS adverts worded in opposite order, one applied one vetoed.
                same = [u for u in same if known.get(u) == "applied"] or same
            return same[0] if len(same) == 1 else None

        rows = []
        for a in got:
            if not a.get("state"):
                continue
            url = whose(a["url"])
            if url is None:
                # either not a job in your list, or an id that names more than one of them
                out["ambiguous"] += 1
                continue
            # the read time for board_state_at (that is when WE looked), but the board's own
            # "data aplicarii" for applied_at: the record should say when the application was
            # made, not when this noticed it. Date only, same 00:00:00 as the import above.
            rows.append((a["state"], a.get("state_word", ""), when, url,
                         f"{a['when']} 00:00:00" if a.get("when") else ""))
        for a in got:
            if a.get("state"):
                out["states"][a["state"]] = out["states"].get(a["state"], 0) + 1
            elif a.get("state_word") or a.get("title"):
                # a word none of ours covers. Named rather than filed under the nearest match, so a
                # board inventing a fourth state shows up as itself.
                out["unknown"].append(f"{board}: {a.get('state_word') or a.get('title', '')[:40]}")
        if rows:
            with db() as c:
                for state, word, stamp, url, filed in rows:
                    out["matched"] += c.execute(
                        "UPDATE jobs SET board_state = ?, board_state_at = ? WHERE url = ?",
                        (f"{state}:{word}" if word else state, stamp, url)).rowcount
                    # Being ON the board's list IS the application. This read the truth and then
                    # declined to act on it: a row the board calls Trimisă sat at 'opened' with
                    # "pressed apply, no confirmation seen" against it, because eJobs hangs on its
                    # redirect and the app would not claim a send it had not watched land. The
                    # board is the one place that actually knows, so its answer settles it.
                    #
                    # Only upwards, and never over 'applied': this promotes a row nobody could
                    # confirm, and must not rewrite a date or a history that already exists.
                    # applied_at is the board's own date where it gave one, so the record
                    # says when the application was really made.
                    out["adopted"] += c.execute(
                        "UPDATE jobs SET status='applied', "
                        "applied_at = COALESCE(applied_at, NULLIF(?, ''), datetime('now','localtime')), "
                        "note = CASE WHEN note LIKE '%no confirmation%' THEN '' ELSE note END "
                        "WHERE url = ? AND status <> 'applied'", (filed, url)).rowcount
    return out


@app.post("/api/board_states")
async def api_board_states():
    """Refresh what the boards say about your applications. Reads only; sends nothing."""
    return await off(refresh_board_states)


def recheck_jobs(on_progress=None):
    """Ask the boards which saved jobs still exist and delete the ones they say are gone.

    -> {"asked": n, "gone": n, "gone_good": n, "why": {reason: n}}

    The honest version of the age rule: it asks instead of guessing, and removes a row on exactly
    three answers - a 404 or 410 from the board, a closing date the employer has let pass, or a page
    that carries no advert at all. That last one is the only signal that works on eJobs and Hipo,
    which answer 200 for an advert that is not there. Anything it could not read is kept, so a bad
    connection costs nothing but time.

    Rows nobody has touched, exactly like the sweep: applied, opened, tailored and skipped all stay
    whatever a board now says, because that list is a record of what you did.
    """
    floor = int(settings().get("auto_min_fit", 75))
    with db() as c:
        rows = [(r[0], r[1] if r[1] is not None else -1, r[2] or "") for r in c.execute(
            "SELECT url, fit, source FROM jobs WHERE status IN ('new','ready','vetoed') "
            "AND (cv IS NULL OR cv = '')")]
    doubt = {}
    gone = scrape.still_listed([(u, src) for u, _, src in rows], on_progress=on_progress,
                               report=doubt)
    why = {}
    for reason in gone.values():
        why[reason] = why.get(reason, 0) + 1
    good = sum(1 for u, fit, _ in rows if u in gone and fit >= floor)
    if gone:
        with db() as c:
            c.executemany("DELETE FROM jobs WHERE url = ? AND status IN ('new','ready','vetoed') "
                          "AND (cv IS NULL OR cv = '')", [(u,) for u in gone])
    # One lock across read AND write, the same as /api/settings and Save the schedule. Locking
    # settings() and save_settings_file() separately reads the whole file, then writes the whole
    # file back, and anything saved in between is erased by the second half. The window here is two
    # lines rather than the length of the recheck - the read is after still_listed, not before it -
    # but "narrow" is not "closed", and this runs while somebody is using the page.
    #
    # ponytail: a threading lock, so it still does not cover auto.py running this in its own
    # process. Shared-file locking if that ever bites; the window is microseconds.
    with _FILES:
        cur = settings()
        cur["recheck_last"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        save_settings_file(cur)
    return {"asked": len(rows), "gone": len(gone), "gone_good": good, "why": why,
            # a board whose answers looked like a broken parser, so none of them were acted on
            "doubted": doubt.get("doubted", [])}


def recheck_due(s=None):
    """-> True if a monthly recheck is switched on and one has not run inside the window."""
    s = s or settings()
    if not s.get("recheck"):
        return False
    last = (s.get("recheck_last") or "").strip()
    if not last:
        return True
    try:
        when = datetime.datetime.strptime(last[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return True                         # unreadable stamp: treat as never, not as never again
    return (datetime.datetime.now() - when).days >= max(1, int(s.get("recheck_days", 30)))


SHORTLIST = HERE / ".shortlist.json"
# How many of the waiting jobs go to the ranker. Ten because the question is "which of these today",
# and a model asked to order forty produces an order nobody reads past the top of anyway.
# How many of the top band the ranking is asked about. Ten was enough when it only named three;
# it now also supplies the order shown on each card, and the band is bigger than ten - measured, 46
# jobs at the floor holding two distinct scores, with 40 of them carrying nothing to break a tie.
# Capped, because this is one prompt and a job summary is a couple of hundred characters.
SHORTLIST_IN = 40


def shortlist_rows(floor=None):
    """The jobs a ranking would be about: waiting, at or above the floor, best first.

    Same order the dashboard shows, so the ranking reorders what is in front of you rather than
    some other list the page never displays.
    """
    floor = int(settings().get("auto_min_fit", 75) if floor is None else floor)
    with db() as c:
        return [dict(r) for r in c.execute(
            f"SELECT url, title, company, fit, why, gaps, applicants, salary, status "
            f"FROM jobs WHERE fit >= ? AND status IN ('new','ready') "
            f"ORDER BY fit DESC, COALESCE(applicants, 1000000) ASC, found DESC LIMIT {SHORTLIST_IN}",
            (floor,))]


def _shortlist_cached(urls):
    """The stored ranking, but only if it was computed for exactly these jobs.

    Keyed on the set of urls, not on a time. A ranking is only true of the jobs it saw: apply to
    two of them and yesterday's three are wrong, however recent they are.
    """
    try:
        got = json.loads(SHORTLIST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(got, dict):
        return None                  # a cache file holding an array is a cache miss, not a crash
    return got if got.get("for") == sorted(urls) else None


@app.post("/api/shortlist")
async def api_shortlist(body: dict = Body(default={})):
    """Rank the waiting jobs against each other and name the few to do today.

    Advisory: nothing here is written back to `fit`. The scorer rates each ad alone and lands
    almost everything on the same handful of values - 923 ads produced 23 distinct scores and never
    one above 85 - so this asks the question a score cannot answer, which is how they compare.
    """
    rows = shortlist_rows()
    if not rows:
        return {"picks": [], "order": [], "note": "", "jobs": []}
    urls = [r["url"] for r in rows]
    if not body.get("refresh"):
        hit = _shortlist_cached(urls)
        if hit:
            return {**hit, "cached": True}
    jobs = [{"id": i + 1, "title": r["title"], "company": r["company"], "fit": r["fit"],
             "why": r["why"], "gaps": r["gaps"], "applicants": r["applicants"],
             "salary": r["salary"], "tailored": r["status"] == "ready"}
            for i, r in enumerate(rows)]
    out = await off(lambda: llm.shortlist(profile(), jobs, reply_in=ui_lang()))
    # A reply can legitimately be a list - _parse_reply salvages bare arrays - and ids can come back
    # as strings, which nothing in the prompt forbids. Neither should be a traceback or a silently
    # empty panel, so both are coerced here rather than trusted.
    if not isinstance(out, dict):
        out = {}
    by_id = {i + 1: r for i, r in enumerate(rows)}

    def _ident(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    picks = [{"url": by_id[_ident(p.get("id"))]["url"],
              "title": by_id[_ident(p.get("id"))]["title"],
              "company": by_id[_ident(p.get("id"))]["company"],
              "fit": by_id[_ident(p.get("id"))]["fit"],
              # _tidy like every other model sentence: it is what takes out em-dashes, markdown
              # and the Turkish cedilla a model reaches for when it means Romanian's ș and ț
              "why": _tidy((p.get("why") or "").strip())}
             for p in (out.get("picks") or []) if isinstance(p, dict)
             and _ident(p.get("id")) in by_id]
    got = {"for": sorted(urls), "picks": picks,
           "order": [by_id[_ident(i)]["url"] for i in (out.get("order") or [])
                     if _ident(i) in by_id],
           "note": (out.get("note") or "").strip(),
           "when": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    try:
        SHORTLIST.write_text(json.dumps(got), encoding="utf-8")
    except OSError:
        pass                      # a cache we could not write is not worth failing the call over
    return {**got, "cached": False}


@app.post("/api/recheck")
async def api_recheck():
    """Run the recheck now, whatever the schedule says. The manual half of the same switch."""
    return await off(recheck_jobs)


def sweep_stale(floor):
    """Delete ads that have stopped being worth keeping. -> (how many, how many at `floor`+).

    The ad's own closing date decides, and MAX_AGE_DAYS is only for ads that give none.

    This used to be `too old OR past its expiry`, which meant age deleted an ad even when the
    employer had stated in writing that it was still open. Measured on this database: of 175
    stored eJobs ads carrying a closing date, 172 say 30 days after posting - so the sweep was
    destroying more than half of every eJobs ad's life, and one of the rows it took was scored 85
    and still live. eJobs is the only board here that publishes the date at all; for BestJobs,
    Hipo and freehire there is nothing to consult and the guess is all there is.

    Only rows nobody has touched: applied, opened, tailored and skipped all stay, and so does
    anything holding a CV, exactly as with Clear results.
    """
    stale = ("status IN ('new','vetoed') AND (cv IS NULL OR cv = '') AND "
             "CASE WHEN COALESCE(expires, '') <> '' "
             #    the employer's own answer, in both directions: gone once it is behind us, and
             #    kept until then however old the posting is
             "     THEN expires < date('now') "
             #    A job you said was worth your time is never deleted on a guess. The age rule is
             #    a proxy for "the board took it down" and a poor one - it measures age, not
             #    removal - and it destroyed two jobs scored 85 in two days, both still open.
             #    These leave when the employer's own date says so, when you act on them, or when
             #    an apply attempt finds the posting closed. Not before.
             "     WHEN COALESCE(fit, -1) >= :floor THEN 0 "
             #    below the floor, nothing stated: fall back to age. bestjobs publishes no posted
             #    date either, so falling back again to when we first saw it is the difference
             #    between those rows expiring and living for ever
             "     ELSE COALESCE(NULLIF(posted, ''), found) < date('now', :age) END")
    age = {"age": f"-{scrape.MAX_AGE_DAYS} days", "floor": int(floor)}
    with db() as c:
        # One WHERE for both statements, so the count cannot disagree with the delete.
        #
        # Now that the age rule cannot touch them, a swept job at or above the floor can only be
        # one the EMPLOYER closed - which is not a loss but is still news, because it is a job you
        # wanted and it has gone. Worth saying; nothing can be done about it.
        good = c.execute(f"SELECT COUNT(*) FROM jobs WHERE {stale} AND fit >= :floor",
                         age).fetchone()[0]
        return c.execute(f"DELETE FROM jobs WHERE {stale}", age).rowcount, good


def _store_scores(jobs, results, warnings):
    """Write one batch of scores, and return how many of them failed.

    Its own connection and its own transaction, so a batch is durable the moment it is written.
    The loop that calls this used to collect every result and write them all once at the end -
    under a comment saying "a partial result is worth keeping if a later chunk fails", which is
    exactly what it did not do. Two ways a whole search's worth of scoring was thrown away:

      - a database error. The inner guard catches TypeError, ValueError and AttributeError, which
        is a MALFORMED REPLY; sqlite3.OperationalError ("database is locked", reachable whenever
        the scheduled run holds the write lock past the 15s busy_timeout) is none of those, so it
        unwound the whole transaction and rolled back every score already written beside it.
      - navigating away from the dashboard mid-search. Starlette cancels the task, CancelledError
        unwinds _search, and nothing had been written yet at all.

    Either way the model calls were paid for and nothing was kept. Now the work is banked as it
    lands: a failure costs the batch in hand, never the ones before it.
    """
    failed = 0
    with db() as c:
        for j, s in zip(jobs, results):
            if isinstance(s, Exception):
                failed += 1
                if isinstance(s, llm.QuotaError):
                    # out of credits says nothing about this ad, so it does not count against
                    # it - the credits come back and the ad deserves another go
                    if str(s) not in warnings:
                        warnings.append(str(s))
                else:
                    c.execute("UPDATE jobs SET tries=COALESCE(tries,0)+1 WHERE url=?", (j["url"],))
                print(f"[score] {j['title']}: {s}")
                continue
            # the same scrub the CV gets: models emit **bold** and em-dashes into the reasoning
            # too, and it renders literally on the dashboard
            try:
                if not isinstance(s, dict):
                    raise TypeError(f"score returned {type(s).__name__}, not an object")
                # ...and it has to be an ANSWER. A model too small to follow the schema returns
                # a valid object full of the wrong keys; writing that stored fit=NULL, which is
                # the same thing the next search reads as "never scored" - so the job stayed
                # invisible, nothing said why, and every later search paid to score it again.
                try:
                    fit = int(s["fit"])
                except (KeyError, TypeError, ValueError):
                    raise TypeError("score came back without a usable 'fit' "
                                    f"(keys: {sorted(s)[:6]}) - the model is probably too small "
                                    f"to follow the format")
                s["fit"] = max(0, min(100, fit))
                c.execute("UPDATE jobs SET fit=?,why=?,gaps=?,untapped=?,scored_by=? "
                          "WHERE url=?",
                          (s.get("fit"), _tidy(s.get("why") or ""),
                           json.dumps(_tidy(s.get("gaps", [])), ensure_ascii=False),
                           json.dumps(_tidy(s.get("untapped", [])), ensure_ascii=False),
                           # which model's scale this number is on. The chain falls through
                           # silently, so without it a list holds several scales and cannot say
                           # which row is on which - measured, 85 from one model is 35 from another.
                           (s.get("_by") or "")[:80], j["url"]))
            except (TypeError, ValueError, AttributeError) as e:
                # one malformed reply must cost one job, not the whole transaction - every score
                # already written in this batch would otherwise be rolled back with it
                failed += 1
                c.execute("UPDATE jobs SET tries=COALESCE(tries,0)+1 WHERE url=?", (j["url"],))
                print(f"[score] {j['title']}: unusable reply: {e}")
    return failed


async def _search(body, p):
    queries = [q.strip() for q in re.split(r"[,;]", body.get("query", "")) if q.strip()]
    # An empty box used to fall back to [""], which asks every board for everything: on a listing
    # site that is thousands of ads, hydrated and scored at one model call each. "Run it now" has
    # refused an empty box from the beginning; the Search button never did, so the one that spends
    # the quota was the one with no guard on it.
    if not queries:
        raise HTTPException(400, "Type what to search for first - an empty box would ask every "
                                 "board for every job it has.")
    loc = body.get("location", "")
    city = loc                      # kept before the county fallback below overwrites it
    county = (body.get("county") or "").strip().lower()
    # A city is more specific than its county, so it wins. With only a county, send that: eJobs
    # filters on it properly, Hipo understands some of them, and scrape.in_county below catches
    # whatever neither of them honoured.
    if county and not loc:
        loc = county
    country = body.get("country", "ro")
    filters = body.get("filters") or {}
    boards = body.get("boards") or scrape.SOURCES
    limit = int(body.get("limit", 20))

    # Phase 1: discover cheaply - one request per board per query, no detail pages yet.
    found, warnings = [], []

    # Country reaches one board in four. scrape.discover passes it to freehire alone; eJobs, Hipo
    # and BestJobs are Romanian sites and answer in Romanian jobs whatever is asked. So picking
    # Germany used to return German ads from freehire and Romanian ads from the other three, mixed
    # together with nothing saying which was which - the same shape as the work mode bug, one
    # control along, and this one sits in the main bar with no caveat under it.
    #
    # There is no post-filter to be had here: a location is free text and "Berlin, Germania" is not
    # reliably separable from a Romanian ad mentioning Berlin. But the three cannot serve the
    # question at all, so asking them is noise by construction - they are skipped, and it is said
    # out loud rather than left for somebody to notice in the results.
    abroad = (country or "").strip().lower()
    if abroad and abroad not in scrape.WORLDWIDE and abroad != "ro":
        can = [b for b in boards if b == "freehire"]
        if can and len(can) < len(boards):
            warnings.append(
                f"searching {abroad.upper()} on freehire only - eJobs, BestJobs and Hipo list "
                f"Romanian jobs and would have answered in them whatever was asked")
            boards = can
        elif not can:
            warnings.append(f"none of the boards picked can search {abroad.upper()} - "
                            f"only freehire has jobs outside Romania")
    asked, to_ask = 0, max(1, len(boards) * len(queries))
    step("searching the boards", 0, to_ask)
    with db() as c:
        prior = {r[0]: r[1] for r in c.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source")}
    for b in boards:
        got = []
        for q in queries:
            try:
                got += await off(lambda bb=b, qq=q: scrape.discover(
                    bb, qq, loc, limit, country=country, filters=filters))
            except Exception as e:
                # Name the term and the status. A failed discover means that search term found
                # NOTHING on that board for the whole run, and the message said only "ejobs did
                # not answer this time (HTTPStatusError)" - three identical lines that named no
                # term, no status, and gave no hint that three of the searches had simply not
                # happened. eJobs rate-limits hard enough to produce this every single run.
                code = getattr(getattr(e, "response", None), "status_code", "")
                warnings.append(f"{b} did not answer for '{q[:40]}'"
                                + (f" (HTTP {code})" if code else f" ({type(e).__name__})")
                                + " - that search found nothing on this run")
                print(f"[scrape] {b} failed on {q!r}: {type(e).__name__}: {e}")
            finally:
                asked += 1
                step("searching the boards", asked, to_ask)
        if not got and prior.get(b):
            warnings.append(f"{b}: 0 results but {prior[b]} stored previously - parser may be broken")
        found += got

    # one posting reaches us twice: the same url from two sources, or the same role listed under
    # both the employer and its ATS subdomain. Dedupe here, before anything hits the database.
    seen, uniq = set(), []
    for j in found:
        keys = [j["url"]]
        if j.get("title") and j.get("company"):
            keys.append((j["title"].lower().strip(), j["company"].lower().strip()[:18]))
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        uniq.append(j)
    found = uniq

    # Phase 2: fetch detail pages only for postings we have never seen. A repeat search now costs
    # one request per board instead of one per posting.
    with db() as c:
        known = {r[0] for r in c.execute("SELECT url FROM jobs")}
    new_urls = [j for j in found if j["url"] not in known]

    # Whole job families you do not work in, dropped before they are read or scored. This is where
    # the scoring bill actually goes: two thirds of everything scored so far came in under 25, and
    # fixing the search terms does not stop it - "support" matches "Technical Support Engineer" as
    # readily as "Customer Support Officer". Measured: 28% of the wasted calls, and not one of the
    # 34 jobs that scored 75+ would have been dropped.
    fams = settings().get("skip_families") or []
    # by family, not just how many: a count cannot tell you that one rule is eating a job you want.
    dropped_by = {}
    kept = []
    for j in (new_urls if fams else []):
        hit = scrape.off_target(j.get("title", ""), fams, queries)
        if hit:
            dropped_by[hit] = dropped_by.get(hit, 0) + 1
        else:
            kept.append(j)
    if fams:
        off_family, new_urls = len(new_urls) - len(kept), kept
    else:
        off_family = 0

    # The ads we already have, brought up to date from phase 1 alone - no detail page, no extra
    # request. How many people have applied changes by the hour and was otherwise frozen at
    # whatever it was the day the ad was first seen; the ON CONFLICT arm below never reached
    # these rows, because they never get as far as the insert.
    again = [j for j in found if j["url"] in known
             and (j.get("applicants") is not None or j.get("responsive") is not None
                  or (j.get("salary") or "").strip() or (j.get("pay_est") or "").strip())]
    if again:
        with db() as c:
            for j in again:
                c.execute(
                    "UPDATE jobs SET "
                    "applicants = COALESCE(:applicants, applicants), "
                    "responsive = COALESCE(:responsive, responsive), "
                    # a board that says nothing this time must not erase what it said last time
                    "salary  = CASE WHEN :salary  <> '' THEN :salary  ELSE salary  END, "
                    "pay_est = CASE WHEN :pay_est <> '' THEN :pay_est ELSE pay_est END "
                    "WHERE url = :url",
                    {"url": j["url"], "applicants": j.get("applicants"),
                     "responsive": j.get("responsive"),
                     "salary": j.get("salary") or "", "pay_est": j.get("pay_est") or ""})
    step("reading the ads", 0, max(1, len(new_urls)))
    # hydrate reports each page as it lands: this phase is a minute or more on a real search,
    # and a bar that does not move for a minute is the same as no bar at all
    read_report = {}
    fresh = await off(lambda: scrape.hydrate(
        new_urls, on_progress=lambda d, t: step("reading the ads", d, t),
        report=read_report))

    # An ad whose detail page did not answer is skipped inside hydrate, and was skipped in
    # silence: a board rate-limiting us for a minute could swallow twenty of thirty and the
    # search still reported success. Nothing is lost for ever - they are still unknown urls, so
    # the next run fetches them again - but "found 30, new 4" with no reason is not something
    # anyone can act on.
    # Only the ones whose page never answered. Everything else hydrate drops - a career fair,
    # an ad past its closing date, the same posting from two boards - is a correct drop and
    # would make this warning meaningless.
    if read_report.get("unread"):
        warnings.append(f"{read_report['unread']} of {len(new_urls)} ads could not be read this "
                        f"time - the board did not answer. Nothing is lost: they are still "
                        f"unseen, so the next search fetches them again.")

    # Now that each ad declares where it is, hold the boards to the city AND county that were asked
    # for. They do not hold themselves to either: measured on one pass, asking BestJobs for
    # Bucuresti returned Fagaras, Codlea and Timisoara, and freehire returned Skopje. Hipo ignores
    # a county name outright and answers with the whole country. Only the county was checked here,
    # so a city on its own did nothing at all.
    off_area = 0
    if city or county:
        keep = [j for j in fresh if scrape.job_in_area(j, city, county)]
        off_area, fresh = len(fresh) - len(keep), keep

    # Work mode reaches all four boards, not just the one that implements it. Measured, one pass
    # each: freehire honours it (2 of 20 remote on Any, 12 on Remote, 0 on On-site), BestJobs
    # returns the identical mix whatever is asked, and eJobs and Hipo never receive it - it is a
    # freehire API facet. So picking Remote filtered one source in four.
    #
    # hybrid is deliberately not enforced here: the remote pattern counts hybrid AS remote, so a
    # post-filter would answer a different question from the one that was asked.
    mode = (filters.get("work_mode") or "").strip().lower()
    off_mode = 0
    if mode in ("remote", "onsite"):
        want_remote = mode == "remote"
        keep = [j for j in fresh if scrape.remote_job(j) == want_remote]
        off_mode, fresh = len(fresh) - len(keep), keep

    # Seniority, for the same reason and in the same place. It is a freehire facet too, so picking
    # Junior filtered one source in four - which is exactly why the term suggestions used to carry
    # "junior", "debutant" and "fara experienta" as though they were job titles: searching the
    # words was the only way to reach entry-level ads on the other three boards.
    #
    # Mid is not enforced, the way hybrid is not: almost no advert says "mid-level", so the honest
    # answer is to leave that question alone rather than answer a different one. Measured on 353
    # stored ads, Junior drops 77 and every one of them reads as a manager or lead role.
    rank = (filters.get("seniority") or "").strip().lower()
    off_rank = 0
    if rank in ("intern", "junior", "senior", "lead"):
        keep = [j for j in fresh if scrape.seniority_fits(j, rank)]
        off_rank, fresh = len(fresh) - len(keep), keep

    # Adult-industry work, unless it was asked for. Videochat studios advertise constantly on these
    # boards and the title often gives nothing away - one of the four in this database is called
    # "Trainer/Teamleader" and only the body says "studio de videochat".
    #
    # Dropped before scoring, like the language gate, so they cost nothing rather than a model call
    # each. The pattern is deliberately narrow: "chat support" and "live chat" are an entirely
    # different job and must never be touched by this.
    off_adult = 0
    if not settings().get("allow_adult"):
        keep = [j for j in fresh if not scrape.adult_job(j)]
        off_adult, fresh = len(fresh) - len(keep), keep

    # The same posting listed on two boards. The dedupe before phase 2 compares title and company
    # too, but only within the batch in hand - across two searches the second board's url is simply
    # unknown, so the ad is read, scored and stored a second time. Measured on this database: 16
    # titles stored twice, 8 of them from different boards, and one pair where both copies were
    # still open - which auto-apply would have sent to the same employer twice.
    #
    # Here rather than at phase 2 because that is too early: discover() returns no company at all
    # for eJobs and Hipo, which is where these pairs come from, and the name only arrives with the
    # detail page. One query, and the key is the same one the batch dedupe uses.
    dupe = 0
    if fresh:
        with db() as c:
            stored = {f"{(r[0] or '').lower().strip()}|{(r[1] or '').lower().strip()[:18]}"
                      for r in c.execute("SELECT title, company FROM jobs "
                                         "WHERE COALESCE(title,'') <> '' "
                                         "AND COALESCE(company,'') <> ''")}
        keep = []
        for j in fresh:
            t, co = (j.get("title") or "").lower().strip(), (j.get("company") or "").lower().strip()
            if t and co and f"{t}|{co[:18]}" in stored:
                dupe += 1
                continue
            keep.append(j)
        fresh = keep

    for b in boards:
        rows = [j for j in fresh if j["source"] == b]
        complaint = scrape.health(b, rows, prior.get(b, 0)) if rows else ""
        if complaint:
            warnings.append(complaint)

    # Thirty days is the shelf life of an ad that does not say when it closes; one that does say is
    # believed. sweep_stale holds the rule, so the suite can put rows through the real thing.
    expired, expired_good = sweep_stale(settings().get("auto_min_fit", 75))

    with db() as c:
        for j in fresh:
            if j.get("lang") in ("", None, "en", "ro"):     # keep freehire's 'de', 'nl', ...
                j["lang"] = llm.ad_language(j)
            c.execute("INSERT INTO jobs(url,source,title,company,location,posted,"
                      "description,note,salary,expires,terms,lang,applicants,pay_est,"
                      "responsive) "
                      "VALUES(:url,:source,:title,"
                      ":company,:location,:posted,:description,:note,:salary,:expires,:terms,"
                      ":lang,:applicants,:pay_est,:responsive) "
                      # A row already here keeps everything a person has touched - its status,
                      # its score, the CV written for it, the date applied. What it does take
                      # is the facts that go stale: how many people have applied (12 on Monday
                      # is 300 by Friday, which is exactly when you want to be told), the pay if
                      # the board has started stating one, and the closing date. COALESCE, so a
                      # board that says nothing this time cannot erase what it said last time.
                      "ON CONFLICT(url) DO UPDATE SET "
                      "applicants = COALESCE(excluded.applicants, jobs.applicants), "
                      "responsive = COALESCE(excluded.responsive, jobs.responsive), "
                      "salary     = CASE WHEN excluded.salary   <> '' THEN excluded.salary   ELSE jobs.salary   END, "
                      "pay_est    = CASE WHEN excluded.pay_est  <> '' THEN excluded.pay_est  ELSE jobs.pay_est  END, "
                      "expires    = CASE WHEN excluded.expires  <> '' THEN excluded.expires  ELSE jobs.expires  END",
                      {"note": "", "lang": "", "salary": "", "expires": "", "terms": "",
                       "applicants": None, "pay_est": "", "responsive": None,
                       **{k: v for k, v in j.items() if not k.startswith("_")}})
        todo = [dict(r) for r in c.execute(
            "SELECT * FROM jobs WHERE fit IS NULL AND COALESCE(tries,0) < ? "
            # not the ones you have already dealt with. Marking a batch as already applied
            # imports rows with no score, and paying a model to rate a job you applied to
            # three weeks ago buys nothing - the card shows what you did, not a number.
            "AND status NOT IN ('applied','opened','skipped')", (SCORE_TRIES,))]
        # Scores from a model that is not the one in charge now go FIRST, before anything new.
        #
        # The chain falls through when a provider is out of quota or unwell, so a score can come
        # from whoever could answer - and the same advert measured 85 from one model and 35 from
        # another, which is either side of a 75 floor. Nothing is lost by that fallthrough as long
        # as it is temporary, and putting these at the front is what makes it temporary: the list
        # converges back to one scale on its own, without anybody noticing it had drifted.
        #
        # Only when there IS a model in charge to compare against, and only rows still waiting -
        # applied, opened and skipped keep whatever scored them, because their number is history.
        # Rows with no stamp at all are left alone: every score that predates this column has one,
        # and re-scoring nine hundred adverts to learn what they would say now is not a migration,
        # it is a bill. They stay on whatever scale they were on, and say nothing about it.
        #
        # `here` is the HEAD OF THE CHAIN, which is the only string that matches what score()
        # stamps. Measured on the real database when this was built from _entry() instead: 33 of 33
        # scored rows read as off-scale, because chain() builds the primary as
        # _entry(provider, cfg("LLM_MODEL")) - the Model box overrides the per-provider default for
        # the provider in charge - while _entry(provider) alone falls through to
        # LLM_MODEL_<PROVIDER> and then the built-in default. Nothing ever matched, so every search
        # re-scored the backlog and rewrote fit; the cap below is why that cost 25 rows and not 900.
        #
        # Not active(), which is chain() filtered by the breaker: while the primary rests that names
        # the fallback, so "the correct scale" would become whichever provider happened to be up and
        # every row the primary scored would queue for re-scoring. The scale is the model in charge.
        entry = (llm.chain() or [None])[0]
        stale_scale = []
        if entry:
            here = f"{entry[0]}/{entry[1]}"
            stale_scale = [dict(r) for r in c.execute(
                "SELECT * FROM jobs WHERE fit IS NOT NULL AND COALESCE(scored_by,'') <> '' "
                "AND scored_by <> ? AND COALESCE(tries,0) < ? "
                "AND status IN ('new','ready','vetoed') "
                # Capped, so a mistake here costs a batch and not a quota. Oldest first: a score
                # from a model that has since been replaced is the one most worth correcting.
                f"ORDER BY found ASC LIMIT {RESCALE_CAP}", (here, SCORE_TRIES))]
            todo = stale_scale + todo
        stuck = c.execute("SELECT COUNT(*) FROM jobs WHERE fit IS NULL "
                          "AND COALESCE(tries,0) >= ? "
                          "AND status NOT IN ('applied','opened','skipped')",
                          (SCORE_TRIES,)).fetchone()[0]

    # Re-run the gate over every row a search could surface, not just the unscored ones. It is
    # pure string matching, so it costs nothing - and without it, widening the language table or
    # correcting the gate leaves every previously judged row sitting at its old verdict for ever.
    with db() as c:
        judged = [dict(r) for r in c.execute(
            "SELECT * FROM jobs WHERE status IN ('new','ready','vetoed')")]
    # off(): pure string matching per row, but it runs over every row a search could surface -
    # 1.9 seconds at 761 rows, during which nothing else on the event loop moves. That is the
    # progress bar freezing and the dashboard not answering, on a table that only grows.
    todo, vetoed, freed = await off(_gate_pass, p, judged, todo)
    if freed:
        with db() as c:
            for j in freed:
                c.execute("UPDATE jobs SET fit=NULL, why=NULL, gaps=NULL, status='new' "
                          "WHERE url=? AND status='vetoed'", (j["url"],))
    with db() as c:
        for j, reason in vetoed:
            c.execute("UPDATE jobs SET fit=0, why=?, gaps='[]', status='vetoed' "
                      "WHERE url=? AND status IN ('new','vetoed')", (reason, j["url"]))

    # score in small chunks: the pool is shared with tailoring, applying and PDF rendering,
    # and a partial result is worth keeping if a later chunk fails
    scored = []
    # the language the model writes its reasons in. Read once here, not inside the worker: the
    # answers land on the card, and the app translates its own 631 sentences only to print the one
    # that matters most - why this job suits you - in English.
    want_lang = ui_lang()
    step("scoring", 0, len(todo))
    # Six at a time measured twice as fast on a 12-ad sample, but a 144-ad run outran mistral's
    # free tier: 15 calls came back "spent", the breaker parked the provider for 300s each time,
    # and the run averaged 4.8s an ad against the 1.1s measured on 38. No fixed number is right
    # for both sizes, so start wide and back off when the provider says to.
    width, i, failed = WORKERS, 0, 0
    while i < len(todo):
        chunk = todo[i:i + width]
        # count quota refusals across the batch, not exceptions: ask() recovers by moving down
        # the chain, so a job still gets scored and nothing is raised - but the provider did
        # refuse, and that is the thing worth slowing down for
        q0 = len(llm.QUOTA_EVENTS)

        async def one(job, _done=[0]):
            # progress per job, not per batch: when a provider backs off, its breaker parks it
            # for 300s and a batch can outlast the staleness rule that decides a search has
            # died. It had, twice, on a search that was working perfectly well.
            try:
                # a lambda so reply_in goes by keyword: off() forwards positionals only, and
                # a positional None for `send` makes every caller depend on the argument order
                return await off(lambda: llm.score(p, job, reply_in=want_lang))
            finally:
                _done[0] += 1
                step("scoring", len(scored) + _done[0], len(todo))

        got = await asyncio.gather(*(one(j) for j in chunk), return_exceptions=True)
        # Banked here, not at the end. A database error or the dashboard being closed mid-search
        # used to discard every score in the run; now the worst either costs is the batch in hand.
        # A write that fails leaves those rows with fit NULL and `tries` untouched, so the next
        # search picks them up again rather than giving up on them.
        try:
            failed += _store_scores(chunk, got, warnings)
        except Exception as e:
            print(f"[score] could not store a batch of {len(chunk)}: {type(e).__name__}: {e}")
            warnings.append(f"{len(chunk)} score(s) could not be saved "
                            f"({type(e).__name__}) - they will be scored again next search")
        scored += got
        i += len(chunk)
        spent = (len(llm.QUOTA_EVENTS) - q0) + sum(1 for g in got
                                                   if isinstance(g, llm.QuotaError))
        nxt = _next_width(width, spent, WORKERS)
        if nxt != width:
            # flushed: stdout is block-buffered when the weekly run redirects it to a file,
            # and a backoff line stuck in a buffer is a backoff nobody can diagnose
            print(f"[score] {width} -> {nxt} at a time"
                  + (f" ({spent} said spent)" if spent else " (provider is keeping up)"),
                  flush=True)
            width = nxt
        step("scoring", len(scored), len(todo))
    # (every batch was stored as it landed, inside the loop above)
    # only rows this search actually moved into 'vetoed': the gate now re-runs over every
    # stored row, so counting the whole list would report the standing total as if it had just
    # happened ("113 skipped on language" on a search that skipped none)
    _finish()
    newly_vetoed = sum(1 for j, _ in vetoed if j["status"] != "vetoed")
    if stuck:
        warnings.append(f"{stuck} ad(s) could not be scored after {SCORE_TRIES} attempts and "
                        f"are no longer retried. Settings has a button to put them back in the "
                        f"queue - worth pressing after changing the AI model, which is what most "
                        f"of them are stuck on.")
    return {"found": len(found), "new": len(fresh), "freed": len(freed), "expired": expired,
            # how many of those you would have applied to - the only part of `expired` that
            # anybody can do anything about
            "expired_good": expired_good, "scored": len(todo) - failed,
            # re-scored because a different model had produced their number, so the list is back on
            # one scale. Named, since a score changing under somebody is otherwise inexplicable.
            "rescaled": len(stale_scale),
            # ads never read or scored because they are in a job family you do not work in. Shown,
            # not silent: a filter you cannot see the effect of is a filter you cannot trust.
            "off_family": off_family,
            # dropped for being somewhere other than the city or county asked for. The boards
            # answer a city search with other cities, so without this the filter did nothing.
            "off_area": off_area,
            # dropped for being the wrong work mode, on the three boards that ignore the filter
            "off_mode": off_mode,
            # ...and for being the wrong seniority, on the same three
            "off_rank": off_rank,
            # the same posting already stored from another board, which would otherwise be read,
            # scored and applied to twice
            "off_dupe": dupe,
            # adult-industry work, unless the box under Settings says otherwise
            "off_adult": off_adult,
            # which rule dropped what. Named so a skip list that is quietly costing you a job you
            # would have wanted is visible, instead of being one number in a log line.
            "off_family_by": dict(sorted(dropped_by.items(), key=lambda kv: -kv[1])[:8]),
            "failed": failed, "vetoed": newly_vetoed, "queries": len(queries),
            "warnings": warnings}


def _url_of(body):
    """The url a request is about. Missing, null or not a string is a 400, not a KeyError 500."""
    url = (body or {}).get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(400, "url is required")
    return url


def _job(url):
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone()
    if not r:
        raise HTTPException(404, "unknown job")
    return dict(r)


LABELS = {
    "en": dict(profile="Profile", experience="Experience", projects="Projects",
               education="Education", skills="Skills", languages="Languages",
               certifications="Certifications", hobbies="Interests", present="present",
               year="year", years="years", month="month", months="months", and_="and",
               email="Email", phone="Tel", city="City"),
    "ro": dict(profile="Profil", experience="Experiență profesională", projects="Proiecte",
               education="Educație", skills="Competențe", languages="Limbi",
               certifications="Certificări", hobbies="Interese", present="prezent",
               year="an", years="ani", month="lună", months="luni", and_="și",
               email="Email", phone="Tel", city="Localitate"),
}


ONGOING = {"present", "prezent", "current", "now", "today", "curent", "in curs", "în curs",
           "ongoing", "la zi"}
MONTHS = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
          "ro": ["ian.", "feb.", "mar.", "apr.", "mai", "iun.",
                 "iul.", "aug.", "sept.", "oct.", "nov.", "dec."]}


def _month(v, lang):
    """2024-06 -> Jun 2024. Nobody writes a date as an ISO month on a CV, and the same page
    otherwise shows bare years for education - two granularities side by side."""
    v = str(v) if isinstance(v, (int, float)) else v      # models sometimes answer 2024, not "2024"
    # str(): cv.html already defends cv.links because a crash here wastes the tailor call that
    # has already been paid for, and a date is just as likely to arrive as a dict.
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(v or "").strip())
    if not m:
        return str(v or "").strip()
    year, mon = m.group(1), int(m.group(2))
    return f"{MONTHS[lang][mon - 1]} {year}" if 1 <= mon <= 12 else year


SCRUB = {"—": " - ", "–": "-", "‘": "'", "’": "'",
         "“": '"', "”": '"',
         # Romanian is written with a comma below: ș ț. The cedilla forms ş ţ are Turkish, and
         # models mix them in freely - measured, one model returned "suport clienţi", "Iaşi" and
         # "competenţele" in a single two-sentence answer, every word correct and every one of them
         # misspelled. A substitution, not a judgement, so it does not belong in a prompt.
         "ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"}
# Emphasis markers only count when they WRAP something, on one line. Removing them blindly
# turned __init__.py into init.py and 2**8 into 28 - on a technical CV, in the file that is sent
# to the employer.
# ** only. Underscores are how Python spells __init__.py, __name__ and 2**8, and a model that
# wants emphasis reaches for asterisks - so stripping __ costs real technical content and buys
# almost nothing. ("2**8" survives either way: emphasis needs a matching pair.)
PAIRED = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
TICKED = re.compile(r"`([^`\n]+)`")


def _tidy(v):
    """The prompt bans em-dashes and markdown; models still emit both. Strip them on the way to
    the PDF so the rule holds whatever model is answering - and so an ATS reading the text layer
    sees plain ASCII punctuation rather than typographic look-alikes."""
    if isinstance(v, str):
        for bad, good in SCRUB.items():
            v = v.replace(bad, good)
        v = TICKED.sub(r"\1", v)
        for _ in range(3):           # **bold with __nested__**; a few passes, never a while loop
            v, n = PAIRED.subn(r"\1", v)
            if not n:
                break
        return v.strip()
    if isinstance(v, list):
        return [_tidy(x) for x in v]
    if isinstance(v, dict):
        return {k: _tidy(x) for k, x in v.items()}
    return v


CV_DIR = HERE / "templates" / "cv"
THUMBS = OUT / ".thumbs"


# What each template is actually meant to carry. A photo makes European and Timeline; it sits
# oddly on a Harvard-style Traditional, where a plain header is the convention; Classic reads
# fine either way. Shown beside each download so the choice is made once, in the right place.
PHOTO_ADVICE = {"european": "yes", "timeline": "yes", "traditional": "no", "classic": "either"}
# What someone who has not chosen gets. The Europass-shaped one, because this app is used in
# Romania and that is the layout a recruiter here opens every day.
DEFAULT_CV = "european"


def cv_templates():
    """Template key -> {name, blurb}, read from the header comment of each templates/cv/*.css."""
    out = {}
    for f in sorted(CV_DIR.glob("*.css")):
        head = f.read_text(encoding="utf-8")[:400]
        m = re.search(r"/\*\s*(.+?)\s*[-–]\s*(.+?)\s*\*/", head, re.S)
        out[f.stem] = {"name": m.group(1).strip() if m else f.stem.title(),
                       "blurb": re.sub(r"\s+", " ", m.group(2)).strip() if m else "",
                       "photo": PHOTO_ADVICE.get(f.stem, "either")}
    return out


def _ym(value):
    """-> (year, month) from '2024-06', '2024-6' or '2024', else None."""
    m = re.match(r"\s*(\d{4})(?:[-/](\d{1,2}))?", str(value or ""))
    if not m:
        return None
    month = int(m.group(2) or 1)
    return (int(m.group(1)), month if 1 <= month <= 12 else 1)


def _cv_html(cv, lang, template, photo=None):
    def when(start, end):
        """Render a date range. An ASCII hyphen, because ATS parsers split on that and not on
        an en-dash, and nothing at all when the model dropped both ends."""
        a, b = _month(start, lang), _month(end, lang)
        if b and str(end).strip().lower() in ONGOING:
            b = LABELS[lang]["present"]
        return f"{a} - {b}" if a and b else (a or b or "")
    def howlong(start, end):
        """'1 year and 8 months'. Empty when a date is missing - a guess here is a lie on a CV."""
        a, b = _ym(start), _ym(end)
        if not a:
            return ""
        if not b:
            # Only an explicit "present" means today. A BLANK end date used to fall through to
            # here and print "2 years and 9 months" for a job that finished years ago, on a
            # document sent to an employer - while the dates beside it said only "Jan 2024".
            if str(end).strip().lower() not in ONGOING:
                return ""
            today = datetime.date.today()
            b = (today.year, today.month)
        # "0000" parses happily and printed "2026 years and 9 months". A working life fits here.
        if not (1900 <= a[0] <= datetime.date.today().year + 1):
            return ""
        months = (b[0] - a[0]) * 12 + (b[1] - a[1]) + 1        # a job worked in one month is 1
        if months < 1 or months > 80 * 12:
            return ""
        y, m = divmod(months, 12)
        L = LABELS[lang]
        bits = []
        if y:
            bits.append(f"{y} {L['year'] if y == 1 else L['years']}")
        if m:
            bits.append(f"{m} {L['month'] if m == 1 else L['months']}")
        return f" {L['and_']} ".join(bits)

    if template not in cv_templates():
        template = "classic"
    return tpl.get_template("cv.html").render(
        cv=cv, L=LABELS[lang], when=when, howlong=howlong, lang=lang,
        photo=photo_data_uri(photo),
        style=(CV_DIR / f"{template}.css").read_text(encoding="utf-8"))


# A fictional CV used only to draw the template thumbnails, so the picker shows what each style
# does to a real-looking page rather than a blank one.
SAMPLE_CV = {
    "name": "Ana Popescu", "title": "Customer Support Team Lead",
    "email": "ana.popescu@example.com", "phone": "+40 7xx xxx xxx", "location": "Cluj-Napoca",
    "links": ["linkedin.com/in/anapopescu"],
    "summary": "Team lead with six years in customer support, from frontline agent to running a "
               "team of twelve. Known for calm escalations and clear coaching.",
    "experience": [
        {"role": "Team Lead, Customer Support", "company": "Nordic Telecom", "location": "Cluj-Napoca",
         "start": "2023-03", "end": "present",
         "bullets": ["Led a team of twelve agents across chat and phone channels.",
                     "Cut average handling time by 18% through a revised escalation path.",
                     "Coached four agents into senior roles."]},
        {"role": "Senior Support Agent", "company": "Nordic Telecom", "location": "Cluj-Napoca",
         "start": "2020-06", "end": "2023-02",
         "bullets": ["Handled tier-two escalations for business customers.",
                     "Wrote the onboarding guide still used for new hires."]},
    ],
    "education": [{"degree": "BA, Communication", "school": "Babes-Bolyai University",
                   "start": "2016", "end": "2019"}],
    "skills": ["Zendesk", "Salesforce", "Coaching", "Escalation handling", "Quality assurance",
               "Workforce planning"],
    "languages": [{"name": "Romanian", "level": "native"}, {"name": "English", "level": "C1"}],
    "certifications": ["ITIL Foundation"], "projects": [], "hobbies": [],
}


@app.get("/api/cv/templates")
def list_cv_templates():
    return cv_templates()


@app.get("/api/cv/thumb/{key}.png")
async def cv_thumb(key: str):
    """A rendered first page of the sample CV in this template, cached after the first request.
    Four Chromium renders once, then a static file."""
    if key not in cv_templates():
        raise HTTPException(404, "no such template")
    THUMBS.mkdir(exist_ok=True)
    png = THUMBS / f"{key}.png"
    if not png.exists() or png.stat().st_mtime < (CV_DIR / f"{key}.css").stat().st_mtime:
        def render():
            from playwright.sync_api import sync_playwright
            html = _cv_html(_tidy(dict(SAMPLE_CV)), "en", key)
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                # A4 at 96dpi is 794x1123; keep the page's own margins so the thumbnail is the
                # printed page, not the unmargined html
                pg = b.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=0.5)
                pg.set_content(html.replace("<body>", '<body style="padding:14mm">', 1), wait_until="load")
                pg.screenshot(path=str(png), full_page=False)
                b.close()
        await off(render)
    return FileResponse(png, media_type="image/png")


def _pdf(cv, path, lang="en", template="classic", photo=None):
    """Render the CV html to PDF with Chromium - Playwright is already a dependency, so no PDF lib."""
    from playwright.sync_api import sync_playwright
    cv = _tidy(cv)

    html = _cv_html(cv, lang, template, photo)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content(html, wait_until="load")
        pg.pdf(path=str(path), format="A4", print_background=True,
               margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"})
        b.close()


@app.post("/api/tailor")
async def tailor(body: dict = Body(...)):
    j = _job(_url_of(body))
    lang = body.get("lang", "auto")
    if lang not in ("auto", "en", "ro"):
        raise HTTPException(400, "lang must be auto, en or ro")
    if lang == "auto":
        lang = llm.ad_language(j)
    template = body.get("template") or settings()["cv_template"] or DEFAULT_CV
    if template not in cv_templates():
        raise HTTPException(400, f"no such CV template: {template}")
    cv = await off(llm.tailor, profile(), j, lang)
    slug = "".join(ch if ch.isalnum() else "-" for ch in f"{j['company']}-{j['title']}")[:56].strip("-")
    # the url hash keeps two jobs with the same long prefix from overwriting each other's CV
    tag = hashlib.sha1(j["url"].encode()).hexdigest()[:6]
    # The template belongs in the name. Without it, tailoring the same job as Classic and then
    # as European wrote to one path and served one url - and the browser, quite reasonably,
    # handed back the copy it already had. Two templates, one CV, and it looked like the app
    # had ignored the choice.
    path = OUT / f"{slug or 'cv'}-{tag}-{lang}-{template}.pdf"
    want = body.get("photo")
    want = None if want is None else bool(want)
    await off(lambda: _pdf(cv, path, lang, template, want))
    with db() as c:
        # a vetoed row you chose to tailor anyway is one you decided to pursue, so promote it
        # like any other - leaving it 'vetoed' hid it and put it on Clear's deletion list
        c.execute("UPDATE jobs SET cv=?, status=CASE WHEN status IN ('new','vetoed') THEN 'ready' ELSE status END "
                  "WHERE url=?", (path.name, j["url"]))
    return {"cv": path.name, "lang": lang, "template": template, "preview": cv}


# How many times an ad may fail to score before it stops being retried. Failures that are the
# provider's fault (out of credits) are not counted, so this only ever runs out on an ad that
# genuinely cannot be scored - and without it, every search paid for that ad again.
SCORE_TRIES = 3

# What the card says about a posting whose apply button leaves the board. Written once it has
# been discovered, and read by the weekly run so the discovery is not repeated every week.
EXTERNAL_NOTE = "apply on the employer site"

# The hard ceiling on one run, whatever you type in the box. A guard against a typo, not a
# policy: the score floor is what actually decides how many go out. Measured on a real list -
# at floor 85 there are 7 applyable jobs waiting, at 75 there are 17, at 70 there are 19 - so
# the floor bites long before this does.
#
# Fifty rather than more: the weekly task is allowed two hours, a search takes about six minutes
# and an application 15-21 seconds, so fifty is twenty minutes of applying and nowhere near the
# limit. What makes a big number dangerous is not the time it takes - it is that an unattended
# run sending fifty applications with an out-of-date board CV is fifty employers who saw it.
BATCH_CAP = 50


def _mark_closed(c, url):
    """The board has taken this posting down. Keep the row - the person may have read it - but
    stop offering it, and say why rather than leaving it looking like an ordinary skip."""
    c.execute("UPDATE jobs SET status='skipped', note='closed on the board' "
              "WHERE url=? AND status != 'applied'", (url,))


@app.post("/api/apply_batch")
async def apply_batch(body: dict = Body(...)):
    """Apply to the jobs you ticked, one after another.

    Capped and sequential on purpose. The batch saves the waiting, not the deciding - every url
    here is one you ticked on its own card, after reading its ad. There is no "apply to everything matching": a bad
    CV or a wrong salary reaching ten employers you chose is recoverable, reaching seventy you
    never looked at is not. The run stops early if the board drops the session, since every
    application after that would fail the same way.
    """
    urls = [u for u in dict.fromkeys(body.get("urls") or []) if u][:BATCH_CAP]
    if not urls:
        raise HTTPException(400, "nothing selected")
    p, results, unconfirmed = profile(), [], []
    for url in urls:
        try:
            j = _job(url)
        except HTTPException:
            # The expiry sweep deletes rows on every search, so a url can disappear between the
            # page's last refresh and this click. Raising here threw away the whole run's
            # results - including applications that had already been SENT to real employers,
            # which the browser was then told nothing about.
            results.append({"url": url, "title": url,
                            "error": "no longer in your list - it was cleared or deleted"})
            continue
        # Read again, now, not from the list the page was holding. The urls were chosen from a
        # page that may be minutes old, and the scheduled run applies from the same table without
        # telling the browser - so a job it sent at 09:00 was still ticked here and would be sent
        # a second time. Nothing local stopped that: the only thing that ever caught it was the
        # board itself answering "already applied", which is a race, not a guard.
        if j.get("status") == "applied":
            results.append({"url": url, "title": j["title"], "already": True,
                            "error": "already applied - sent before this batch started"})
            continue
        try:
            board = j["source"] if prefill.apply_mode(j["source"]) == "auto" else ""
            # `source` authorises the send; the url decides where the browser goes. A row stored as
            # ejobs with a hipo.ro url passed this gate and then ran a different board's flow against
            # it - each board has its own form, so the wrong one silently fills nothing.
            if board and prefill.board_of(j["url"]) != board:
                results.append({"url": url, "title": j["title"],
                                "error": f"this row says {board} but its link is not a {board} "
                                         f"link - not applying"})
                continue
            if not board:
                results.append({"url": url, "title": j["title"],
                                "error": ("apply to this one by hand"
                                          if prefill.apply_mode(j["source"]) == "manual"
                                          else "not a board job")})
                continue
            if not prefill.session_for(board):
                results.append({"url": url, "title": j["title"],
                                "error": f"not signed in to {board}"})
                break
            res = await off(lambda u=url, t=j["title"]: prefill.board_apply(
                u, headless=True, profile=p, job_title=t,
                # default False: a caller that forgets the flag must not thereby submit an
                # employer's screening questions. The dashboard passes True explicitly.
                # The dashboard's batch button does NOT pass this, deliberately: a job with
                # screening questions is handed back and opened for you, because twenty sets of
                # answers nobody read is not something to send on one click. The single Apply
                # button, which asks about that one job by name, does submit them.
                auto_send=body.get("auto_send", False)))
            if res.get("submitted") or res.get("already"):
                with db() as c:
                    _mark_applied(c, url)
            elif res.get("closed"):
                with db() as c:
                    _mark_closed(c, url)
            elif res.get("external"):
                # live, just not one-clickable from here - say so on the card instead of hiding it
                with db() as c:
                    c.execute("UPDATE jobs SET note = CASE WHEN COALESCE(note,'') = '' "
                              "THEN ? ELSE note || ' \u00b7 ' || ? END "
                              "WHERE url=? AND status != 'applied' "
                              "AND COALESCE(note,'') NOT LIKE ?",
                              (EXTERNAL_NOTE, EXTERNAL_NOTE, url, f"%{EXTERNAL_NOTE}%"))
            elif res.get("needs_you"):
                # Screening questions: normally open it for the person, and take it out of the next
                # batch either way. hand_off=False is the scheduled run, where opening a window at
                # 09:00 on a Sunday just leaves Chromium sitting on an empty desk.
                #
                # Ahead of clicked, because the "sent the mini interviu but saw no confirmation"
                # path sets both. Tested the other way round, that job was filed as pressed-and-
                # forgotten and never opened for anyone - while the run's own report went on saying
                # "needs you: screening questions" about it.
                if body.get("hand_off", True):
                    prefill.spawn_board(url, j["title"])
                _handed_over(url)
            elif res.get("clicked"):
                # Pressed, not confirmed. Recorded as done-for-now rather than left untouched:
                # leaving it 'new' put it straight back into next week's list and applied twice.
                # Resolved properly below, by asking the board - this is only the fallback for
                # when even the board cannot say.
                unconfirmed.append((url, j["title"], board))
                with db() as c:
                    c.execute("UPDATE jobs SET status=CASE WHEN status IN ('new','ready') "
                              "THEN 'opened' ELSE status END, "
                              "note='pressed apply, no confirmation seen - check the board' "
                              "WHERE url=?", (url,))
            results.append({"url": url, "title": j["title"], "submitted": res.get("submitted"),
                            "already": res.get("already"), "needs_you": res.get("needs_you"),
                            "error": res.get("error")})
            if res.get("error") and "not signed in" in (res["error"] or ""):
                break
        except Exception as e:
            # Whatever broke, the applications already sent in this batch are facts and the
            # caller has to hear about them. Playwright crashing on job 7 of 10 used to
            # discard the results for 1-6 and answer 500 - while those six were in real
            # inboxes and their rows already said applied. The loop stops here, because
            # whatever just failed will most likely fail on the next one too, and what has
            # been collected is returned below.
            print(f"[apply] {j['title']}: {type(e).__name__}: {e}")
            results.append({"url": url, "title": j["title"],
                            "error": f"stopped here ({type(e).__name__}) - anything above "
                                     f"this line was still sent"})
            break
    # Ask the board whether the ones it would not confirm actually landed.
    #
    # eJobs frequently presses through and then shows nothing - its own redirect hangs - so the
    # application was filed as "pressed apply, no confirmation seen" and left for a person to check
    # by hand. That is a real application nobody can account for, and it happened to four jobs in
    # one day here. The board knows: all three publish the list of what you have applied to, which
    # is what refresh_board_states already reads.
    #
    # So instead of trusting silence - which would record applications that may not exist - this
    # goes and looks. One read of the list per board, however many were unconfirmed, and matched on
    # the board's own posting id because an advert has more than one url: eJobs stores a /user/
    # prefix its application list does not use.
    if unconfirmed:
        for board in {b for _, _, b in unconfirmed if b in prefill.APPLICATIONS}:
            mine = [(u, t) for u, t, b in unconfirmed if b == board]
            try:
                listed = await off(lambda bb=board: prefill.board_applications(bb))
            except Exception as e:
                print(f"[apply] could not read {board}'s application list: {type(e).__name__}: {e}")
                continue
            ids = {prefill.posting_id(a.get("url") or "") for a in listed}
            ids.discard("")
            for u, title in mine:
                if prefill.posting_id(u) not in ids:
                    continue                     # the board does not list it: genuinely not sent
                with db() as c:
                    _mark_applied(c, u)
                    c.execute("UPDATE jobs SET note='' WHERE url=?", (u,))
                for r in results:
                    if r["url"] == u:
                        r.update(submitted=True, error=None, confirmed_by_board=True)
                print(f"[apply] {board} lists {title[:50]!r} as applied - recorded")

    return {"results": results,
            "sent": sum(1 for r in results if r.get("submitted")),
            "skipped": sum(1 for r in results if r.get("already")),
            "needs_you": sum(1 for r in results if r.get("needs_you")),
            # a needs_you or already result carries an error string too, and counting it
            # here as well made sent+skipped+needs_you+failed exceed the number of jobs
            "failed": sum(1 for r in results if r.get("error")
                          and not (r.get("submitted") or r.get("already")
                                   or r.get("needs_you")))}


@app.get("/api/cv/{name}")
def get_cv(name: str):
    f = OUT / pathlib.Path(name).name
    # is_file, not exists: "...." and "%2e" resolve to a directory and handing that to
    # FileResponse is a 500 rather than an honest 404
    if not f.is_file():
        raise HTTPException(404, "no such CV")
    # Re-tailoring the same job writes the same file name, so a cached copy would keep being
    # handed back after the CV had been rewritten.
    return FileResponse(f, media_type="application/pdf",
                        headers={"Cache-Control": "no-store, must-revalidate"})


# only boards the app actually submits on need a stored session
SIGNIN = {"ejobs": "https://accounts.ejobs.ro/login",
          "bestjobs": "https://www.bestjobs.eu/ro/login",
          # Hipo stays manual until a sign-in made here is still accepted afterwards. The button
          # is back so that can be tested: every context now shares one browser identity, which
          # is the leading explanation for why its sessions used to die.
          "hipo": "https://www.hipo.ro/locuri-de-munca/logincontcandidat"}


@app.get("/api/signin/saved")
def saved_signins():
    """Which boards have a saved sign-in, and whether it is still being used.

    Never the username and obviously never the password: there is no endpoint anywhere that
    returns either, so nothing on the page can leak one.
    """
    return {"boards": creds.status(), "supported": sorted(prefill.LOGIN_FORM)}


@app.post("/api/signin/saved")
def save_signin(body: dict = Body(...)):
    """Save a board sign-in, encrypted to this Windows account."""
    board = (body or {}).get("board")
    if board not in prefill.LOGIN_FORM:
        raise HTTPException(400, f"not a board this app can sign in to: {board}")
    try:
        creds.save(board, body.get("username") or "", body.get("password") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(400, str(e))
    # deliberately no echo of what was stored
    return {"ok": True, "boards": creds.status()}


@app.post("/api/signin/now")
async def signin_now(body: dict = Body(...)):
    """Use a just-saved sign-in straight away, if that board has signed the person out.

    The moment somebody types their password and presses Save is the moment the app both knows the
    credentials and knows the board is not letting it in - and it used to sit on both until the next
    scheduled run, hours away.

    Through auto_apply.sign_back_in, which the keep-alive and the applying step also use: one
    attempt and never a loop, because an unattended retry posting a wrong password is how an account
    gets locked. Already signed in is not an error, it is nothing to do.
    """
    board = (body or {}).get("board")
    if board not in prefill.LOGIN_FORM:
        raise HTTPException(400, f"not a board this app can sign in to: {board}")
    if not creds.status().get(board):
        raise HTTPException(400, "no saved sign-in for that board")

    def work():
        # a LIVE look, not the cached file: the whole point is that this runs the moment somebody
        # hands over a password because a board is refusing them, and a stale "signed in" would
        # make it do nothing at all
        try:
            live = prefill.verify_boards([board]).get(board, prefill.board_status().get(board))
        except Exception:
            live = prefill.board_status().get(board)
        if live:
            return {"already": True, "signed_in": True}
        said = []
        import auto_apply                  # imported here: app.py has no module-level use for it
        back = auto_apply.sign_back_in(prefill, [board], said.append)
        return {"already": False, "signed_in": board in back,
                "note": " ".join(said)[:300]}

    out = await off(work)
    # whatever happened, hand back what the panel needs so it can redraw without a page load
    out["boards"] = prefill.board_status()
    return out


@app.delete("/api/signin/saved")
def forget_signin(board: str = ""):
    creds.forget(board)
    return {"ok": True, "boards": creds.status()}


@app.get("/api/boards")
def boards():
    """Which sources the app can apply on, and which you apply to by hand."""
    return {"auto": list(prefill.AUTO_APPLY), "manual": list(prefill.MANUAL_APPLY),
            "profiles": {b: ui["profile"] for b, ui in prefill.BOARD_UI.items()}}


# What a board holds versus what this app holds. Read-only by design - see prefill.board_profile.
def _roles_of(sections):
    """Role lines out of a board's rendered experience section. A role line is short, has no
    date in it, and is followed by something; everything else there is prose."""
    lines = []
    for head, body in (sections or {}).items():
        if not str(head).lower().startswith(("experien", "ce stiu", "ce \u0219tiu")):
            continue
        lines += [l for l in body if 2 < len(l) < 70]
    drop = re.compile(r"\d{4}|prezent|ani |luni|vezi mai mult|recomandare|^\W+$", re.I)
    return [l for l in lines if not drop.search(l)]


@app.get("/api/boards/{board}/profile")
async def board_profile(board: str):
    """Show what this board currently holds about you, beside what this app holds.

    Nothing is written to the board, now or ever: this opens the page, reads it and closes.
    Changing a board profile is done by the person, on the board, which is the only way a
    half-finished write cannot leave it neither theirs nor ours.
    """
    if board not in prefill.PROFILE_PAGE:
        raise HTTPException(400, f"No profile page is known for {board}.")
    if not prefill.session_for(board):
        raise HTTPException(400, f"Not signed in to {board}. Sign in from the dashboard first.")
    try:
        got = await off(lambda: prefill.board_profile(board))
    except Exception as e:
        raise HTTPException(400, f"Could not read your {board} profile: {e}")
    me = profile()
    mine = [f"{e.get('role','')} - {e.get('company','')}".strip(" -")
            for e in (me.get("experience") or []) if e.get("role")]
    theirs = _roles_of(got.get("sections"))
    fold = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    missing = [r for r in mine
               if not any(fold(r.split(" - ")[0]) and fold(r.split(" - ")[0]) in fold(t)
                          for t in theirs)]
    return {"board": board, "url": got.get("url"),
            "board_sections": {k: v[:12] for k, v in (got.get("sections") or {}).items()},
            "board_fields": got.get("fields") or {},
            "app_roles": mine, "board_roles": theirs[:20],
            "roles_missing_on_board": missing,
            "app_summary": (me.get("summary") or "")[:400]}


@app.get("/api/signin")
def signin_status():
    """Last known sign-in state per board (cheap - reads the cached verification).

    `stale` is the important part: the cached answer has no expiry of its own, so without it the
    page happily showed "signed in" for a session that had died the day before.
    """
    ago = prefill.board_checked_ago()
    return {"saved": prefill.STATE.exists(), "boards": prefill.board_status(),
            "checked_ago": ago,
            # Has a live check ever actually run? Without one, board_status() is a cookie-NAME
            # guess, and that guess has been wrong for both boards before - which is the whole
            # reason verify_boards exists. The page needs to tell a guess from an answer, or it
            # prints "You are signed out" in red over a session with six months left on it.
            "verified": ago is not None,
            "stale": ago is None or ago > prefill.BOARD_CHECK_STALE}


@app.post("/api/signin/check")
async def signin_check():
    """Actually load each board and look. Slower, so it runs when you come back from signing
    in rather than on every dashboard load.

    Returns the MERGED state, not the raw probe. verify_boards deliberately leaves out a board it
    could not reach so that the file keeps that board's last verified answer; handing the partial
    dict to the page threw that away again, because a missing key is falsy there. It is read
    straight after a sign-in to choose the message, so a probe that timed out announced "Still not
    signed in to Hipo" to somebody who had just signed in to Hipo.
    """
    probed = await off(prefill.verify_boards)
    return {"ok": True, "boards": prefill.board_status(),
            # named rather than hidden: these kept their previous answer instead of being checked
            "unchecked": sorted(b for b in prefill.BOARD_UI if b not in probed)}


@app.post("/api/signin")
def signin(body: dict = Body(...)):
    """Open a board's login page in the app's browser. You type the credentials there - the app
    never sees them - and the session is saved for later runs."""
    url = SIGNIN.get(body.get("board") or "")
    if not url:
        raise HTTPException(400, f"unknown board {body.get('board')!r}")
    prefill.signin(url)
    return {"ok": True, "url": url}


@app.post("/api/apply")
async def apply(body: dict = Body(...)):
    """Open the application. On a known ATS we drive a real browser, fill the fields the profile
    already answers and attach the CV; on anything else we just open the ad and the PDF.

    Either way it stops before the submit button. You read what was filled, answer the questions
    only you can answer, and send it yourself - an unattended submitter that quietly gets a field
    wrong does it to every employer at once, and none of it can be taken back."""
    j = _job(_url_of(body))
    host = prefill.ats_host(j["url"])
    cv = (OUT / j["cv"]) if j["cv"] else None

    if prefill.apply_mode(j["source"]) == "manual" and body.get("submit"):
        raise HTTPException(400, f"{j['source']} has to be applied to by hand - "
                                 f"use Open to apply, which signs you in as yourself.")
    board = j["source"] if prefill.apply_mode(j["source"]) == "auto" else ""
    if board and body.get("submit"):
        # The board's own one-click apply. This SENDS it - there is no form and no review step
        # afterwards - so it only runs when `submit` is set by a click on this one job.
        if not prefill.session_for(board):
            raise HTTPException(400, f"Not signed in to {board}. Use the sign-in button first.")
        res = await off(lambda: prefill.board_apply(
            j["url"], headless=True, profile=profile(), job_title=j["title"],
            auto_send=body.get("auto_send", True)))
        if res["error"]:
            print("[apply]", j["title"], "->", res)      # full detail lands in srv.log
            if res.get("closed"):
                # take it off the list on the way out, so the next click is not the same dead end
                with db() as c:
                    _mark_closed(c, j["url"])
            raise HTTPException(400, res["error"])
        if res["needs_you"]:
            # the employer added screening questions, and answering them IS the application.
            # Reopen visibly with what the profile answers filled in, and leave the rest - and
            # the send button - to you.
            prefill.spawn_board(j["url"], j["title"])
            _handed_over(j["url"])
            return {"ok": True, "board": board, "needs_you": True,
                    "questions": res["questions"]}
        with db() as c:
            _mark_applied(c, j["url"])
        return {"ok": True, "board": board, "submitted": res["submitted"],
                "already": res["already"]}

    report = None
    if host and body.get("headless"):
        # nothing to look at, so run it here and hand back what it filled
        report = await off(lambda: prefill.run(j["url"], cv, headless=True,
                                               job_title=j["title"], profile=profile()))
    elif host:
        prefill.spawn(j["url"], cv, headless=False, job_title=j["title"])
    else:
        # eJobs and Hipo require a signed-in account and refuse an automated browser, so hand off
        # to the one you already use: your default browser has the real session. Nothing to
        # prefill there anyway - both send the CV stored on your board profile, not a per-job
        # upload - so the app opens the ad and the tailored PDF beside it.
        webbrowser.open(j["url"])
        if cv:
            webbrowser.open(cv.as_uri())
    with db() as c:
        # only a job not yet applied to moves to 'opened' - re-checking a prefill must not
        # demote something already sent
        c.execute("UPDATE jobs SET status=CASE WHEN status IN ('new','ready') THEN 'opened' "
                  "ELSE status END WHERE url=?", (j["url"],))
    return {"ok": True, "ats": host, "cv": j["cv"], "report": report}


def one_job(c, url):
    """The list-shaped row for a single job, so the page can update one card instead of
    re-downloading every ad it already has."""
    r = c.execute(f"SELECT {LIST_COLS} FROM jobs WHERE url=?", (url,)).fetchone()
    return dict(r) if r else None


@app.post("/api/status")
def set_status(body: dict = Body(...)):
    url = _url_of(body)
    status = body.get("status")
    # "vetoed" is here for undo only - Mark applied on a row the language gate vetoed, then
    # Undo, has to put it back where it was, and it used to answer "not a status: vetoed".
    # Vetoed rows are precisely the ones you overrule by hand, so this was not a corner.
    if status not in ("new", "ready", "opened", "applied", "skipped", "vetoed"):
        raise HTTPException(400, f"not a status: {status}")
    with db() as c:
        if status == "applied":
            _mark_applied(c, url)
        elif body.get("undo"):
            # Mark applied sits one click from Skip, so a slip needs a way back - but only for
            # a couple of minutes. After that the row is history and stays as it is.
            n = c.execute("UPDATE jobs SET status=?, applied_at=NULL WHERE url=? AND status='applied' "
                          "AND applied_at >= datetime('now','localtime','-2 minutes')",
                          (status, url)).rowcount
            if not n:
                raise HTTPException(400, "Too late to undo - applied jobs stay in the history.")
        else:
            # applied rows are the record of what you sent, and that record is not editable
            n = c.execute("UPDATE jobs SET status=? WHERE url=? AND status != 'applied'",
                          (status, url)).rowcount
            if not n and c.execute("SELECT 1 FROM jobs WHERE url=? AND status='applied'",
                                   (url,)).fetchone():
                raise HTTPException(400, "Applied jobs stay in the history and cannot be changed.")
        job = one_job(c, url)
    return {"ok": True, "job": job}


@app.post("/api/clear")
def clear(body: dict = Body(...)):
    """Empty the board of results you never acted on, so the next search starts from a clean list.

    Searching for something new appends to what is already stored, which is right until the day
    you switch from "customer support" to "front end developer" and the old 200 rows bury the new
    ones. Only untouched rows go: anything applied, opened, tailored or deliberately skipped is
    the record of your work (and skipped rows are what stop a job you rejected coming straight
    back on the next search), so it stays.
    """
    keep = ("applied", "opened", "ready", "skipped")
    asked = body.get("status") or ("new", "vetoed")
    # A string here used to be iterated letter by letter - tuple("applied") is ('a','p',...) -
    # so the request looked like it worked and deleted nothing.
    if isinstance(asked, str) or not isinstance(asked, (list, tuple)):
        raise HTTPException(400, "status must be a list of statuses")
    drop = tuple(asked)
    # An assert, not an exception, is stripped by python -O: in that configuration this guard
    # simply was not there, and the rows a person had acted on were deletable.
    if set(drop) & set(keep):
        raise HTTPException(400, "Refusing to delete rows you have acted on.")
    if not set(drop) <= {"new", "vetoed"}:
        raise HTTPException(400, "Only new or vetoed rows can be cleared.")
    q = ",".join("?" * len(drop))
    with db() as c:
        # A tailored CV is work you paid for, and a vetoed row can hold one - you can tailor a
        # job before the gate re-vetoes it. Status is not the whole story, so spare anything
        # with a CV attached, whatever its status says.
        n = c.execute(f"DELETE FROM jobs WHERE status IN ({q}) "
                      f"AND (cv IS NULL OR cv = '')", drop).rowcount
    return {"ok": True, "deleted": n}


@app.post("/api/rescore")
def rescore(body: dict = Body(...)):
    """Put jobs back in the queue to be scored again.

    A language veto is a guess made from the ad's wording, and it sticks: the row is left at
    fit=0 and never re-examined. Adding a language to your profile, or spotting a bad veto,
    needs a way back - otherwise those rows are unreachable except by deleting them, and the
    next search just re-inserts and re-vetoes them.
    """
    where = body.get("status") or "vetoed"
    # Only the two verdicts this app makes on its own behalf can be taken back. Anything else -
    # and 'applied' above all - is the record of what a person actually did: resetting it to
    # 'new' erased that record AND offered the job up to be applied to a second time, at an
    # employer who had already had one.
    if where == "stuck":
        # Ads that failed to score SCORE_TRIES times. They are left at status 'new' with fit NULL,
        # so the two branches below cannot see them and nothing else resets the counter - the
        # warning told you they were "no longer retried" and left it there. Usually they are stuck
        # on something that has since changed: a model too small for the format, a provider that
        # was refusing, an ad that was half-loaded when it was read.
        with db() as c:
            n = c.execute("UPDATE jobs SET tries=0 WHERE fit IS NULL "
                          "AND COALESCE(tries,0) >= ? "
                          "AND status NOT IN ('applied','opened','skipped')",
                          (SCORE_TRIES,)).rowcount
        return {"ok": True, "queued": n}
    if where not in ("vetoed", "skipped"):
        raise HTTPException(400, "Only vetoed, skipped or stuck jobs can be queued again. "
                                 "Applied jobs are the record of what you sent.")
    with db() as c:
        # tries=0 as well. Without it this was only half a way back: the scoring queue takes rows
        # with `tries` under SCORE_TRIES, so a row that had already failed three times came back as
        # 'new' with its counter still spent and was skipped by every search afterwards - cleared
        # of its verdict, queued in name only, and unreachable except by deleting it. Nothing
        # anywhere else ever set this back to zero.
        n = c.execute("UPDATE jobs SET fit=NULL, why=NULL, gaps=NULL, status='new', tries=0 "
                      "WHERE status=?", (where,)).rowcount
    return {"ok": True, "queued": n}


@app.post("/api/delete")
def delete(body: dict = Body(...)):
    url = _url_of(body)
    with db() as c:
        row = c.execute("SELECT cv, status FROM jobs WHERE url=?", (url,)).fetchone()
        if row and row["status"] == "applied":
            raise HTTPException(400, "Applied jobs stay in the history and cannot be deleted.")
        c.execute("DELETE FROM jobs WHERE url=?", (url,))
    # the PDF outlives the row otherwise: out/ collects files nothing references any more
    name = (row["cv"] if row else "") or ""
    if name:
        (OUT / pathlib.Path(name).name).unlink(missing_ok=True)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    import socket, threading
    port = 8777
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            print(f"The app is already running. Opening http://127.0.0.1:{port}")
            webbrowser.open(f"http://127.0.0.1:{port}")
            sys.exit(0)
    with db():                 # create the schema before anything can ask for a row
        pass
    # open the dashboard from here, once the server is about to listen - run.bat used to launch
    # the browser first, so the very first thing a new user saw was "connection refused"
    if os.environ.get("JOB_OPEN"):        # set by run.bat; a developer restart should not
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8777")).start()
    # On a thread: it is two PowerShell calls and it matters once, so it must not sit between
    # the user double-clicking run.bat and the page loading.
    threading.Thread(target=retire_old_tasks, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8777, log_level="warning")
