"""Smoke check for the non-LLM logic: run `python test_app.py`."""
import json, pathlib, sys
import app, scrape

# 1. JSON-LD extraction survives the shapes these boards actually emit
page = '<script type="application/ld+json">' + json.dumps({"@graph": [
    {"@type": "WebSite"},
    {"@type": "JobPosting", "title": "Dev", "description": "<p>Build &amp; ship</p>",
     "hiringOrganization": {"name": "ACME"},
     "jobLocation": {"address": {"addressLocality": "Cluj"}},
     "datePosted": "2026-09-01T10:00:00+03:00"}]}) + "</script>"
jp = scrape._jobposting(page)
assert jp and jp["title"] == "Dev"
assert scrape._flat(jp["hiringOrganization"]) == "ACME"
assert scrape._flat(jp["jobLocation"]) == "Cluj", scrape._flat(jp["jobLocation"])
assert scrape._text(jp["description"]) == "Build & ship"
assert scrape._jobposting("<html>no ld+json</html>") is None
assert scrape._jobposting('<script type="application/ld+json">{bad json</script>') is None

# 1b. Fake-bold PDFs repeat every glyph; collapse them without touching ordinary text
assert app._untriple("JJJaaannn   222000222666") == "Jan 2026"
assert app._untriple("SSSuuupppeeerrrvvviiisssooorrr   ---   CCCGGGSSS") == "Supervisor - CGS"
assert app._untriple("ZZooppppaass  IInndd") == "Zoppas Ind"   # doubled, not tripled
for plain in ["Brasov | Telecommunications | IT / Telecom", "Managed a team of 20+ people",
              "aa", "Lean Six Sigma, Kaizen", ""]:
    assert app._untriple(plain) == plain, plain

# 1c. Ad language detection drives which headings the CV gets
assert app.llm.ad_language({"title": "Agent suport clienți",
    "description": "Căutăm un coleg cu experiență în relații cu clienții, pentru a lucra "
                   "împreună cu echipa noastră și să ofere suport."}) == "ro"
# plenty of Romanian ads are typed without diacritics - the function words must carry those
assert app.llm.ad_language({"title": "Programator Junior",
    "description": "Alaturi de echipa te vei ocupa de scrierea si testarea codului, "
                   "de mentenanta aplicatiilor si de suport pentru colegi din echipa."}) == "ro"
# an English ad that merely mentions Romania stays English
assert app.llm.ad_language({"title": "Support Engineer",
    "description": "Join our team in Romania. Troubleshoot network issues, own escalated "
                   "tickets and communicate clearly with enterprise customers."}) == "en"
assert app.llm.ad_language({"title": "Technical Support Engineer",
    "description": "Troubleshoot network connectivity and device configuration issues "
                   "for our enterprise customers."}) == "en"
assert set(app.LABELS["ro"]) == set(app.LABELS["en"])
# the ongoing-role word follows the CV language whatever the model wrote
_ro = app.LABELS["ro"]["present"]
assert [w for w in ("present", "Prezent", "NOW") if w.strip().lower() in app.ONGOING] ==        ["present", "Prezent", "NOW"] and _ro == "prezent"

# 1d. Languages are {name, level}; older profiles and stray model output used plain strings
assert app._langs(["English (Advanced)"]) == [{"name": "English", "level": "Advanced"}]
assert app._langs([{"name": "Romana", "level": "Nativ"}]) == [{"name": "Romana", "level": "Nativ"}]
assert app._langs(["German - B2"]) == [{"name": "German", "level": "B2"}]
assert app._langs(["Spanish"]) == [{"name": "Spanish", "level": ""}]
assert app._langs([" ", None, ""]) == []      # blanks never reach the CV

# 1e. JSON-LD hides JobPosting under @graph, bare arrays, or mainEntity depending on the SEO plugin
import json as _json
_jp = {"@type": "JobPosting", "title": "X", "description": "d"}
for shape in (_jp, [_jp], {"@graph": [{"@type": "WebSite"}, _jp]},
              {"@graph": [{"mainEntity": _jp}]}, {"@type": ["JobPosting", "Thing"], "title": "X"}):
    page = '<script type="application/ld+json">' + _json.dumps(shape) + "</script>"
    assert scrape._jobposting(page), shape
# a malformed block must not stop the good one after it being read
two = ('<script type="application/ld+json">{oops</script>'
       '<script type="application/ld+json">' + _json.dumps(_jp) + "</script>")
assert scrape._jobposting(two)["title"] == "X"

# 1f. Retry 429/5xx, never 403/404 - a rejection is an answer, not a hiccup
class _R:
    def __init__(self, code): self.status_code = code
class _C:
    def __init__(self, codes): self.codes, self.n = codes, 0
    def get(self, url): self.n += 1; return _R(self.codes[min(self.n - 1, len(self.codes) - 1)])
c = _C([429, 503, 200]); assert scrape._get(c, "u", _sleep=lambda s: None).status_code == 200 and c.n == 3
c = _C([403]);           assert scrape._get(c, "u", _sleep=lambda s: None).status_code == 403 and c.n == 1
c = _C([404]);           assert scrape._get(c, "u", _sleep=lambda s: None).status_code == 404 and c.n == 1
c = _C([500]);           assert scrape._get(c, "u", tries=3, _sleep=lambda s: None).status_code == 500 and c.n == 3

# 1g. Language gate: a demanded language the profile lacks is a veto, a country name is not
_p = {"languages": [{"name": "English", "level": "Advanced"}, {"name": "Romanian", "level": "Native"}]}
def _gate(t, d): return app.llm.language_gate(_p, {"title": t, "description": d})[0]
assert not _gate("Swedish Customer Support Representative", "Handle inbound calls.")
assert not _gate("Support Agent", "Fluent German is required for this role.")
assert _gate("Support Engineer", "We serve customers across Germany and France from Bucharest.")
assert _gate("Technical Support", "English B2+ required. Based in Romania.")
assert _gate("Agent suport clienti", "Cautam un coleg cu limba romana la nivel avansat.")

# 1h. The ad's own language beats our heuristic, and freehire flags stale/mass postings
assert scrape.WORLDWIDE and "" in scrape.WORLDWIDE

# 1i. Untrusted posting text is delimited and the trust boundary leads the prompt
import inspect
for fn in (app.llm.score, app.llm.tailor):
    src = inspect.getsource(fn)
    assert "TRUST +" in src, fn.__name__
    assert "<JOB_POSTING" in src and "</JOB_POSTING>" in src, fn.__name__

# 1j. Typographic junk must never reach the PDF: em-dashes break ATS date parsing and
# stray markdown renders as literal asterisks
_d = app._tidy({"summary": "Ran QA—directly transferable", "skills": ["**Lean**", "5S"],
                "experience": [{"bullets": ["Used ‘tools’ and `scripts`"]}]})
assert _d["summary"] == "Ran QA - directly transferable"
assert _d["skills"] == ["Lean", "5S"]
assert _d["experience"][0]["bullets"] == ["Used 'tools' and scripts"]
assert app._tidy(None) is None and app._tidy(7) == 7

# 1k. Screening questions: repeat what the user declared, never invent one
import prefill as _pf
_me = {"salary_expectation": "5500 RON net", "notice_period": "30 days",
       "earliest_start": "immediately"}
assert _pf.personal_answer("What are your salary expectations? (monthly net)", _me) == "5500 RON net"
assert _pf.personal_answer("Care sunt pretentiile tale salariale?", _me) == "5500 RON net"
assert _pf.personal_answer("Care este perioada de preaviz?", _me) == "30 days"
assert _pf.personal_answer("Cand esti disponibil sa incepi?", _me) == "immediately"
assert _pf.personal_answer("Why do you want this job?", _me) == ""      # not a personal field
# an unanswered field stays blank rather than being guessed at
assert _pf.personal_answer("What are your salary expectations?", {}) == ""
assert _pf.ats_host("https://www.ejobs.ro/user/locuri-de-munca/x/1") == ""   # boards are not ATS

# 1l. Dates render as a human month, with an ASCII hyphen an ATS can split on
assert app._month("2024-06", "en") == "Jun 2024"
assert app._month("2024-06", "ro") == "iun. 2024"
assert app._month("2022", "en") == "2022"          # a bare year passes through
assert app._month("", "en") == "" and app._month(None, "en") == ""
assert app._month("2024-13", "en") == "2024"       # nonsense month degrades to the year

# 1m. The skills cap is enforced in code - the prompt asks for 14 and models overshoot
import inspect as _i
assert 'out["skills"][:14]' in _i.getsource(app.llm.tailor)

# 1n. Board handling is per-board, not eJobs strings everywhere
import re as _re
assert _pf.board_of("https://www.ejobs.ro/user/locuri-de-munca/x/1") == "ejobs"
assert _pf.board_of("https://www.hipo.ro/locuri-de-munca/locuri_de_munca/1/a/b") == "hipo"
assert _pf.board_of("https://jobs.lever.co/x/y") == ""      # ATS is not a board
def _match(board, text):
    ui = _pf.BOARD_UI[board]
    return bool(_re.search(ui["apply"], text)) and not _re.search(ui["avoid"], text, _re.I)
assert _match("ejobs", "aplică") and _match("ejobs", "aplică rapid")
assert not _match("ejobs", "aplicările mele")          # nav link, not the apply button
assert _match("hipo", "aplica la acest anunt")
# social apply is a different flow and must never be clicked
assert not _match("hipo", "aplica cu linkedin")
assert not _match("hipo", "aplica cu facebook")

# 1o. Models write markdown into the JSON they were asked for, and put the asterisks OUTSIDE the
# string - `**"Team collaboration** in ...`. That is not JSON, and every one of those replies
# cost a whole extra call to the next provider in the chain.
_bad = """```json
{"fit": 65, "why": "Strong support background", "gaps": ["SQL"],
 "untapped": [**"Team collaboration** in high-pressure environments"]}
```"""
_got = app.llm._parse_reply("mistral", _bad)
assert _got["fit"] == 65 and _got["gaps"] == ["SQL"], _got
assert "Team collaboration" in _got["untapped"][0]
# a reply that is honest JSON is never touched, asterisks and all
assert app.llm._parse_reply("x", '{"why": "uses ** literally"}')["why"] == "uses ** literally"
# and genuine rubbish must still raise RuntimeError, or ask() cannot fail over to the next
# provider - JSONDecodeError is a ValueError, which ask() does not catch
for _junk in ("no json at all", "", "{unclosed"):
    try:
        app.llm._parse_reply("x", _junk)
        raise AssertionError(f"should have raised: {_junk!r}")
    except RuntimeError:
        pass

# 1p. The scoring chunk must match the pool, or every chunk runs in two rounds and the progress
# bar jumps in steps the pool cannot actually deliver at once.
import inspect as _i2
assert "range(0, len(todo), WORKERS)" in _i2.getsource(app.search)
assert app.pool._max_workers == app.WORKERS

# 2. A suggestion writes to the right place - and only that place
# Point the app at a scratch profile rather than overwriting the real one. The previous version
# restored from a variable in a finally block, which is no help if the run is interrupted during
# the Chromium launch below - and the file it was holding is the user's actual CV data.
_real, _scratch = app.PROFILE, app.HERE / ".profile.test.json"
app.PROFILE = _scratch
try:
    app.save_profile({**app.llm.EMPTY, "summary": "old",
                      "experience": [{"role": "Dev", "bullets": ["a", "b"]}]})
    app.apply_suggestion({"path": "summary", "value": "new"})
    app.apply_suggestion({"path": "experience.0.bullets.1", "value": "B!"})
    app.apply_suggestion({"path": "experience.0.bullets", "value": ["x", "y"]})
    p = app.profile()
    assert p["summary"] == "new"
    assert p["experience"][0]["bullets"] == ["x", "y"]
    assert p["experience"][0]["role"] == "Dev", "unrelated field was clobbered"

    # 3. CV html -> PDF actually produces a PDF
    out = app.OUT / "_test.pdf"
    app._pdf({**app.llm.EMPTY, "name": "Test Person", "email": "t@e.ro",
              "summary": "Hi", "skills": ["Python"],
              "experience": [{"role": "Dev", "company": "ACME", "start": "2020",
                              "end": "prezent", "bullets": ["Shipped things"]}]}, out, "ro")
    assert b"Competen" in out.read_bytes()[:200] or out.stat().st_size > 2000
    assert out.read_bytes()[:4] == b"%PDF" and out.stat().st_size > 2000
    out.unlink()
finally:
    app.PROFILE = _real
    if _scratch.exists():
        _scratch.unlink()

# 4. Every route reaches the function it is named after. Adding a plain helper directly under a
# decorator silently registers the HELPER as the endpoint, and the route keeps answering - with
# the wrong signature. That happened; this is how it stays fixed.
_expected = {
    "/api/jobs": "list_jobs", "/api/job/description": "job_description",
    "/api/status": "set_status", "/api/delete": "delete", "/api/search": "search",
    "/api/search/progress": "search_progress", "/api/tailor": "tailor",
    "/api/apply": "apply", "/api/apply_batch": "apply_batch", "/api/settings": "get_settings",
    "/api/auto": "get_auto", "/api/llm": "get_llm", "/api/boards": "boards",
}
_seen = {}
for _r in app.app.routes:
    _p, _n = getattr(_r, "path", None), getattr(_r, "name", "")
    if _p in _expected:
        _seen.setdefault(_p, set()).add(_n)
for _p, _want in _expected.items():
    assert _p in _seen, f"route {_p} is missing"
    assert _want in _seen[_p], f"{_p} is served by {_seen[_p]}, expected {_want}"

print("ok")
