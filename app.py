"""jobhunter - a local job-hunting assistant. Run: run.bat  ->  http://127.0.0.1:8777"""
import asyncio
import collections, hashlib, io, json, os, pathlib, re, sqlite3, subprocess, sys, time, webbrowser
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Body, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import llm, prefill, scrape

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
# Measured against the live chain, not guessed: 12 real ads scored in 26.1s three at a
# time and 13.1s six at a time, with no 429 and the breaker untripped. Browser work is
# dispatched one at a time by apply_batch, so this never means six Chromiums.
WORKERS = 6
pool = ThreadPoolExecutor(max_workers=WORKERS)


_SCHEMA_DONE = False


def db():
    global _SCHEMA_DONE
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")   # the weekly run may be writing at the same time
    if _SCHEMA_DONE:
        return c
    # Set the schema up once per process, not once per connection. ALTER TABLE needs a write
    # lock, so doing this on every connection made every read - opening the dashboard, polling
    # the progress bar - queue behind whatever the search was writing, for up to the full
    # busy_timeout. That is what "it feels stuck, it needs a lot of refreshes" was.
    c.execute("PRAGMA journal_mode=WAL")     # and with WAL, a reader never waits for the writer
    c.execute("""CREATE TABLE IF NOT EXISTS jobs(
        url TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT,
        posted TEXT, description TEXT, fit INTEGER, why TEXT, gaps TEXT,
        status TEXT DEFAULT 'new', cv TEXT, found TEXT DEFAULT (datetime('now')))""")
    for col in ("note TEXT", "lang TEXT", "applied_at TEXT", "untapped TEXT",
                "salary TEXT"):                                                 # added later
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
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


# ---------- settings ----------
SETTINGS = HERE / "settings.json"
# what the dashboard remembers between visits. Secrets stay in .env; these are preferences,
# and they travel with a folder copy while .env deliberately does not.
DEFAULTS = {"lang": "auto", "headless": "", "cv_template": "", "cv_ask": True,
            # The county you could actually take a job in. Not derived from the profile address:
            # "Saravale" is a village and no town list will place it, and guessing wrong here
            # would quietly mislabel every result. Blank means "do not judge distance".
            "home_county": "",
            # What the search bar had last time. It lived in the browser's localStorage, so it
            # never moved with the profile to another machine, and the county dropdown was not
            # saved at all - it reset on every reload.
            "search_query": "", "search_location": "", "search_county": "",
            "search_country": "ro",
            # the weekly run (auto.py, started by Windows Task Scheduler)
            "auto_enabled": False, "auto_day": "SUN", "auto_time": "09:00",
            "auto_query": "", "auto_location": "", "auto_county": "", "auto_country": "ro",
            "keep_signed_in": False,
            "auto_min_fit": 75,
            # applying without you there: off unless you turn it on, and deliberately stricter
            # than the score you would use when reading the ad yourself
            "auto_apply": False, "auto_apply_min_fit": 85, "auto_apply_cap": 5}


def settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
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
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    os.replace(tmp, SETTINGS)


@app.get("/api/settings")
def get_settings():
    return settings()


# ---------- the weekly run ----------
# One scheduled task, owned by this folder. Windows keeps it after the app is closed, which is
# the whole point: the search happens whether or not anyone opens the dashboard.
TASK = "jobhunter weekly search"
KEEP_TASK = "jobhunter keep signed in"
# Hipo's session cookie is the shortest at about six hours, and it is renewed to a full
# six every time the site is visited. Four hours leaves room for a laptop that was asleep
# when a run was due without letting the window close.
KEEP_HOURS = 4
DAYS = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday",
        "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}


def _ps(script):
    """Run a PowerShell snippet. The ScheduledTask cmdlets are used rather than schtasks.exe
    because their output is objects with English names - schtasks prints localised field labels,
    which is unparseable on a Romanian Windows."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


_TASK = [0.0, None]


def task_state():
    """-> what Windows knows about the scheduled task right now.

    Cached briefly: asking costs a PowerShell process, about a second, and it runs on every
    dashboard load for a value that changes only when you press Save.
    """
    if _TASK[1] is not None and time.monotonic() - _TASK[0] < 15:
        return _TASK[1]
    _TASK[:] = [time.monotonic(), _task_state()]
    return _TASK[1]


def _task_state():
    code, out, _ = _ps(
        f"$ErrorActionPreference='SilentlyContinue';"
        f"$t = Get-ScheduledTask -TaskName '{TASK}';"
        f"if (-not $t) {{ '{{}}' }} else {{ $i = $t | Get-ScheduledTaskInfo;"
        f"[pscustomobject]@{{ exists=$true; state=[string]$t.State;"
        f" next=[string]$i.NextRunTime; last=[string]$i.LastRunTime;"
        f" result=$i.LastTaskResult }} | ConvertTo-Json -Compress }}")
    try:
        state = json.loads(out) if code == 0 and out else {}
    except json.JSONDecodeError:
        state = {}
    return {"exists": bool(state.get("exists")), **state}


def schedule(on, day, at):
    """Create or remove the weekly task. Returns "" or a message explaining why it failed."""
    _TASK[1] = None                  # we are about to change it, so do not serve the old answer
    if not on:
        _ps(f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue")
        return ""
    pyw = HERE / ".venv" / "Scripts" / "pythonw.exe"      # windowless: no console pops up
    if not pyw.exists():
        return "The Python environment is missing - start the app once through run.bat first."
    code, _, err = _ps(
        f"$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument 'auto.py' "
        f"-WorkingDirectory '{HERE}';"
        f"$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {DAYS[day]} -At '{at}';"
        # StartWhenAvailable is what makes this work on a laptop: a run missed because the PC
        # was off happens the next time it is on, instead of being skipped for the week.
        f"$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew "
        f"-ExecutionTimeLimit (New-TimeSpan -Hours 2);"
        f"Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s "
        f"-Description 'jobhunter: weekly job search and scoring' -Force | Out-Null")
    return "" if code == 0 else f"Windows refused to create the scheduled task: {err[:200]}"


def keep_signed_in(on):
    """Create or remove the timer that keeps the board sign-ins alive.

    Board sessions are renewed by being visited - measured on all three - so a visit every few
    hours is enough to stay signed in without typing a password again. Nothing is applied for
    and nothing is searched: it loads each board and saves the refreshed cookies.
    """
    _TASK[1] = None
    if not on:
        _ps(f"Unregister-ScheduledTask -TaskName '{KEEP_TASK}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue")
        return ""
    pyw = HERE / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        return "The Python environment is missing - start the app once through run.bat first."
    code, _, err = _ps(
        f"$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument 'auto.py --touch' "
        f"-WorkingDirectory '{HERE}';"
        f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Hours {KEEP_HOURS});"
        f"$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew "
        f"-ExecutionTimeLimit (New-TimeSpan -Minutes 10);"
        f"Register-ScheduledTask -TaskName '{KEEP_TASK}' -Action $a -Trigger $t -Settings $s "
        f"-Description 'jobhunter: keep the board sign-ins alive' -Force | Out-Null")
    return "" if code == 0 else f"Windows refused to create the keep-alive task: {err[:200]}"


@app.get("/api/auto")
def get_auto():
    s = settings()
    try:
        last = json.loads((HERE / "auto_last.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        last = None
    # keep_signed_in is not an auto_ key but the same panel owns it: without it here the
    # checkbox always drew itself unticked, however the scheduled task was actually set
    return {"settings": {k: v for k, v in s.items()
                         if k.startswith("auto_") or k == "keep_signed_in"},
            "task": task_state(), "last": last}


@app.post("/api/auto")
def set_auto(body: dict = Body(...)):
    cur = settings()
    for k in ("auto_enabled", "auto_day", "auto_time", "auto_query", "auto_location",
              "auto_county", "auto_country", "keep_signed_in",
              "auto_min_fit", "auto_apply", "auto_apply_min_fit",
              "auto_apply_cap"):
        if k in body:
            cur[k] = body[k]
    if cur["auto_day"] not in DAYS:
        raise HTTPException(400, f"not a day: {cur['auto_day']}")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cur["auto_time"])):
        raise HTTPException(400, "time must be HH:MM, e.g. 09:00")
    try:
        cur["auto_min_fit"] = max(0, min(100, int(cur["auto_min_fit"])))
        cur["auto_apply_min_fit"] = max(0, min(100, int(cur["auto_apply_min_fit"])))
        cur["auto_apply_cap"] = max(1, min(BATCH_CAP, int(cur["auto_apply_cap"])))
    except (TypeError, ValueError):
        raise HTTPException(400, "the score and the cap must be numbers")
    if cur["auto_apply"] and not cur["auto_enabled"]:
        raise HTTPException(400, "Applying happens during the weekly run, so switch that on too.")
    if cur["auto_enabled"] and not (cur["auto_query"] or "").strip():
        raise HTTPException(400, "Type what the weekly run should search for.")
    save_settings_file(cur)
    problem = schedule(cur["auto_enabled"], cur["auto_day"], cur["auto_time"])
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

    # match on the board's own numeric posting id: the slug after it differs between the list
    # and the search results (diacritics, punctuation), the id does not
    def jid(u):
        m = re.search(r"/locuri_de_munca/(\d+)", u or "")
        return m.group(1) if m else None

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
            c.execute("UPDATE jobs SET status='applied', "
                      "applied_at=COALESCE(applied_at, ?) WHERE url=?",
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


@app.post("/api/auto/run")
def run_auto():
    """Run the weekly search now, in the same way Windows will run it."""
    py = HERE / ".venv" / "Scripts" / "python.exe"
    subprocess.Popen([str(py), str(HERE / "auto.py")], cwd=str(HERE),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


@app.post("/api/settings")
def save_settings(body: dict = Body(...)):
    cur = settings()
    for k in DEFAULTS:
        if k in body:
            cur[k] = body[k]
    if cur["cv_template"] and cur["cv_template"] not in cv_templates():
        raise HTTPException(400, f"no such CV template: {cur['cv_template']}")
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
    out = []
    for x in v or []:
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
    out = []
    for x in v or []:
        if not x:
            continue                      # else None would become the language "None"
        if isinstance(x, dict):
            out.append({"name": (x.get("name") or "").strip(), "level": (x.get("level") or "").strip()})
        else:
            m = LEVEL_SPLIT.match(str(x))
            out.append({"name": m.group(1), "level": m.group(2)} if m else {"name": str(x).strip(), "level": ""})
    return [x for x in out if x["name"]]


def profile():
    try:
        p = json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}
        if not isinstance(p, dict):
            raise ValueError("profile.json is not an object")
    except (OSError, ValueError) as e:
        # never 500 the whole app over a damaged file - the profile page must stay reachable
        print(f"[profile] unreadable ({e}); starting from an empty profile")
        p = {}
    p = {**llm.EMPTY, **p}
    p["languages"] = _langs(p.get("languages"))
    for k in STR_LIST_KEYS:
        p[k] = _strs(p.get(k))
    return p


def save_profile(p):
    p["languages"] = _langs(p.get("languages"))
    for k in STR_LIST_KEYS:
        p[k] = _strs(p.get(k))
    # write-then-replace: a crash or an overlapping save must not leave a half-written profile
    tmp = PROFILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PROFILE)


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
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    # the county list lives in scrape.py, where the matching also happens - rendering the
    # dropdown from it means the two can never drift apart
    return tpl.TemplateResponse(request, "dashboard.html", {
        "counties": [(slug, name) for slug, (name, _towns) in sorted(
            scrape.COUNTIES.items(), key=lambda kv: kv[1][0])]})


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    return tpl.TemplateResponse(request, "profile.html")


# ---------- profile ----------
@app.get("/api/profile")
def get_profile():
    return profile()


@app.post("/api/profile")
def post_profile(p: dict = Body(...)):
    save_profile({**llm.EMPTY, **p})
    return {"ok": True}


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


def _cv_text(name, data):
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        import pypdf
        raw = "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(io.BytesIO(data)).pages)
    elif ext == "docx":
        raw = _docx_text(data)
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
        if cur["provider"] == "ollama" and not llm.ollama_up():
            cur["error"] = ("Ollama is selected but is not running on this PC. Start Ollama, "
                            "or pick another provider and paste its key.")
    except RuntimeError as e:
        cur["error"] = str(e)
    live = (cur["provider"], cur["model"])
    return {**cur,
            "chain": [{"provider": p, "model": m, "live": (p, m) == live,
                       "blocked": llm._breaker((p, m)) or ""} for p, m, _ in llm.chain()],
            "providers": {n: {"env": env, "default": dflt,
                              "keyed": bool(llm.cfg(env)) if env else llm.ollama_up()}
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
            raise HTTPException(400, f"{p} would not accept that key: {e}.{had}")

    kv = {"LLM_PROVIDER": p, "LLM_MODEL": model}
    if env and key:                      # blank key = keep the one already saved
        kv[env] = key
    llm.set_cfg(**kv)
    try:
        return {**get_llm(), "check": llm.ask("Reply with JSON only.", 'Return {"ok": true}', 100)}
    except Exception as e:
        raise HTTPException(400, f"Saved, but the test call failed: {e}")


@app.get("/api/llm/models")
async def llm_models(provider: str = ""):
    """Models for the provider the dropdown is showing, not whichever one the chain picked."""
    try:
        return await off(lambda: llm.models(provider or None))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/suggest")
async def suggestions():
    # What employers actually asked for, from the jobs already scored. Counted locally, so this
    # costs nothing extra and the advice stops being generic CV polish.
    top = recurring_gaps(min_fit=50, limit=15)["gaps"]
    market = [(g["gap"], g["jobs"]) for g in top if g["jobs"] > 1]
    return await off(lambda: llm.suggest(profile(), market))


@app.post("/api/suggest/apply")
def apply_suggestion(s: dict = Body(...)):
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
            if not k.isdigit() or int(k) >= len(node):
                raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
            node = node[int(k)]
        elif isinstance(node, dict) and k in node:
            node = node[k]
        else:
            raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
    last, new = parts[-1], s.get("value")
    if isinstance(node, list):
        if not last.isdigit() or int(last) >= len(node):
            raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
        old = node[int(last)]
    else:
        if not isinstance(node, dict):
            raise HTTPException(400, f"suggestion points outside the profile: {s['path']}")
        old = node.get(last)
    if old is not None and type(old) is not type(new):
        raise HTTPException(400, f"suggestion would change {s['path']} from "
                                 f"{type(old).__name__} to {type(new).__name__}")
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
LIST_COLS = ("url, source, title, company, location, posted, fit, why, gaps, untapped, "
             "status, cv, found, note, salary, lang, applied_at, LENGTH(description) AS desc_len")


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
                         "AND gaps != '' AND fit >= ? AND status IN ('new','ready')",
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
        for g in {" ".join(str(x).split()).lower() for x in items if str(x).strip()}:
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
            f"SELECT {LIST_COLS} FROM jobs ORDER BY (fit IS NULL), fit DESC, found DESC")]
    if home:
        for r in rows:
            loc = (r.get("location") or "").strip()
            # an ad that names no location is unknown, not far - saying otherwise would put a
            # warning on every bestjobs row, which publishes no location at all
            r["far"] = bool(loc) and not scrape.in_county(loc, home)
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
    if not p.get("experience") and not p.get("skills"):
        raise HTTPException(400, "Fill in your profile first - there is nothing to match jobs against.")
    queries = [q.strip() for q in re.split(r"[,;]", body.get("query", "")) if q.strip()] or [""]
    loc = body.get("location", "")
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
                warnings.append(f"{b} did not answer this time ({type(e).__name__})")
                print(f"[scrape] {b} failed: {type(e).__name__}: {e}")
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
    step("reading the ads", 0, max(1, len(new_urls)))
    # hydrate reports each page as it lands: this phase is a minute or more on a real search,
    # and a bar that does not move for a minute is the same as no bar at all
    fresh = await off(lambda: scrape.hydrate(
        new_urls, on_progress=lambda d, t: step("reading the ads", d, t)))

    # Now that each ad declares where it is, hold the boards to the county that was asked for.
    # Hipo ignores a county name outright and answers with the whole country instead - measured,
    # not assumed - so without this the dropdown would quietly do nothing on half the results.
    if county:
        fresh = [j for j in fresh if scrape.in_county(j.get("location", ""), county)]

    for b in boards:
        rows = [j for j in fresh if j["source"] == b]
        complaint = scrape.health(b, rows, prior.get(b, 0)) if rows else ""
        if complaint:
            warnings.append(complaint)

    # Two weeks is the shelf life of a job ad. Clear out what has aged past it - but only rows
    # nobody has touched: applied, opened, tailored and skipped all stay, and so does anything
    # holding a CV, exactly as with Clear results.
    with db() as c:
        expired = c.execute(
            # bestjobs publishes no posted date at all, so falling back to when we first saw
            # the ad is the difference between those rows expiring and living for ever
            "DELETE FROM jobs WHERE status IN ('new','vetoed') AND (cv IS NULL OR cv = '') "
            "AND COALESCE(NULLIF(posted, ''), found) < date('now', ?)",
            (f"-{scrape.MAX_AGE_DAYS} days",)).rowcount

    with db() as c:
        for j in fresh:
            if j.get("lang") in ("", None, "en", "ro"):     # keep freehire's 'de', 'nl', ...
                j["lang"] = llm.ad_language(j)
            c.execute("INSERT OR IGNORE INTO jobs(url,source,title,company,location,posted,"
                      "description,note,salary,lang) VALUES(:url,:source,:title,:company,"
                      ":location,:posted,:description,:note,:salary,:lang)",
                      {"note": "", "lang": "", "salary": "",
                       **{k: v for k, v in j.items() if not k.startswith("_")}})
        todo = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE fit IS NULL")]

    # Re-run the gate over every row a search could surface, not just the unscored ones. It is
    # pure string matching, so it costs nothing - and without it, widening the language table or
    # correcting the gate leaves every previously judged row sitting at its old verdict for ever.
    with db() as c:
        judged = [dict(r) for r in c.execute(
            "SELECT * FROM jobs WHERE status IN ('new','ready','vetoed')")]
    todo_urls = {j["url"] for j in todo}
    vetoed, freed = [], []
    for j in judged:
        ok, reason = llm.language_gate(p, j)
        if not ok:
            vetoed.append((j, reason))
            todo = [t for t in todo if t["url"] != j["url"]]
        elif j["status"] == "vetoed":
            freed.append(j)                    # the gate changed its mind: score it again
            if j["url"] not in todo_urls:
                todo.append(j)
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
    step("scoring", 0, len(todo))
    # Six at a time measured twice as fast on a 12-ad sample, but a 144-ad run outran mistral's
    # free tier: 15 calls came back "spent", the breaker parked the provider for 300s each time,
    # and the run averaged 4.8s an ad against the 1.1s measured on 38. No fixed number is right
    # for both sizes, so start wide and back off when the provider says to.
    width, i = WORKERS, 0
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
                return await off(llm.score, p, job)
            finally:
                _done[0] += 1
                step("scoring", len(scored) + _done[0], len(todo))

        got = await asyncio.gather(*(one(j) for j in chunk), return_exceptions=True)
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
    failed = 0
    with db() as c:
        for j, s in zip(todo, scored):
            if isinstance(s, Exception):
                failed += 1
                if isinstance(s, llm.QuotaError) and str(s) not in warnings:
                    warnings.append(str(s))
                print(f"[score] {j['title']}: {s}")
                continue
            # the same scrub the CV gets: models emit **bold** and em-dashes into the reasoning
            # too, and it renders literally on the dashboard
            try:
                # a model that wraps its one answer in a list cost a whole job last run:
                # "score returned list, not an object", and that job was never scored again
                if isinstance(s, list) and len(s) == 1 and isinstance(s[0], dict):
                    s = s[0]
                if not isinstance(s, dict):
                    raise TypeError(f"score returned {type(s).__name__}, not an object")
                c.execute("UPDATE jobs SET fit=?,why=?,gaps=?,untapped=? WHERE url=?",
                          (s.get("fit"), _tidy(s.get("why") or ""),
                           json.dumps(_tidy(s.get("gaps", [])), ensure_ascii=False),
                           json.dumps(_tidy(s.get("untapped", [])), ensure_ascii=False), j["url"]))
            except (TypeError, ValueError, AttributeError) as e:
                # one malformed reply must cost one job, not the whole transaction - every score
                # already written in this loop would otherwise be rolled back with it
                failed += 1
                print(f"[score] {j['title']}: unusable reply: {e}")
    # only rows this search actually moved into 'vetoed': the gate now re-runs over every
    # stored row, so counting the whole list would report the standing total as if it had just
    # happened ("113 skipped on language" on a search that skipped none)
    PROGRESS.update(active=False, phase="", done=0, total=0, pct=100)
    newly_vetoed = sum(1 for j, _ in vetoed if j["status"] != "vetoed")
    return {"found": len(found), "new": len(fresh), "freed": len(freed), "expired": expired,
            "scored": len(todo) - failed,
            "failed": failed, "vetoed": newly_vetoed, "queries": len(queries),
            "warnings": warnings}


def _job(url):
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone()
    if not r:
        raise HTTPException(404, "unknown job")
    return dict(r)


LABELS = {
    "en": dict(profile="Profile", experience="Experience", projects="Projects",
               education="Education", skills="Skills", languages="Languages",
               certifications="Certifications", hobbies="Interests", present="present"),
    "ro": dict(profile="Profil", experience="Experiență profesională", projects="Proiecte",
               education="Educație", skills="Competențe", languages="Limbi",
               certifications="Certificări", hobbies="Interese", present="prezent"),
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
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", (v or "").strip())
    if not m:
        return (v or "").strip()
    year, mon = m.group(1), int(m.group(2))
    return f"{MONTHS[lang][mon - 1]} {year}" if 1 <= mon <= 12 else year


SCRUB = {"—": " - ", "–": "-", "‘": "'", "’": "'",
         "“": '"', "”": '"', "**": "", "__": "", "`": ""}


def _tidy(v):
    """The prompt bans em-dashes and markdown; models still emit both. Strip them on the way to
    the PDF so the rule holds whatever model is answering - and so an ATS reading the text layer
    sees plain ASCII punctuation rather than typographic look-alikes."""
    if isinstance(v, str):
        for bad, good in SCRUB.items():
            v = v.replace(bad, good)
        return v.strip()
    if isinstance(v, list):
        return [_tidy(x) for x in v]
    if isinstance(v, dict):
        return {k: _tidy(x) for k, x in v.items()}
    return v


CV_DIR = HERE / "templates" / "cv"
THUMBS = OUT / ".thumbs"


def cv_templates():
    """Template key -> {name, blurb}, read from the header comment of each templates/cv/*.css."""
    out = {}
    for f in sorted(CV_DIR.glob("*.css")):
        head = f.read_text(encoding="utf-8")[:400]
        m = re.search(r"/\*\s*(.+?)\s*[-–]\s*(.+?)\s*\*/", head, re.S)
        out[f.stem] = {"name": m.group(1).strip() if m else f.stem.title(),
                       "blurb": re.sub(r"\s+", " ", m.group(2)).strip() if m else ""}
    return out


def _cv_html(cv, lang, template):
    def when(start, end):
        """Render a date range. An ASCII hyphen, because ATS parsers split on that and not on
        an en-dash, and nothing at all when the model dropped both ends."""
        a, b = _month(start, lang), _month(end, lang)
        if b and str(end).strip().lower() in ONGOING:
            b = LABELS[lang]["present"]
        return f"{a} - {b}" if a and b else (a or b or "")
    if template not in cv_templates():
        template = "classic"
    return tpl.get_template("cv.html").render(cv=cv, L=LABELS[lang], when=when, lang=lang,
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


def _pdf(cv, path, lang="en", template="classic"):
    """Render the CV html to PDF with Chromium - Playwright is already a dependency, so no PDF lib."""
    from playwright.sync_api import sync_playwright
    cv = _tidy(cv)

    html = _cv_html(cv, lang, template)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content(html, wait_until="load")
        pg.pdf(path=str(path), format="A4", print_background=True,
               margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"})
        b.close()


@app.post("/api/tailor")
async def tailor(body: dict = Body(...)):
    j = _job(body["url"])
    lang = body.get("lang", "auto")
    if lang not in ("auto", "en", "ro"):
        raise HTTPException(400, "lang must be auto, en or ro")
    if lang == "auto":
        lang = llm.ad_language(j)
    template = body.get("template") or settings()["cv_template"] or "classic"
    if template not in cv_templates():
        raise HTTPException(400, f"no such CV template: {template}")
    cv = await off(llm.tailor, profile(), j, lang)
    slug = "".join(ch if ch.isalnum() else "-" for ch in f"{j['company']}-{j['title']}")[:56].strip("-")
    # the url hash keeps two jobs with the same long prefix from overwriting each other's CV
    tag = hashlib.sha1(j["url"].encode()).hexdigest()[:6]
    path = OUT / f"{slug or 'cv'}-{tag}-{lang}.pdf"
    await off(_pdf, cv, path, lang, template)
    with db() as c:
        # a vetoed row you chose to tailor anyway is one you decided to pursue, so promote it
        # like any other - leaving it 'vetoed' hid it and put it on Clear's deletion list
        c.execute("UPDATE jobs SET cv=?, status=CASE WHEN status IN ('new','vetoed') THEN 'ready' ELSE status END "
                  "WHERE url=?", (path.name, j["url"]))
    return {"cv": path.name, "lang": lang, "template": template, "preview": cv}


BATCH_CAP = 20


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
    p, results = profile(), []
    for url in urls:
        j = _job(url)
        board = j["source"] if prefill.apply_mode(j["source"]) == "auto" else ""
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
            auto_send=body.get("auto_send", True)))
        if res.get("submitted") or res.get("already"):
            with db() as c:
                _mark_applied(c, url)
        elif res.get("closed"):
            with db() as c:
                _mark_closed(c, url)
        elif res.get("external"):
            # live, just not one-clickable from here - say so on the card instead of hiding it
            with db() as c:
                c.execute("UPDATE jobs SET note='apply on the employer site' "
                          "WHERE url=? AND status != 'applied'", (url,))
        elif res.get("needs_you"):
            # Screening questions: normally open it for the person, and take it out of the next
            # batch either way. hand_off=False is the scheduled run, where opening a window at
            # 09:00 on a Sunday just leaves Chromium sitting on an empty desk.
            if body.get("hand_off", True):
                prefill.spawn_board(url, j["title"])
            _handed_over(url)
        results.append({"url": url, "title": j["title"], "submitted": res.get("submitted"),
                        "already": res.get("already"), "needs_you": res.get("needs_you"),
                        "error": res.get("error")})
        if res.get("error") and "not signed in" in (res["error"] or ""):
            break
    return {"results": results,
            "sent": sum(1 for r in results if r.get("submitted")),
            "skipped": sum(1 for r in results if r.get("already")),
            "needs_you": sum(1 for r in results if r.get("needs_you")),
            "failed": sum(1 for r in results if r.get("error"))}


@app.get("/api/cv/{name}")
def get_cv(name: str):
    f = OUT / pathlib.Path(name).name
    if not f.exists():
        raise HTTPException(404, "no such CV")
    return FileResponse(f, media_type="application/pdf")


# only boards the app actually submits on need a stored session
SIGNIN = {"ejobs": "https://accounts.ejobs.ro/login",
          "bestjobs": "https://www.bestjobs.eu/ro/login",
          # Hipo stays manual until a sign-in made here is still accepted afterwards. The button
          # is back so that can be tested: every context now shares one browser identity, which
          # is the leading explanation for why its sessions used to die.
          "hipo": "https://www.hipo.ro/locuri-de-munca/logincontcandidat"}


@app.get("/api/boards")
def boards():
    """Which sources the app can apply on, and which you apply to by hand."""
    return {"auto": list(prefill.AUTO_APPLY), "manual": list(prefill.MANUAL_APPLY),
            "profiles": {b: ui["profile"] for b, ui in prefill.BOARD_UI.items()}}


@app.get("/api/signin")
def signin_status():
    """Last known sign-in state per board (cheap - reads the cached verification).

    `stale` is the important part: the cached answer has no expiry of its own, so without it the
    page happily showed "signed in" for a session that had died the day before.
    """
    ago = prefill.board_checked_ago()
    return {"saved": prefill.STATE.exists(), "boards": prefill.board_status(),
            "checked_ago": ago,
            "stale": ago is None or ago > prefill.BOARD_CHECK_STALE}


@app.post("/api/signin/check")
async def signin_check():
    """Actually load each board and look. Slower, so it runs when you come back from signing
    in rather than on every dashboard load."""
    return {"ok": True, "boards": await off(prefill.verify_boards)}


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
    j = _job(body["url"])
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
    status = body.get("status")
    if status not in ("new", "ready", "opened", "applied", "skipped"):
        raise HTTPException(400, f"not a status: {status}")
    with db() as c:
        if status == "applied":
            _mark_applied(c, body["url"])
        elif body.get("undo"):
            # Mark applied sits one click from Skip, so a slip needs a way back - but only for
            # a couple of minutes. After that the row is history and stays as it is.
            n = c.execute("UPDATE jobs SET status=?, applied_at=NULL WHERE url=? AND status='applied' "
                          "AND applied_at >= datetime('now','localtime','-2 minutes')",
                          (status, body["url"])).rowcount
            if not n:
                raise HTTPException(400, "Too late to undo - applied jobs stay in the history.")
        else:
            # applied rows are the record of what you sent, and that record is not editable
            n = c.execute("UPDATE jobs SET status=? WHERE url=? AND status != 'applied'",
                          (status, body["url"])).rowcount
            if not n and c.execute("SELECT 1 FROM jobs WHERE url=? AND status='applied'",
                                   (body["url"],)).fetchone():
                raise HTTPException(400, "Applied jobs stay in the history and cannot be changed.")
        job = one_job(c, body["url"])
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
    drop = tuple(body.get("status") or ("new", "vetoed"))
    assert not set(drop) & set(keep), "refusing to delete rows you have acted on"
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
    with db() as c:
        n = c.execute("UPDATE jobs SET fit=NULL, why=NULL, gaps=NULL, status='new' "
                      "WHERE status=?", (where,)).rowcount
    return {"ok": True, "queued": n}


@app.post("/api/delete")
def delete(body: dict = Body(...)):
    with db() as c:
        row = c.execute("SELECT cv, status FROM jobs WHERE url=?", (body["url"],)).fetchone()
        if row and row["status"] == "applied":
            raise HTTPException(400, "Applied jobs stay in the history and cannot be deleted.")
        c.execute("DELETE FROM jobs WHERE url=?", (body["url"],))
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
    db().close()
    # open the dashboard from here, once the server is about to listen - run.bat used to launch
    # the browser first, so the very first thing a new user saw was "connection refused"
    if os.environ.get("JOB_OPEN"):        # set by run.bat; a developer restart should not
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8777")).start()
    uvicorn.run(app, host="127.0.0.1", port=8777, log_level="warning")
