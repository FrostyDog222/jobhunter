"""Open a job application form and fill in everything the profile can answer.

It never submits. The browser is left on the filled form so you read it, fix anything the matcher
got wrong, and press the button yourself.

Runs as its own process (see `spawn`), so a browser that hangs or a form that traps focus cannot
take the web app down with it.

    python prefill.py --url <application url> [--cv out/x.pdf] [--headless] [--no-llm]
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

HERE = pathlib.Path(__file__).parent
# Where the signed-in state lives. A Chromium *profile* drops cookies that carry no expiry date -
# and a login session is usually exactly that - so the session is saved explicitly instead, which
# also means no profile lock and no "browser already open" failures.
STATE = HERE / ".session.json"
# whose localStorage is worth carrying between runs: the boards we hold a session for
KEEP_ORIGINS = ("ejobs.ro", "hipo.ro", "bestjobs.eu")
BROWSER_DIR = HERE / ".browser"          # legacy profile dir; only read to migrate old installs


# A login page hands out CSRF and analytics cookies before you type anything, so a loose
# word like "auth" would report a session that does not exist.
SESSION_HINTS = ("session", "sessid", "accesstoken", "refreshtoken", "idtoken", "authtoken",
                 "kratos", "jwt", "remember", "loggedin", "identity")
NOT_SESSION = ("csrf", "consent", "redirect", "locale", "i18n", "ga", "fbp", "ttp", "ttcsid",
               "gid", "obref", "enablecookie", "analytics", "notice", "alert")


def _norm(name):
    """eJobs writes user-access-token, others write user_access_token - same cookie, and a
    separator should not decide whether we think you are logged in."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _browser(pw, headless):
    """Real Chrome when it is installed, otherwise the bundled build.

    Google sign-in will not work in either: Playwright sets navigator.webdriver, Google reads it
    and answers "this browser or app may not be secure". That is their anti-automation control,
    so boards are signed into with an email and password instead.
    """
    last = None
    for kw in ({"channel": "chrome"}, {}):
        try:
            # chromium_sandbox=True drops Playwright's default --no-sandbox, which Chrome warns
            # about in a banner and which makes the browser look unusual to a login backend.
            return pw.chromium.launch(headless=headless, chromium_sandbox=True,
                                      args=["--start-maximized"], **kw)
        except Exception as e:
            last = e
    raise last


def _user_agent(browser):
    """This browser's own user agent with the word 'Headless' taken out, so a visible window and
    a headless one built from the same Chrome introduce themselves identically."""
    try:
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " \
               f"Chrome/{browser.version.split('.')[0]}.0.0.0 Safari/537.36"
    except Exception:
        return None


def _open(pw, headless, fresh_host=None):
    """-> (browser, context, page) with any previously saved session restored.

    fresh_host drops that host's stored cookies before starting: boards bind their login form's
    nonce to a short-lived session cookie, and replaying a stale one makes the POST fail.
    """
    browser = _browser(pw, headless)
    usable = STATE.exists()
    if usable:
        try:
            json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            usable = False          # a half-written state file must not block signing in again
            print("[prefill] session file unreadable, starting a clean context")
    state = None
    if usable:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if fresh_host:
            state["cookies"] = [c for c in state.get("cookies", [])
                                if fresh_host not in c.get("domain", "")]
    # One identity for every context. You sign in through a visible window, which calls itself
    # "Chrome/153", and every check and application afterwards ran headless, which calls itself
    # "HeadlessChrome/153" - so a board that ties a session to the browser it was created in saw
    # a stranger each time. That fits everything Hipo did: accepted in the sign-in window,
    # rejected everywhere else, with the cookies intact.
    ctx = browser.new_context(storage_state=state, no_viewport=not headless,
                              user_agent=_user_agent(browser))
    # eJobs auto-fires Google One Tap on load, which throws "this browser may not be secure" over
    # the form before you have touched anything. It cannot work here, so stop it loading at all.
    # One Tap cannot work in an automated browser and pops "this browser may not be secure" over
    # the form. Serve a stub instead of aborting, so page code awaiting the library still resolves.
    ctx.route(re.compile(r"accounts\.google\.com/gsi/client"), lambda r: r.fulfill(
        status=200, content_type="text/javascript",
        body="window.google=window.google||{};google.accounts={id:{initialize(){},prompt(){},"
             "renderButton(){},disableAutoSelect(){}}};"))
    return browser, ctx, ctx.new_page()


def _save(ctx, only_host=None, visited=None):
    """Write cookies out, merging with what is already saved.

    Merging matters: a sign-in that starts from a clean context would otherwise replace the whole
    file and log you out of the other board. `only_host` keeps a board's sign-in from touching
    any cookie that is not its own.
    """
    try:
        fresh = ctx.storage_state()
    except Exception:
        return False
    try:
        old = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, json.JSONDecodeError):
        old = {}

    live = fresh.get("cookies") or []
    # only_host wipes every stored cookie for that host, which is how a stale one is stopped from
    # coming back (that is what made the Hipo login work). It is destructive, so it belongs on
    # exactly one call: the save made after a sign-in has been VERIFIED. Do not try to infer the
    # right moment from the cookies present - a login page sets analytics and CSRF cookies before
    # you have typed anything, so any "does the context have cookies for this host" test is true
    # from the first page load and the purge lands on a session that is still working.
    keep = []
    for c in old.get("cookies", []):
        dom = c.get("domain", "")
        if only_host and only_host in dom:
            continue                       # this sign-in owns that host now
        keep.append(c)
    # A run that lasted minutes carries a snapshot from when it started, so for a host it never
    # visited the file on disk is the newer truth - writing our copy back would undo a sign-in
    # that happened meanwhile. `visited` names the hosts this run is entitled to save.
    if visited is not None:
        live = [c for c in live if any(h in c.get("domain", "") for h in visited)]
    seen = {(c.get("name"), c.get("domain"), c.get("path")) for c in live}
    merged = [c for c in keep
              if (c.get("name"), c.get("domain"), c.get("path")) not in seen]
    merged += live

    # localStorage is only worth persisting for the boards we sign in to. Everything else is an
    # ATS page opened once, and nothing ever pruned them: the file had reached 2.3 MB, of which
    # 99.8% was a single careers site whose storage we will never need to restore.
    origins = {o.get("origin"): o for o in old.get("origins", [])
               if any(h in (o.get("origin") or "") for h in KEEP_ORIGINS)}
    origins.update({o.get("origin"): o for o in fresh.get("origins", [])
                    if any(h in (o.get("origin") or "") for h in KEEP_ORIGINS)})
    try:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"cookies": merged, "origins": list(origins.values())}),
                       encoding="utf-8")
        os.replace(tmp, STATE)
        return True
    except OSError:
        return False


def _cookie_session(board):
    """Whether the saved state holds a real session for this board. A login page hands out CSRF
    and analytics cookies before you type anything, so a name has to mean a session to count."""
    if not STATE.exists():
        return False
    domain = {"ejobs": "ejobs.ro", "hipo": "hipo.ro"}.get(board, board)
    try:
        cookies = json.loads(STATE.read_text(encoding="utf-8")).get("cookies", [])
    except (OSError, json.JSONDecodeError):
        return False
    for c in cookies:
        if domain not in c.get("domain", ""):
            continue
        n = _norm(c.get("name", ""))
        if any(h in n for h in SESSION_HINTS) and not any(x in n for x in NOT_SESSION):
            return True
    return False


def session_for(board):
    """Whether we hold a usable session for this board.

    A verified probe beats a cookie-name guess, because we asked the board itself. Guessing which
    opaque name means "session" was already wrong for eJobs and Hipo, and BestJobs saves nothing
    that looks like one at all - yet its session demonstrably works. So trust the probe where we
    have one; a stale True costs nothing, since board_apply re-checks the live page before it
    clicks anything. _cookie_session is the fallback for a board never probed.
    """
    probed = board_status().get(board)
    return bool(probed) if probed is not None else _cookie_session(board)


# Matching is fail-closed: the host must BE the apex or end with ".<apex>", so that
# "evil-greenhouse.io" and "greenhouse.io.evil.com" do not pass.
# Forms that are reachable without an account. Workday is deliberately absent: every employer
# on it asks you to create a login before it shows a single field, so there is nothing to fill.
ATS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com",
       "teamtailor.com", "recruitee.com", "personio.de", "personio.com", "jobvite.com")


def ats_host(url):
    r"""-> the ATS apex this posting lives on, or "" if it is not a form we know how to fill.

    Fail-closed twice over. The apex must match exactly or as a dot-suffix, so
    "evil-greenhouse.io" and "greenhouse.io.evil.com" are rejected - and before that, the URL
    itself must be unambiguous: Python ends the authority at "\" but Chromium (WHATWG) does
    not, so "https://evil.com\@boards.greenhouse.io/x" parses here as greenhouse.io and
    navigates there as evil.com. Userinfo plays the same trick, so both are refused outright.
    """
    url = url or ""
    if "\\" in url or "@" in urlsplit(url).netloc or not url.lower().startswith(("http://", "https://")):
        return ""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return next((a for a in ATS if host == a or host.endswith("." + a)), "")


# Ordered: "first name" must be tested before the looser "name".
FIELDS = [
    ("first",     r"first[\s_-]*name|given[\s_-]*name|prenume"),
    ("last",      r"last[\s_-]*name|surname|family[\s_-]*name|nume de familie"),
    ("fullname",  r"full[\s_-]*name|your name|^name$|\bname\b|nume complet"),
    ("email",     r"e-?mail"),
    ("phone",     r"phone|mobile|telephone|telefon"),
    ("linkedin",  r"linked ?in"),
    ("github",    r"git ?hub"),
    ("website",   r"website|portfolio|personal site|blog|\burl\b"),
    ("city",      r"\bcity\b|town|localitate|ora[sș]"),
    ("country",   r"country|\bțara\b|\btara\b"),
    ("location",  r"location|where are you based|current location|address|adres"),
    ("headline",  r"headline|current title|job title|position you|current role"),
    ("company",   r"current employer|current company|most recent employer"),
]


def _values(profile):
    name = (profile.get("name") or "").strip()
    first, _, last = name.partition(" ")
    links = [l for l in (profile.get("links") or []) if l]
    pick = lambda pat: next((l for l in links if re.search(pat, l, re.I)), "")
    loc = (profile.get("location") or "").strip()
    exp = (profile.get("experience") or [{}])[0]
    return {
        "first": first, "last": last.strip(), "fullname": name,
        "email": profile.get("email", ""), "phone": profile.get("phone", ""),
        "location": loc, "city": loc.split(",")[0].strip(),
        "country": loc.split(",")[-1].strip() if "," in loc else "",
        "linkedin": pick(r"linkedin"), "github": pick(r"github"),
        "website": next((l for l in links if not re.search(r"linkedin|github", l, re.I)), ""),
        "headline": profile.get("title", ""), "company": exp.get("company", ""),
    }


def _question(el):
    """The human-readable question, preferring the rendered label so the same field does not
    reach the model twice under two different spellings."""
    lab = _describe(el, labels_only=True).strip()
    lab = re.split(r"\s*\|\s*", lab)[0].strip() if lab else ""
    return (lab or _describe(el))[:200]


def _describe(el, labels_only=False):
    """Everything a human would read to know what a box is for."""
    bits = [el.get_attribute(a) or "" for a in
            ("name", "id", "placeholder", "aria-label", "autocomplete", "data-qa")]
    try:
        lab = el.evaluate("""e => {
            const txt = n => ((n && n.innerText) || '').trim();
            const byFor = e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
            if (txt(byFor)) return txt(byFor);
            if (txt(e.closest('label'))) return txt(e.closest('label'));
            const aria = e.getAttribute('aria-labelledby');
            if (aria && txt(document.getElementById(aria))) return txt(document.getElementById(aria));
            // walk up until a container carries text of its own, and read it WITHOUT the
            // controls inside it - a previous sibling belongs to the previous question
            let n = e.parentElement;
            for (let d = 0; n && d < 4; d++, n = n.parentElement) {
                const c = n.cloneNode(true);
                c.querySelectorAll('input,textarea,select,button,script,style').forEach(x => x.remove());
                const t = (c.innerText || '').trim();
                if (t.length > 2) return t;
            }
            return '';
        }""") or ""
    except Exception:
        lab = ""
    return lab.strip() if labels_only else " ".join(bits + [lab]).strip()


def _editable_inputs(page):
    out = []
    for el in page.query_selector_all("input, textarea"):
        try:
            if not el.is_visible() or not el.is_editable():
                continue
            kind = (el.get_attribute("type") or "text").lower()
            if kind in ("hidden", "submit", "button", "checkbox", "radio", "file"):
                continue
            # a React dropdown is an <input role="combobox">: typing a value into it selects
            # nothing, and leaves text in the box that looks like an answer
            if (el.get_attribute("role") or "").lower() in ("combobox", "listbox"):
                continue
            out.append((el, kind))
        except Exception:
            continue
    return out


# Preference order is deliberate: decline outright, else open the settings panel and save it
# with nothing extra enabled. "Accept all" is never clicked - a consent wall in the way is not a
# reason to opt someone into tracking on their behalf.
REJECT = r"reject all|reject|refuse|decline|necessary only|only necessary|essential only|"          r"respinge|refuz|doar necesare|doar cele necesare|continu[ăa] f[ăa]r[ăa]"
SETTINGS = r"manage|settings|preferences|customi[sz]e|modific[ăa] set[ăa]rile|set[ăa]ri|personalizeaz"
SAVE = r"save settings|save preferences|save choices|confirm choices|save and close|"        r"salveaz[ăa] set[ăa]rile|salveaz[ăa]|confirm[ăa]"


def _click_matching(page, pattern, timeout=2500):
    for el in page.query_selector_all("a, button, [role=button]"):
        try:
            if not el.is_visible():
                continue
            if re.fullmatch(r"\s*", el.inner_text() or ""):
                continue
            if re.search(pattern, el.inner_text(), re.I):
                el.click(timeout=timeout)
                page.wait_for_timeout(1200)
                return True
        except Exception:
            continue
    return False


def dismiss_consent(page):
    """Get a cookie wall out of the way without accepting tracking. Returns what it did.

    Every click here is guarded: consent wording overlaps with ordinary link text ("detalii",
    "personalizarea navigarii"), and a mis-match navigates the page somewhere else entirely.
    If the url moves, it was the wrong control - go back and give up.
    """
    def guarded(pattern):
        before = page.url
        if not _click_matching(page, pattern):
            return False
        if page.url != before:
            try:
                page.go_back(wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(600)
            except Exception:
                pass
            return False
        return True

    try:
        if guarded(REJECT):
            return "rejected"
        if guarded(SETTINGS) and guarded(SAVE):
            return "saved necessary-only"
        return ""
    except Exception:
        return ""


def reach_form(page):
    """Some boards show the posting first and keep the form one click away (Workable and Lever
    use /apply/, Ashby /application). Try those paths, then the apply link. This only ever
    navigates to the form - anything that looks like a submit control is left alone."""
    if _editable_inputs(page):
        return True

    base = page.url.split("?")[0].split("#")[0].rstrip("/")
    # the three conventions in the wild: Workable and Lever use /apply/, Ashby uses /application
    for candidate in (base + "/apply/", base + "/apply", base + "/application"):
        try:
            page.goto(candidate, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            if _editable_inputs(page):
                return True
        except Exception:
            continue

    try:
        page.goto(base, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
    except Exception:
        pass
    for el in page.query_selector_all("a, button"):
        try:
            if not el.is_visible():
                continue
            text = ((el.inner_text() or "") + " " + (el.get_attribute("href") or "")).strip()
            if not re.search(r"\bapply\b|aplica", text, re.I):
                continue
            if re.search(r"submit|trimite|\bsend\b", text, re.I):
                continue                      # never the button that files the application
            el.click()
            page.wait_for_timeout(3000)
            if _editable_inputs(page):
                return True
        except Exception:
            continue
    return bool(_editable_inputs(page))


def fill_known(page, profile):
    """Pass 1: the fields every application asks for, matched by label. Deterministic."""
    vals, filled, used = _values(profile), [], set()
    for el, _kind in _editable_inputs(page):
        try:
            desc = _describe(el).lower()
            for key, pat in FIELDS:
                if key in used or not vals.get(key) or not re.search(pat, desc):
                    continue
                if (el.input_value() or "").strip():
                    break                        # never overwrite what is already there
                el.fill(vals[key])
                filled.append(key)
                used.add(key)
                break
        except Exception:
            continue                             # one awkward widget must not stop the rest
    return filled


def attach_cv(page, cv_path):
    for el in page.query_selector_all('input[type="file"]'):
        try:
            desc = _describe(el).lower()
            if re.search(r"cover", desc) and not re.search(r"resume|cv\b", desc):
                continue
            el.set_input_files(str(cv_path))
            return True
        except Exception:
            continue
    return False


# A dropdown still showing "Select...", "-- Choose one --", "Alege o opțiune" or "---" has not
# been answered, whichever position that option sits in. The test is that EVERY word in the cell
# is filler: matching the first word instead threw away "Selected for interview" as a placeholder,
# and demanding a word boundary after "selecta" missed "Selectează opțiunea" entirely.
FILLER_WORDS = {
    "select", "selected", "selecteaza", "selectează", "selectati", "selectați", "selectare",
    "choose", "chose", "pick", "alege", "alegeti", "alegeți", "alegere", "please", "va", "vă",
    "rugam", "rugăm", "an", "a", "the", "one", "your", "option", "options", "optiune",
    "opțiune", "optiunea", "opțiunea", "optiuni", "opțiuni", "raspuns", "răspuns",
    "raspunsul", "răspunsul", "none", "n", "na", "nimic", "below", "de", "mai", "jos", "din",
    "lista", "listă", "here", "aici", "o", "un", "to",
}


def is_placeholder(text):
    """-> True if this dropdown cell is prompting for an answer rather than holding one."""
    words = re.findall(r"[^\W\d_]+", (text or "").lower(), re.UNICODE)
    return all(w in FILLER_WORDS for w in words)          # no words at all ("---") counts too


def open_questions(page):
    """Pass 2 targets: every still-empty text box and every unanswered dropdown."""
    qs = []
    for el, kind in _editable_inputs(page):
        try:
            if (el.input_value() or "").strip():
                continue
            label = _question(el)
            if len(label.strip()) < 3:
                continue
            qs.append({"el": el, "tag": "input", "label": label, "options": []})
        except Exception:
            continue
    for el in page.query_selector_all("select"):
        try:
            if not el.is_visible():
                continue
            opts = [o.strip() for o in el.eval_on_selector_all(
                "option", "os => os.map(o => o.textContent.trim())") if o.strip()]
            cur = el.evaluate("e => e.options[e.selectedIndex] ? e.options[e.selectedIndex].text : ''")
            # Three ways a dropdown is still unanswered, and only the first was checked. A select
            # with no selection at all has an empty VALUE however its text reads, and a
            # placeholder is not always the first option - "Alege..." sits second on eJobs'
            # salary field, under a blank. Counting those as answered sent the application with
            # the employer's own default where an answer belonged.
            val = (el.input_value() or "").strip()
            placeholder = is_placeholder(cur)
            if val and cur.strip() and cur.strip() not in opts[:1] and not placeholder:
                continue                          # already answered
            qs.append({"el": el, "tag": "select", "label": _question(el),
                       "options": [o for o in opts if o.lower() not in ("", "select...", "select")][:25]})
        except Exception:
            continue
    return qs


def answer_questions(profile, job_title, questions):
    """Ask the model to answer the employer's own questions from the profile - and only from it."""
    import llm
    payload = [{"i": i, "question": q["label"], "options": q["options"]}
               for i, q in enumerate(questions)]
    return llm.ask(
        "You are filling in a job application form on behalf of a candidate, using ONLY their "
        "profile. Answer each question from the profile's facts. Rules: "
        "(1) If the profile does not answer it, return an empty string - never guess and never "
        "invent a fact. Always return empty for questions about gender, race or ethnicity, "
        "sexual orientation, disability, veteran status, age or salary: those are the "
        "candidate's to answer, not yours, even when the profile happens to mention something. "
        "(2) DO answer what the profile plainly settles - which languages they speak and at what "
        "level, years of experience, whether they hold a given skill, their current role, their "
        "notice period if stated. 'Are you fluent in French?' is answerable No when the profile "
        "lists only English and Romanian. "
        "(3) If 'options' is non-empty you must return EXACTLY one of those strings, or empty. "
        "(4) Free-text answers are short and concrete: one or two sentences, first person, no "
        "cliches, no em-dashes. "
        'Output ONLY JSON: {"answers": [{"i": <index>, "value": "<answer or empty string>"}]}',
        f"Candidate profile:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"Applying for: {job_title}\n\nQuestions:\n{json.dumps(payload, ensure_ascii=False)}",
        max_tokens=3000,
    )


def run(url, cv_path=None, headless=False, use_llm=True, profile=None, job_title=""):
    from playwright.sync_api import sync_playwright
    report = {"url": url, "filled": [], "answered": [], "left_blank": [], "cv": False,
              "consent": "", "signed_in": None, "error": None}
    profile = profile if profile is not None else json.loads(
        (HERE / "profile.json").read_text(encoding="utf-8"))

    BROWSER_DIR.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser, ctx, page = _open(pw, headless)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)          # let the form's own scripts render it
            consent = dismiss_consent(page)      # a cookie wall blocks every later click
            if consent:
                report["consent"] = consent
                page.wait_for_timeout(1200)
            if not reach_form(page):
                report["error"] = "no application form found on this page"
            report["url"] = page.url
            report["filled"] = fill_known(page, profile)
            if cv_path:
                report["cv"] = attach_cv(page, cv_path)

            # Salary, notice period and start date: your own words from the profile page, used
            # as written. These never go to the model - and a question of that kind which you
            # have not answered is left blank for you, not guessed.
            mine = []
            for el, kind in _editable_inputs(page):
                try:
                    if (el.input_value() or "").strip():
                        continue
                    q = _question(el)
                    val = personal_answer(q, profile)
                    if val:
                        el.fill(val)
                        mine.append(q[:70])
                except Exception:
                    continue
            report["personal"] = mine

            if use_llm:
                qs = [q for q in open_questions(page)
                      if not any(re.search(pat, q.get("label", ""), re.I) for _, pat in PERSONAL)]
                if qs:
                    try:
                        answers = answer_questions(profile, job_title, qs).get("answers", [])
                    except Exception as e:
                        answers = []
                        report["error"] = f"questions unanswered: {type(e).__name__}: {e}"
                    for a in answers:
                        q = qs[a["i"]] if 0 <= a.get("i", -1) < len(qs) else None
                        val = (a.get("value") or "").strip()
                        if not q or not val:
                            continue
                        try:
                            if q["tag"] == "select":
                                q["el"].select_option(label=val)
                            else:
                                q["el"].fill(val)
                            report["answered"].append({"q": q["label"][:90], "a": val[:120]})
                        except Exception:
                            continue
                    answered_labels = {a["q"] for a in report["answered"]}
                    seen = set()
                    for q in qs:                       # one question reaches us as both the
                        lab = q["label"][:90]          # input and its own label element
                        gist = re.sub(r"[^a-z0-9]+", "", lab.lower())[:40]
                        if lab in answered_labels or gist in seen:
                            continue
                        seen.add(gist)
                        report["left_blank"].append(lab)
        except Exception as e:
            report["error"] = f"{type(e).__name__}: {e}"

        print(json.dumps(report, ensure_ascii=False, indent=1))
        if not headless:
            # Park until the person closes the tab. wait_for_event(timeout=0) returns immediately
            # here, which would shut the browser the moment it was filled.
            try:
                while not page.is_closed():
                    time.sleep(1)
            except Exception:
                pass
        # Only the hosts this window actually visited. It parks until you close the tab, so by
        # then its snapshot can be many minutes old - writing it back whole would roll back a
        # board sign-in you did in the meantime.
        here = ""
        try:
            here = urlsplit(page.url).hostname or ""
        except Exception:
            pass
        _save(ctx, visited=tuple(h for h in {ats_host(url), here} if h) or None)
        browser.close()
    return report


APPLIED_MARKERS = ("ai aplicat", "aplicat deja", "candidatura ta", "aplicare trimis")

# Where the posting stops and the rail of other people's suggestions starts. Both boards put
# "Joburi similare" under the ad, and a card there carries the same applied badge for a
# DIFFERENT job.
SIMILAR = ("joburi similare", "job-uri similare", "jobs similare", "anunturi similare",
           "anunțuri similare", "locuri de munca similare", "locuri de muncă similare",
           "similar jobs", "joburi recomandate", "recomandate pentru tine", "alte joburi",
           "s-ar putea sa te intereseze", "s-ar putea să te interese")


def own_text(page):
    """-> the posting's own text, lowercased, without the rail of other jobs beneath it.

    Searching the whole body for "ai aplicat" found it on a suggested job and reported THIS one
    as already applied - which skips it for good, because the row is marked and never reconsidered.
    """
    txt = ""
    for sel in ("main", "article", "[role=main]", "#main"):
        try:
            el = page.query_selector(sel)
            txt = (el.inner_text() if el else "") or ""
            if len(txt.strip()) > 200:     # a <main> holding a spinner is not the posting
                break
            txt = ""
        except Exception:
            txt = ""
    if not txt:
        try:
            txt = page.inner_text("body") or ""
        except Exception:
            return ""
    low = txt.lower()
    # find(-1) for absent, and a heading at position 0 would mean there is no posting above it
    cuts = [i for i in (low.find(m) for m in SIMILAR) if i > 0]
    return low[:min(cuts)] if cuts else low

# Each board words everything differently, so nothing here is hardcoded to eJobs any more.
# signed_out is checked first where a board shows the same nav to everyone: Hipo renders a
# "MyHipo" link whether or not you are logged in, so its absence proves nothing.
BOARD_UI = {
    "ejobs": {
        "probe":      "https://www.ejobs.ro/",
        "profile":    "https://www.ejobs.ro/cv-ul-meu",
        "denied":     ("accounts.ejobs.ro", "/login"),
        "signed_in":  ("cv-ul meu", "aplicările mele"),
        "signed_out": ("intră în contul tău", "creează-ți un cont"),
        "apply":      r"^aplic[ăa]( rapid)?$",
        # "Aplică extern" hands you to the employer's own site. Deliberately NOT in `apply` -
        # we do not click through to an arbitrary careers system - but it does mean the posting
        # is alive, so it must not be mistaken for a closed one.
        "external":   r"aplic[ăa] extern",
        "avoid":      r"linkedin|facebook|google|apple",
        "applied":    APPLIED_MARKERS,
    },
    "hipo": {
        # Hipo shows the same nav to everyone, so text is useless - ask for a members-only page
        # and see whether it bounces you to the login instead
        "probe":      "https://www.hipo.ro/locuri-de-munca/candidat/myhipo",
        "profile":    "https://www.hipo.ro/locuri-de-munca/candidat/myhipo",
        "denied":     ("logincontcandidat", "/login"),
        "signed_in":  (),
        "signed_out": ("intra in cont", "intră în cont", "cont nou"),
        # Hipo labels the same /candidat/aplica/ endpoint several ways, and the label follows the
        # LANGUAGE OF THE AD as well as whether the employer waived the CV: "Aplica la acest
        # anunt", "Aplica fara CV", and on English ads "Apply to this job". Matching only the
        # first hid the button on 4 of 11 Romanian ads sampled, and on every English one.
        "apply":      (r"aplica la acest anun|aplică la acest anun|aplic[aă] f[aă]r[aă] cv"
                       r"|apply (to|for) this job|apply without (a )?cv"),
        # Hipo's equivalent: the apply link 302s out to the employer (Lidl, Leroy Merlin, ...)
        "external":   r"aplica la acest anun|aplică la acest anun|apply (to|for) this job",
        "avoid":      r"linkedin|facebook|google",
        # Hipo's own confirmation is "Ati aplicat deja la acest job" - the words the other way
        # round from "deja aplicat", so that marker never fired and a genuinely successful
        # application came back as "sent it but saw no confirmation".
        "applied":    ("ai aplicat", "deja aplicat", "aplicat deja", "aplicare trimis",
                       "candidatura ta", "ai candidat"),
    },
    "bestjobs": {
        # a React app, so page text is unreliable - but an unauthenticated /ro/profile answers
        # 307 to /ro/login?targetPath=..., which is as clear a signal as a board ever gives
        "probe":      "https://www.bestjobs.eu/ro/profile",
        "profile":    "https://www.bestjobs.eu/ro/profile",
        "denied":     ("/login", "targetpath"),
        "signed_in":  (),
        "signed_out": (),
        "apply":      r"^aplic[ăa]( acum)?$|aplic[ăa] ?&|trimite aplicarea",
        "avoid":      r"linkedin|facebook|google|apple",
        "applied":    ("ai aplicat", "aplicare trimis", "candidatura ta", "deja aplicat"),
    },
}


# Boards the app can submit on, versus boards you apply to by hand.
#
# Hipo is manual on purpose. Its login works fine in the app's browser - the POST returns
# 302 -> /candidat/myhipo - but the resulting session is not recognised once you leave that
# window: the httpOnly cookies are captured and restored intact, are hours from expiry, and are
# still rejected by a plain HTTP client. Something binds it to the live context. Rather than
# guess again, Hipo opens in your own browser where you are properly signed in.
#
# BestJobs is automated. Its button says "Aplica & Incepe interviul", which reads like the start
# of a conversation, but one click applies outright - the card becomes "Ai aplicat deja la acest
# loc de munca" and the interview is optional afterwards. The chat is never automated: the
# mini-interview filler keys off eJobs' own "Mini interviu" wording, so on BestJobs it finds
# nothing and the run reports back instead of typing answers as you.
AUTO_APPLY = ("ejobs", "bestjobs")
MANUAL_APPLY = ("hipo",)


def apply_mode(source):
    """-> 'auto' (the app can submit), 'manual' (you submit), or 'ats' / '' for everything else."""
    if source in AUTO_APPLY:
        return "auto"
    if source in MANUAL_APPLY:
        return "manual"
    return ""


BOARD_HOSTS = {"ejobs": "ejobs.ro", "hipo": "hipo.ro", "bestjobs": "bestjobs.eu"}


def _profile():
    """The saved profile, or {} on a machine where nobody has filled one in yet."""
    try:
        return json.loads((HERE / "profile.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# Where a board lists what you have applied to, and how to read a row out of that page.
# This is better evidence than anything on the job page itself: Hipo puts no "you applied"
# marker on a posting, so the board's own list is the only way to know - and it also covers
# applications you made yourself, in your own browser, which this app never saw.
APPLICATIONS = {
    "hipo": ("https://www.hipo.ro/locuri-de-munca/candidat/myhipo/aplicarileMele",
             """() => [...document.querySelectorAll('a')]
                 .filter(a => (a.getAttribute('href') || '').includes('locuri_de_munca')
                           && !(a.getAttribute('href') || '').includes('Top-Talents'))
                 .map(a => { let n = a, row = '';
                     for (let i = 0; i < 6 && n; i++) { n = n.parentElement;
                       if (n && /data aplic/i.test(n.innerText || '')) { row = n.innerText; break; } }
                     return {url: a.href, title: (a.innerText || '').trim(), row}; })"""),
}


# What each board's own profile page shows, and how to read it. Measured by opening both pages
# with a real session, not guessed: eJobs renders the finished CV as text under Romanian
# headings, BestJobs is an editable form whose inputs carry names.
PROFILE_PAGE = {
    "ejobs": ("https://www.ejobs.ro/cv-ul-meu", """() => {
        const body = (document.body.innerText || '').split('\n').map(s => s.trim());
        const HEAD = ['Despre mine', 'Experien', 'Studii', 'Limbi cunoscute', 'Hobby',
                      'Permis de conducere', 'Competen'];
        const at = t => HEAD.some(h => t.startsWith(h));
        const out = {}; let cur = null;
        for (const line of body) {
            if (!line) continue;
            if (at(line)) { cur = line; out[cur] = []; continue; }
            if (cur) out[cur].push(line);
        }
        return {sections: out,
                headline: (body.find(l => l && l.length < 80) || '')};
    }"""),
    "bestjobs": ("https://www.bestjobs.eu/ro/profile", """() => {
        const f = {};
        for (const el of document.querySelectorAll('input[name], textarea[name]')) {
            if (el.type === 'hidden' || el.type === 'file') continue;
            if (el.name) f[el.name] = (el.value || '').slice(0, 400);
        }
        const body = (document.body.innerText || '').split('\n').map(s => s.trim());
        const HEAD = ['Cine sunt', 'Ce \u00eemi doresc', 'Ce \u0219tiu s\u0103 fac',
                      'Mini interviu'];
        const at = t => HEAD.some(h => t.startsWith(h));
        const out = {}; let cur = null;
        for (const line of body) {
            if (!line) continue;
            if (at(line)) { cur = line; out[cur] = []; continue; }
            if (cur) out[cur].push(line);
        }
        return {fields: f, sections: out};
    }"""),
}


def board_profile(board, headless=True):
    """-> what the board currently shows on your profile. Reads; never writes, never saves.

    The cookie jar is deliberately NOT written back: this is a look, and a look should not be
    able to change anything at all, including the session.
    """
    from playwright.sync_api import sync_playwright
    if board not in PROFILE_PAGE:
        raise ValueError(f"no profile page known for {board!r}")
    url, extract = PROFILE_PAGE[board]
    with sync_playwright() as pw:
        browser, ctx, page = _open(pw, headless=headless)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            dismiss_consent(page)
            page.wait_for_timeout(1200)
            if signed_in_to(page, board) is False:
                raise RuntimeError(f"not signed in to {board}")
            got = page.evaluate(extract)
            got["url"] = page.url
            return got
        finally:
            browser.close()


def board_applications(board, headless=True):
    """-> [{url, title, when}] straight from the board's own "my applications" page.

    Read-only. Raises if the board is not one we can read, or the session has lapsed.
    """
    from playwright.sync_api import sync_playwright
    if board not in APPLICATIONS:
        raise ValueError(f"no applications page known for {board}")
    page_url, extract = APPLICATIONS[board]
    out = []
    with sync_playwright() as pw:
        browser, ctx, page = _open(pw, headless)
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            if any(d in page.url.lower() for d in BOARD_UI[board]["denied"]):
                raise RuntimeError(f"not signed in to {board}")
            for r in page.evaluate(extract):
                m = re.search(r"data aplic[aă]rii:\s*(\d{2})-(\d{2})-(\d{4})", r.get("row") or "", re.I)
                out.append({"url": r["url"], "title": r["title"],
                            "when": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""})
        finally:
            _save(ctx, visited=(BOARD_HOSTS.get(board) or "",))
            browser.close()
    return out


BOARD_APEX = {"ejobs": "ejobs.ro", "hipo": "hipo.ro", "bestjobs": "bestjobs.eu"}


def board_of(url):
    """Which board this url belongs to, exactly. "" when it is none of them.

    The apex itself or a subdomain of it, never a substring: "ejobs.ro" in host is also true of
    ejobs.ro.attacker.com, and this function decides which site's apply flow runs against a real
    session and whose cookies are written back afterwards. ats_host below is already fail-closed
    this way; there was no reason for this one not to be.
    """
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    for board, apex in BOARD_APEX.items():
        if host == apex or host.endswith("." + apex):
            return board
    return ""


def signed_in_to(page, board):
    """-> True/False, or None when the page gives no signal either way."""
    ui = BOARD_UI[board]
    low = page.inner_text("body").lower()
    if any(m in low for m in ui["signed_out"]):
        return False
    if ui["signed_in"]:
        return any(m in low for m in ui["signed_in"])
    return None                      # no positive marker for this board; absence of the
                                     # sign-in prompt is the best signal we have


def external_apply(page, board):
    """Does this posting hand the application off to the employer's own site?

    Hipo says so in the href (redirectAnuntExtern); eJobs says so in the button's words. Either
    way the posting is live and simply cannot be one-clicked from here.
    """
    pat = BOARD_UI.get(board, {}).get("external")
    for el in page.query_selector_all("a, button"):
        try:
            if not el.is_visible():
                continue
            href = el.get_attribute("href") or ""
            if "redirectanuntextern" in href.lower():
                return True
            if pat and re.search(pat, (el.inner_text() or "").strip().lower()) and \
                    "/candidat/aplica/" not in href:
                return True
        except Exception:
            continue
    return False


def apply_control(page, board):
    """The board's own apply control, never a social-login variant of it."""
    ui = BOARD_UI[board]
    for el in page.query_selector_all("a, button"):
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text() or "").strip().lower()
            if not text or not re.search(ui["apply"], text):
                continue
            if re.search(ui["avoid"], text + " " + (el.get_attribute("href") or ""), re.I):
                continue             # "Aplica cu LinkedIn" is a different flow entirely
            return el
        except Exception:
            continue
    return None
MINI = ("mini interviu", "mini-interviu")
# Questions no CV answers. The app never guesses these - it only repeats what you wrote on the
# profile page, and leaves the box empty when you have not.
PERSONAL = (
    ("salary_expectation", r"salar|salariu|remunera|preten[tțţ]|a[sșş]tept[ăa]ri (salariale|financiare)|"
                           r"venit(ul)? (dorit|a[sșş]teptat)|salary expectation|expected (salary|compensation)"),
    ("notice_period",      r"notice period|preaviz|perioad[ăa] de preaviz"),
    ("earliest_start",     r"c[âa]nd\b.{0,25}\bdisponibil|cel mai devreme|data de [îi]ncepere|start date|when can you start|c[âa]nd po[tțţ]i [îi]ncepe|earliest.{0,12}(start|availab)"),
)


def personal_answer(question, profile):
    """-> what you said on the profile page for this kind of question, or "" to leave it blank."""
    for key, pattern in PERSONAL:
        if re.search(pattern, question, re.I):
            return (profile.get(key) or "").strip()
    return ""


def mini_interview(page, board=""):
    """-> the employer's screening inputs if a screening form is open, else [].

    Scoped to the dialog. Matching the whole page would pick up the site's own search box and
    type an LLM answer into it, then count it as an unanswered question and refuse to send.
    """
    if not any(m in page.inner_text("body").lower() for m in MINI):
        return []
    sel = "textarea, input[type=text], select"
    nodes = []
    # NOT "form". Every board page carries a search form, and the docstring above says what
    # happens then: the answer is typed into the site's own search box, the box then looks
    # answered, and the application goes out with junk in it. No container, no questions -
    # the job is handed to the person instead, which is the safe direction.
    for scope in ("[role=dialog]", ".ejobs-modal", ".MiniInterview__Content",
                  "[class*=mini-interviu]", "[class*=MiniInterview]"):
        # :is() is required - "scope a, b, c" only scopes the first selector in the list
        nodes = page.query_selector_all(f"{scope} :is({sel})")
        if nodes:
            break
    out = []
    for el in nodes or page.query_selector_all(sel):
        try:
            if el.is_visible() and el.is_editable():
                out.append(el)
        except Exception:
            continue
    return out


def board_apply(url, headless=True, profile=None, job_title="", auto_send=False):
    """Press a board's one-click apply.

    eJobs has two flavours. Most postings submit on the click, sending the CV stored on your
    board profile. Some open a "Mini interviu" - screening questions the employer added, and
    answering them IS the application. Those are never submitted here: the questions can include
    salary expectations, which is yours to answer, so the dialog is handed back to you prefilled.
    """
    from playwright.sync_api import sync_playwright
    out = {"url": url, "submitted": False, "already": False, "needs_you": False,
           "closed": False, "external": False, "questions": [], "filled": [], "error": None}
    with sync_playwright() as pw:
        browser, ctx, page = _open(pw, headless)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_consent(page)
            page.wait_for_timeout(1200)

            board = board_of(url)
            if not board:
                out["error"] = "not a job board this app knows how to apply on"
                return out
            markers = BOARD_UI[board]["applied"]

            if signed_in_to(page, board) is False:
                remember_signin(board, False)          # so the dashboard stops showing green
                out["error"] = f"not signed in to {board} - use the sign-in button first"
                return out
            low = own_text(page)
            if any(m in low for m in markers):
                out["already"] = True
                return out

            btn = apply_control(page, board)
            if not btn:
                # We got this far, so we are signed in and the page is not already-applied. That
                # leaves two very different cases, and they look identical from here: the board
                # has taken the posting down, or the employer takes applications on their own
                # site. Only the first one should be hidden from the list.
                if external_apply(page, board):
                    out["external"] = True
                    out["error"] = ("this employer takes applications on their own site - "
                                    "open the posting and apply there")
                elif any(d in (page.url or "").lower()
                         for d in BOARD_UI[board].get("denied", ())):
                    # Signed out, not closed. BestJobs declares no signed_out markers, so
                    # signed_in_to can only ever answer None for it and the guard above never
                    # fires - which filed every remaining job in the batch as "closed on the
                    # board": permanently skipped, never applied to, and never mentioned.
                    out["error"] = f"not signed in to {board}"
                else:
                    out["closed"] = True
                    out["error"] = "this posting is closed - the board offers no way to apply"
                return out

            btn.click()
            for _ in range(10):
                page.wait_for_timeout(1000)
                body = own_text(page)
                if any(m in body for m in markers):
                    out["submitted"] = True
                    return out
                fields = mini_interview(page, board)
                if fields:
                    out["questions"] = [_question(f)[:160] for f in fields]
                    out["filled"] = _fill_mini(page, fields, profile, job_title)
                    blank = [_question(f)[:120] for f in fields
                             if not (f.input_value() or "").strip()]
                    out["blank"] = blank
                    if blank or not auto_send:
                        out["needs_you"] = True
                        return out
                    send = next((e for e in page.query_selector_all(
                                     "button, input[type=submit], a")
                                 if e.is_visible()
                                 and "trimite" in ((e.inner_text() or "")
                                                   + (e.get_attribute("value") or "")).lower()), None)
                    if not send:
                        out["needs_you"] = True
                        out["error"] = "filled the mini interviu but found no send button"
                        return out
                    send.click()
                    for _ in range(12):
                        page.wait_for_timeout(1000)
                        if any(m in own_text(page) for m in markers):
                            out["submitted"] = True
                            return out
                    out["needs_you"] = True
                    out["clicked"] = True
                    out["error"] = "sent the mini interviu but saw no confirmation - check it"
                    return out

            # It may well have gone. On eJobs a one-click apply IS the application, and a page
            # that confirms slower than we waited looks identical to one that did nothing.
            # Reporting "nothing happened" left the row untouched at 'new', so the next weekly
            # run applied to the same employer again.
            out["clicked"] = True
            out["error"] = ("pressed apply but saw no confirmation - check the board before "
                            "applying again")
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
        finally:
            # only this board's cookies: a sign-in to another board, in another window, while
            # this run was open must not be rolled back by our older snapshot
            _save(ctx, visited=(BOARD_HOSTS.get(board_of(url)) or "",) if board_of(url) else None)
            if headless:
                browser.close()
            else:
                while not page.is_closed():          # leave it open for you to finish
                    time.sleep(1)
                _save(ctx, visited=(BOARD_HOSTS.get(board_of(url)) or "",) if board_of(url) else None)
                browser.close()
    return out


def _fill_mini(page, fields, profile, job_title):
    """Answer what the profile settles, leave the rest - never salary, never a commitment."""
    if profile is None:
        profile = _profile()
    asks, done = [], []
    for el in fields:
        q = _question(el)
        mine = personal_answer(q, profile)
        if mine:                                      # your own stated answer, used verbatim
            try:
                el.fill(mine)
                done.append(q[:70])
            except Exception:
                pass
            continue
        if any(re.search(pat, q, re.I) for _, pat in PERSONAL):
            continue                                  # you have not answered it, so neither will we
        tag = "input"
        opts = []
        try:
            tag = (el.evaluate("e => e.tagName") or "").lower()
            if tag == "select":
                # offer the model the real options, and never let the pre-selected first one
                # pass for an answer the employer actually got
                opts = [o for o in el.evaluate(
                    "e => Array.from(e.options).map(o => o.label || o.text)") if o]
        except Exception:
            pass
        asks.append({"el": el, "tag": tag, "label": q[:300], "options": opts})
    if not asks:
        return done
    try:
        answers = answer_questions(profile, job_title, asks).get("answers", [])
    except Exception:
        return done
    for a in answers:
        i, val = a.get("i", -1), (a.get("value") or "").strip()
        if not (0 <= i < len(asks) and val):
            continue
        ask = asks[i]
        try:
            if ask["tag"] == "select":
                ask["el"].select_option(label=val)    # fill() throws on a <select>
            else:
                ask["el"].fill(val)
            done.append(ask["label"][:70])
        except Exception:
            continue
    return done


# Where the username and the password go on each board, read off the signed-out page rather
# than guessed. The submit is matched by its text because eJobs' is type=button (React) and
# would not be found by [type=submit].
LOGIN_FORM = {
    "ejobs": {"url": "https://accounts.ejobs.ro/login",
              "user": "input[type=email]", "pass": "input[type=password]",
              "submit": r"intr[ăa] [îi]n cont"},
    "bestjobs": {"url": "https://www.bestjobs.eu/ro/login",
                 "user": "#email", "pass": "#password",
                 "submit": r"intr[ăa] [îi]n cont"},
    "hipo": {"url": "https://www.hipo.ro/locuri-de-munca/logincontcandidat",
             "user": 'input[name="emaillogin"]', "pass": 'input[name="parolalogin"]',
             "submit": r"^login$"},
}


def auto_signin(board, username, password, headless=True):
    """Sign in from a saved username and password. -> (ok, what happened).

    One attempt. No retry loop anywhere in this function or its callers: an unattended loop
    posting a wrong password is how an account gets locked, which is far worse than being
    signed out for a week. The caller counts failures and stops after two.

    The password is typed into the board's own form and goes nowhere else. It is never printed,
    never logged, and never put in the return value.
    """
    from playwright.sync_api import sync_playwright
    form = LOGIN_FORM.get(board)
    if not form:
        return False, f"no login form known for {board}"
    if not username or not password:
        return False, "nothing saved"
    with sync_playwright() as pw:
        # fresh_host: a board ties its login form's nonce to a short-lived cookie, and replaying
        # a stale one makes the POST fail - the same reason the manual sign-in does this.
        browser, ctx, page = _open(pw, headless, fresh_host=BOARD_HOSTS.get(board))
        try:
            page.goto(form["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            dismiss_consent(page)
            page.wait_for_timeout(1200)
            u = page.query_selector(form["user"])
            p = page.query_selector(form["pass"])
            if not u or not p:
                # the form moved, or the board answered with something else entirely
                return False, "could not find the sign-in form on that page"
            u.fill(username)
            p.fill(password)
            btn = next((e for e in page.query_selector_all("button, input[type=submit]")
                        if e.is_visible() and re.search(
                            form["submit"], ((e.inner_text() or "")
                                             + (e.get_attribute("value") or "")).strip(), re.I)),
                       None)
            if not btn:
                return False, "could not find the sign-in button"
            btn.click()
            # A login is ONE navigation. Wait for it to land, then ask the board once.
            #
            # Not in a loop: _probe_signed_in navigates to a members-only page, waits, dismisses
            # the consent banner and retries itself once - so polling it twenty times is up to
            # forty page loads, and each one navigates away from the page the login just
            # produced. Measured: the first real attempt ran for eight minutes before it was
            # killed. It is the check that is slow, not the login.
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                page.wait_for_timeout(6000)       # a SPA that never goes idle is still fine
            page.wait_for_timeout(2500)           # ...and let the token call after it finish
            if _probe_signed_in(page, board):
                _save(ctx, only_host=BOARD_HOSTS.get(board),
                      visited=(BOARD_HOSTS.get(board) or "",))
                remember_signin(board, True)
                return True, "signed in"
            return False, "the sign-in did not take - wrong password, or the board asked "\
                          "something extra (a code, a captcha) that needs you at the keyboard"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"        # never the credentials
        finally:
            browser.close()


def run_signin(url):
    """Open a board's sign-in page and leave it open. You type the credentials into the browser;
    the app never sees them. Closing the tab saves the session into BROWSER_DIR."""
    from playwright.sync_api import sync_playwright
    BROWSER_DIR.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        board0 = next((b for b in BOARD_UI if b in url), "")
        host0 = BOARD_HOSTS.get(board0)
        browser, ctx, page = _open(pw, headless=False, fresh_host=host0)
        # Trace the login round trip into signin.log so a hang can be diagnosed from evidence.
        # Deliberately only method/url/status - never post_data, which holds the password.
        host = urlsplit(url).hostname or ""
        def _req(r):
            if r.method == "POST" and host in (urlsplit(r.url).hostname or ""):
                print(f"[net] --> POST {r.url[:110]}", flush=True)
        def _res(r):
            if host in (urlsplit(r.url).hostname or "") and (r.request.method == "POST"
                                                             or r.status >= 300):
                loc = ""
                try:
                    loc = (r.headers or {}).get("location", "")[:80]
                except Exception:
                    pass
                print(f"[net] <-- {r.status} {r.url[:100]} {loc}", flush=True)
        def _fail(r):
            if host in (urlsplit(r.url).hostname or ""):
                print(f"[net] xxx {r.method} {r.url[:100]} -> {r.failure}", flush=True)
        ctx.on("request", _req)
        ctx.on("response", _res)
        ctx.on("requestfailed", _fail)

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        # deliberately NOT dismissing the cookie banner here: a mis-matched click navigates the
        # page away and you lose the login form mid-typing. You are at the keyboard - your call.
        # Save when the page actually moves, not on a timer: a login is a navigation, so the
        # session is caught the moment it exists, and the window stays completely still while
        # you are typing a password into it.
        #
        # After each navigation, check in a background tab whether that navigation logged us in.
        # When it did, save and close - there is nothing left for you to do in the window, and
        # leaving it open is how the last three attempts got lost.
        board = next((b for b in BOARD_UI if b in url), "")
        saved, last, ok, ticks = False, page.url, None, 0
        while not page.is_closed():
            time.sleep(1)
            ticks += 1
            try:
                here = page.url               # a local property, no call into the browser
            except Exception:
                break
            if here == last:
                # Hipo's login POST can hang with the url unchanged, so a navigation-only save
                # never fires. Snapshot every 10s as a backstop: reading cookies does not touch
                # the page, so it cannot disturb what you are typing.
                if ticks % 10 == 0:
                    saved = _save(ctx, visited=(host0,) if host0 else None) or saved
                continue
            last = here
            # additive only: until the probe says we are in, the session on disk is the good one
            saved = _save(ctx, visited=(host0,) if host0 else None) or saved
            print(f"[signin] navigated to {here[:90]}", flush=True)
            if not board:
                continue
            try:
                probe = ctx.new_page()
                try:
                    if _probe_signed_in(probe, board):
                        ok = True
                finally:
                    probe.close()
            except Exception:
                continue
            print(f"[signin] {board}: signed in = {ok}", flush=True)
            if ok:
                # verified: now it is safe to drop the old cookies for this host, stale ones
                # included, and keep only what this signed-in context holds
                saved = _save(ctx, only_host=host0, visited=(host0,) if host0 else None) or saved
                state = board_status()
                state[board] = True
                BOARD_STATE.write_text(json.dumps(state), encoding="utf-8")
                print(f"[signin] {board}: session saved, closing", flush=True)
                break
        saved = _save(ctx, visited=(host0,) if host0 else None) or saved
        # check our own work before tearing the context down, so the dashboard has a real
        # answer waiting rather than a cookie-name guess
        if board and ok is None:
            try:
                page2 = ctx.new_page()
                ok = _probe_signed_in(page2, board)
                state = board_status()
                state[board] = ok
                BOARD_STATE.write_text(json.dumps(state), encoding="utf-8")
            except Exception as e:
                print(f"[signin] could not verify: {type(e).__name__}: {e}")
        browser.close()
    print(json.dumps({"board": board, "saved": saved, "signed_in": ok}))



BOARD_STATE = HERE / ".boards.json"


def _probe_signed_in(page, board, _retry=True):
    """Ask for a page only a member can see. Where it lands is the answer.

    A "signed out" answer is checked twice. Boards keep a short-lived token next to a long-lived
    one - eJobs' access token lasts about an hour against a 400-day refresh token - and renew it
    with a request the page makes once it has loaded. Reading the body too early therefore
    catches the gap and condemns a session that is about to renew itself. Saying "signed out"
    now raises an alert and makes the weekly run send nothing, so it is worth the second look.
    """
    ui = BOARD_UI[board]
    page.goto(ui["probe"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    dismiss_consent(page)
    page.wait_for_timeout(800)

    def read():
        if any(d in page.url.lower() for d in ui["denied"]):
            return False
        # A board with no positive marker passes on "nothing said no" - so its error page, served
        # with HTTP 200, used to read as signed in. An outage is not an answer either way.
        low = page.inner_text("body").lower()
        if any(m in low for m in ("momentan indisponibil", "pagina accesata nu exista",
                                  "temporarily unavailable", "service unavailable", "bad gateway")):
            raise RuntimeError(f"{board} is showing an error page")
        verdict = signed_in_to(page, board)
        return True if verdict is None else verdict

    ok = read()
    if ok or not _retry:
        return ok
    # give the page time to make its refresh call, then load it again and ask once more
    page.wait_for_timeout(2500)
    return _probe_signed_in(page, board, _retry=False)


def verify_boards(boards=tuple(BOARD_UI)):
    """Load each board and look at the page: the only reliable way to know you are signed in.

    Cookie names were a dead end - eJobs uses user-access-token, Hipo uses ctlyst_hp_sss, and
    guessing which opaque name means "session" got it wrong for both boards in turn. So ask the
    site. It costs one headless page load, cached here so the dashboard stays instant.
    """
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as pw:
        browser, ctx, page = _open(pw, headless=True)
        visited = []
        try:
            for b in boards:
                try:
                    out[b] = _probe_signed_in(page, b)
                    visited.append(BOARD_APEX.get(b, b))
                except Exception as e:
                    # A timeout or a wifi blip is not "signed out". Leave the key unset so the
                    # merge keeps the last verified answer - otherwise the dashboard shows a red
                    # dot and invites you to sign in again over a session that is perfectly fine.
                    print(f"[verify] {b}: could not probe: {type(e).__name__}: {e}")
        finally:
            # visited, not everything: this context started from a snapshot of the file, and the
            # keep-alive runs every half hour. Signing into eJobs in the app while a check was
            # in flight put that snapshot's dead eJobs cookie back over the fresh one, and the
            # sign-in that had just worked was gone. Only the boards this run actually loaded
            # hold a cookie newer than the file's.
            _save(ctx, visited=visited)
            browser.close()
    try:
        # merge: verifying one board must not erase what we know about the others
        BOARD_STATE.write_text(json.dumps({**board_status(), **out}), encoding="utf-8")
    except OSError:
        pass
    return out


# A saved sign-in does not last for ever, and nothing about the cached answer says how old it
# is. Two hours is the line. It was twelve, which is how the dashboard came to show a green dot
# over an eJobs session that had been dead for five: the shortest board session here is one hour,
# so a twelve-hour-old "signed in" was not information, it was a guess that read as a fact.
BOARD_CHECK_STALE = 2 * 3600


def board_checked_ago():
    """-> seconds since the last live verification, or None if it has never run."""
    try:
        return max(0.0, time.time() - BOARD_STATE.stat().st_mtime)
    except OSError:
        return None


def remember_signin(board, signed_in):
    """Write down what a live check just learned, so the rest of the app stops disagreeing.

    Applying opens a browser on the board's own page, which is the most expensive and the most
    current check this app ever performs - and its answer was being dropped on the floor. The
    dashboard went on showing a green dot from a cached answer hours older, and the alert that
    exists to say "you are signed out" stayed quiet.
    """
    try:
        BOARD_STATE.write_text(json.dumps({**board_status(), board: bool(signed_in)}),
                               encoding="utf-8")
    except OSError:
        pass                              # a check we could not write down is not worth failing


def board_status():
    """Last verified result, or a cookie-jar guess before the first verification."""
    if not STATE.exists():
        # no saved sessions at all - a .boards.json that came along in a copied folder must not
        # show green dots for sign-ins this machine does not have
        return {b: False for b in BOARD_UI}
    try:
        return json.loads(BOARD_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # the cookie heuristic directly, never session_for - that would recurse back in here
        return {b: _cookie_session(b) for b in BOARD_UI}


SIGNIN_LOG_CAP = 512 * 1024      # what a few dozen sign-ins come to; older ones are not useful


def _log():
    """Subprocess output goes to a file, not a pipe. A pipe fills at ~64KB and blocks the child
    (Chromium is chatty); DEVNULL avoids that but discards the diagnostics we need when a
    sign-in quietly fails.

    Appended to for ever, though, with the keep-alive task adding to it every half hour. Kept to
    the most recent half a megabyte: what is worth reading is the sign-in that just failed.
    """
    path = HERE / "signin.log"
    try:
        if path.stat().st_size > SIGNIN_LOG_CAP:
            with open(path, "rb") as f:
                f.seek(-SIGNIN_LOG_CAP // 2, 2)
                f.readline()                  # start at a line break, not mid-character
                tail = f.read()
            path.write_bytes(b"[older lines trimmed]\n" + tail)
    except OSError:
        pass                                  # a log we cannot trim is not worth failing over
    return open(path, "a", encoding="utf-8", errors="replace")


def signin(url):
    """Start the sign-in browser in its own process, like every other browser run here."""
    log = _log()
    return subprocess.Popen([sys.executable, str(HERE / "prefill.py"), "--signin", url],
                            cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT)


def spawn_board(url, job_title=""):
    """Reopen a board apply visibly so you can finish a Mini interviu yourself."""
    log = _log()
    return subprocess.Popen([sys.executable, str(HERE / "prefill.py"),
                             "--board-apply", url, "--title", job_title],
                            cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT)


def spawn(url, cv_path=None, headless=False, use_llm=True, job_title=""):
    """Start the fill in a separate process. A browser that hangs or a form that grabs focus
    then cannot block the web app - the old in-thread version could."""
    cmd = [sys.executable, str(HERE / "prefill.py"), "--url", url, "--title", job_title]
    if cv_path:
        cmd += ["--cv", str(cv_path)]
    if headless:
        cmd.append("--headless")
    if not use_llm:
        cmd.append("--no-llm")
    log = _log()
    return subprocess.Popen(cmd, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT)


def _selftest():
    assert ats_host("https://job-boards.greenhouse.io/acme/jobs/123") == "greenhouse.io"
    assert ats_host("https://jobs.lever.co/acme/abc") == "lever.co"
    assert ats_host("https://apply.workable.com/j/ABC") == "workable.com"
    assert ats_host("https://evil-greenhouse.io/x") == ""
    assert ats_host("https://greenhouse.io.evil.com/x") == ""
    assert ats_host("https://greenhouse.io@evil.com/x") == ""
    assert ats_host("https://www.ejobs.ro/user/locuri-de-munca/x/1") == ""
    p = {"name": "Ana Popescu", "email": "a@b.ro", "phone": "+40700", "title": "Trainer",
         "location": "Timisoara, Romania", "experience": [{"company": "Nordic Telecom"}],
         "links": ["https://linkedin.com/in/x", "https://mysite.ro"]}
    v = _values(p)
    assert v["first"] == "Ana" and v["last"] == "Popescu"
    assert v["city"] == "Timisoara" and v["country"] == "Romania"
    assert v["linkedin"].endswith("/in/x") and v["website"] == "https://mysite.ro"
    assert v["headline"] == "Trainer" and v["company"] == "Nordic Telecom"
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--cv")
    ap.add_argument("--title", default="")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-llm", dest="llm", action="store_false")
    ap.add_argument("--signin")
    ap.add_argument("--board-apply")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.board_apply:
        print(json.dumps(board_apply(a.board_apply, headless=False, job_title=a.title,
                               # this branch is only reached via spawn_board, i.e. "here, you
                               # finish it" - it must never press Trimite by itself
                               auto_send=False),
                         ensure_ascii=False, indent=1))
    elif a.signin:
        run_signin(a.signin)
    elif a.selftest or not a.url:
        _selftest()
    else:
        run(a.url, a.cv, a.headless, a.llm, job_title=a.title)
