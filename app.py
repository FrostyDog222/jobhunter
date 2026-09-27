"""jobhunter - a local job-hunting assistant. Run: run.bat  ->  http://127.0.0.1:8777"""
import asyncio, hashlib, io, json, os, pathlib, re, sqlite3, sys, webbrowser
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
pool = ThreadPoolExecutor(max_workers=3)   # free LLM tiers rate-limit above this


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS jobs(
        url TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT,
        posted TEXT, description TEXT, fit INTEGER, why TEXT, gaps TEXT,
        status TEXT DEFAULT 'new', cv TEXT, found TEXT DEFAULT (datetime('now')))""")
    for col in ("note TEXT", "lang TEXT", "applied_at TEXT", "untapped TEXT"):   # added later
        try:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
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
DEFAULTS = {"lang": "auto", "headless": "", "cv_template": "", "cv_ask": True}


def settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


@app.get("/api/settings")
def get_settings():
    return settings()


@app.post("/api/settings")
def save_settings(body: dict = Body(...)):
    cur = settings()
    for k in DEFAULTS:
        if k in body:
            cur[k] = body[k]
    if cur["cv_template"] and cur["cv_template"] not in cv_templates():
        raise HTTPException(400, f"no such CV template: {cur['cv_template']}")
    SETTINGS.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    return cur


# "English (Advanced)" / "German - B2" / "German: B2" - but not "Serbo-Croatian", so the
# hyphen only counts as a separator when it has spaces around it
LEVEL_SPLIT = re.compile(r"^\s*(.+?)\s*(?:[(:]|\s[-–]\s)\s*([^)]+?)\s*\)?\s*$")


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
    return p


def save_profile(p):
    p["languages"] = _langs(p.get("languages"))
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


# ---------- pages ----------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return tpl.TemplateResponse(request, "dashboard.html")


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


def _cv_text(name, data):
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        import pypdf
        raw = "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(io.BytesIO(data)).pages)
    elif ext == "docx":
        import docx
        raw = "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
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
def set_llm(body: dict = Body(...)):
    p = body.get("provider")
    if p not in llm.PROVIDERS:
        raise HTTPException(400, f"unknown provider {p!r}")
    env = llm.PROVIDERS[p][0]
    kv = {"LLM_PROVIDER": p, "LLM_MODEL": body.get("model") or None}
    if env and body.get("key"):          # blank key = keep the one already saved
        kv[env] = body["key"]
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
    return await off(llm.suggest, profile())


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
@app.get("/api/jobs")
def list_jobs():
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM jobs ORDER BY (fit IS NULL), fit DESC, found DESC")]


@app.post("/api/search")
async def search(body: dict = Body(...)):
    p = profile()
    if not p.get("experience") and not p.get("skills"):
        raise HTTPException(400, "Fill in your profile first - there is nothing to match jobs against.")
    queries = [q.strip() for q in re.split(r"[,;]", body.get("query", "")) if q.strip()] or [""]
    loc = body.get("location", "")
    country = body.get("country", "ro")
    filters = body.get("filters") or {}
    boards = body.get("boards") or scrape.SOURCES
    limit = int(body.get("limit", 20))

    # Phase 1: discover cheaply - one request per board per query, no detail pages yet.
    found, warnings = [], []
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
    fresh = await off(scrape.hydrate, [j for j in found if j["url"] not in known])

    for b in boards:
        rows = [j for j in fresh if j["source"] == b]
        complaint = scrape.health(b, rows, prior.get(b, 0)) if rows else ""
        if complaint:
            warnings.append(complaint)

    with db() as c:
        for j in fresh:
            if j.get("lang") in ("", None, "en", "ro"):     # keep freehire's 'de', 'nl', ...
                j["lang"] = llm.ad_language(j)
            c.execute("INSERT OR IGNORE INTO jobs(url,source,title,company,location,posted,description,note,lang) "
                      "VALUES(:url,:source,:title,:company,:location,:posted,:description,:note,:lang)",
                      {"note": "", "lang": "", **{k: v for k, v in j.items() if not k.startswith("_")}})
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
    for i in range(0, len(todo), 6):
        scored += await asyncio.gather(
            *(off(llm.score, p, j) for j in todo[i:i + 6]), return_exceptions=True)
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
    newly_vetoed = sum(1 for j, _ in vetoed if j["status"] != "vetoed")
    return {"found": len(found), "new": len(fresh), "freed": len(freed),
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
        elif res.get("needs_you"):
            # screening questions: open it for the person, and take it out of the next batch
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
    """Last known sign-in state per board (cheap - reads the cached verification)."""
    return {"saved": prefill.STATE.exists(), "boards": prefill.board_status()}


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
    return {"ok": True}


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
