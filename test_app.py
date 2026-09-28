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
# Hipo labels the same endpoint two ways; the second one hid the button on 4 of 11 ads
assert _match("hipo", "aplica fara cv") and _match("hipo", "aplică fără cv")
# and the label follows the language of the AD, not the site - an English ad says this
assert _match("hipo", "apply to this job") and _match("hipo", "apply without cv")
# a nearby-but-wrong control must still not match
assert not _match("hipo", "apply with linkedin")
# Hipo's question fields are named intrebari[<id>]. The cover-letter box sits on the same
# form and must NOT be scoped in as a question - it would read as unanswered and block
# every send.
assert "intrebari" in _pf.HIPO_Q and "scrisoare" not in _pf.HIPO_Q
# Hipo confirms with "Ati aplicat deja la acest job" - the words the other way round from
# "deja aplicat", so a real application read as "saw no confirmation" until this was added
assert any(m in "ati aplicat deja la acest job" for m in _pf.BOARD_UI["hipo"]["applied"])
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

# 1p. Scoring width answers to the provider. Six at a time measured twice as fast on 12 ads, but
# a 144-ad run outran mistral's free tier - 15 "spent" replies, the breaker parking it 300s each
# time, 4.8s an ad against 1.1s on 38 - so no fixed number suits both sizes.
import inspect as _i2
assert app.pool._max_workers == app.WORKERS      # the pool still has to be able to deliver it
_w, _CAP = app._next_width, app.WORKERS
assert _w(6, 1, 6) == 3 and _w(3, 2, 6) == 1 and _w(1, 1, 6) == 1   # halve, never reach zero
assert _w(1, 0, 6) == 2 and _w(6, 0, 6) == 6                        # creep back, never past cap
_width, _seen = 6, []
for _spent in (0, 2, 0, 0, 1, 0, 0, 0, 0, 0, 0):                    # a bumpy run
    _width = _w(_width, _spent, 6); _seen.append(_width)
assert _seen == [6, 3, 4, 5, 2, 3, 4, 5, 6, 6, 6], _seen
assert max(_seen) <= 6 and min(_seen) >= 1
# and the loop must actually use it, not a hard-coded slice - the step and the slice drifted
# apart once already, agreeing only because both happened to say 6
_ssrc2 = _i2.getsource(app.search)
assert "todo[i:i + width]" in _ssrc2 and "todo[i:i + 6]" not in _ssrc2

# 1q. The weekly run is unattended, and nothing ages out .boards.json - it can say "signed in"
# days after the session died. It must ask the boards themselves before sending applications,
# or an expired session means a week of applications silently going nowhere.
import auto_apply as _aa
class _FakeBoards:
    AUTO_APPLY = ("ejobs", "bestjobs")
    def __init__(self, live, cached): self.live, self.cached, self.probed = live, cached, False
    def verify_boards(self, boards): self.probed = True; return self.live
    def session_for(self, b): return self.cached[b]
def _weekly(live, cached):
    pf = _FakeBoards(live, cached)
    r = _aa.run(None, pf, {"auto_apply_min_fit": 70, "auto_apply_cap": 5}, lambda *a: None)
    return pf.probed, r["note"]
# cache says signed in, the board says otherwise -> nothing is sent
_probed, _note = _weekly({"ejobs": False, "bestjobs": True}, {"ejobs": True, "bestjobs": True})
assert _probed and _note and "Not signed in to ejobs" in _note, _note
# the probe itself failed (wifi blip) -> keep the cached answer, do not declare a live session dead
_probed, _note = _weekly({}, {"ejobs": False, "bestjobs": True})
assert _note and "Not signed in to ejobs" in _note, _note

# 1r. links/skills/certifications/hobbies are lists of strings, but parse_cv reads a human CV and
# sometimes returns [{"name": "Driving license Category B"}]. That showed on the profile page as
# "[object Object]" and would have gone into a tailored CV exactly as literally.
assert app._strs([{"name": "Driving license Category B"}]) == ["Driving license Category B"]
assert app._strs([{"title": "ITIL"}, {"value": "AWS"}, {"text": "PMP"}, {"label": "Scrum"}]) == \
       ["ITIL", "AWS", "PMP", "Scrum"]
assert app._strs(["Excel", "  Salesforce  "]) == ["Excel", "Salesforce"]
assert app._strs([None, "", "   ", {}, {"name": ""}, {"a": 1}]) == []   # never "{'a': 1}" on screen
assert app._strs(None) == []

# 1s. County filtering is checked against the ad's own location, because the boards disagree:
# eJobs filters on a county slug, Hipo ignores one ("Cluj" returns the whole country, measured)
# and only understands city names. Diacritics are folded on both sides - the boards write both.
_ic = scrape.in_county
assert _ic("Cluj-Napoca", "cluj") and _ic("Timișoara", "timis") and _ic("Timisoara", "timis")
assert _ic("Iași", "iasi") and _ic("Bucharest", "bucuresti") and _ic("Voluntari", "ilfov")
assert not _ic("Cluj-Napoca", "timis") and not _ic("Brașov", "bucuresti")
assert not _ic("Ilfoveni", "ilfov")        # Ilfoveni is in Dambovita
assert not _ic("Paradis Mall", "arad")     # "arad" sits inside "Paradis"
assert not _ic("", "cluj")                 # no location cannot be confirmed local
# remote is open to any county, and the boards pad their county pages with these
assert _ic("Remote", "cluj") and _ic("Telemunca", "dolj") and _ic("Remote", "timis")
# a multi-city ad counts if the county is anywhere in the list
assert _ic("Bacău, Iași (Iași), Roman, Vaslui", "iasi")
# "Romania" alone is the whole country; as a suffix it is just the postal address, and most ads
# carry it - treating the suffix as nationwide marked every job reachable from every county
assert _ic("Romania", "timis") and _ic("România", "cluj")
assert not _ic("Sector 6, București, România", "timis"), "a country suffix is not nationwide"
assert not _ic("Iași, România", "timis")
assert _ic("Timișoara, Lugoj", "timis")
assert _ic("Hybrid", "timis") and _ic("Hibrid", "dolj")
assert not _ic("Bacău, Roman, Vaslui", "cluj")
assert _ic("anywhere", "not-a-county") and _ic("x", "")   # unknown/blank never drops an ad
assert len(scrape.COUNTIES) == 42, "41 counties plus Bucharest"

# 1t. A board that offers a signed-in candidate no way to apply has closed the posting. That is
# the only reliable signal: Hipo restamps datePosted to today on ads that are long closed (140
# stored ads across 7 dates, all recent), publishes no validThrough, and shows the apply link to
# a signed-out visitor either way - so a dead ad was being offered as applyable.
import sqlite3 as _sq
_c = _sq.connect(":memory:")
_c.row_factory = _sq.Row
_c.execute("CREATE TABLE jobs(url TEXT PRIMARY KEY, status TEXT, note TEXT, applied_at TEXT)")
_c.executemany("INSERT INTO jobs VALUES(?,?,?,?)",
               [("dead", "new", "", None), ("sent", "applied", "", "2026-09-28 17:08:00")])
app._mark_closed(_c, "dead")
app._mark_closed(_c, "sent")
_dead = _c.execute("SELECT status, note FROM jobs WHERE url='dead'").fetchone()
assert (_dead["status"], _dead["note"]) == ("skipped", "closed on the board"), tuple(_dead)
# an application already sent must never be rewritten by this
_sent = _c.execute("SELECT status, applied_at FROM jobs WHERE url='sent'").fetchone()
assert _sent["status"] == "applied" and _sent["applied_at"], tuple(_sent)

# 1u. "Closed" and "applies on the employer's own site" look identical to apply_control - it
# finds nothing either way, because the external control is deliberately NOT matched: clicking
# it leads to an arbitrary careers system. Telling them apart is what keeps live external ads
# from being hidden as dead ones.
_ej = _pf.BOARD_UI["ejobs"]
assert not _re.search(_ej["apply"], "aplică extern"), "must not be clicked as a one-click apply"
assert _re.search(_ej["external"], "aplică extern"), "but must be recognised as live"
assert _re.search(_ej["apply"], "aplică") and _re.search(_ej["apply"], "aplică rapid")
assert not _re.search(_ej["external"], "aplică")        # a plain apply is not an external one
assert _pf.BOARD_UI["hipo"].get("external"), "hipo hands off too, via redirectAnuntExtern"

# 1v. A "signed out" verdict is checked twice. Boards keep a short-lived token beside a
# long-lived one - eJobs' access token lasts about an hour against a 400-day refresh token - and
# renew it with a request the page makes after it loads, so reading the body too early condemns
# a session that is about to renew itself. That verdict now raises an alert and makes the weekly
# run send nothing, so it has to be right.
class _FakePage:
    def __init__(self, bodies): self.bodies, self.loads, self.url = list(bodies), 0, "https://x/"
    def goto(self, url, **k): self.loads += 1; self.url = url
    def wait_for_timeout(self, ms): pass
    def inner_text(self, sel): return self.bodies[min(self.loads - 1, len(self.bodies) - 1)]
    def query_selector_all(self, sel): return []
    def query_selector(self, sel): return None
_OUT, _IN = "intră în contul tău", "cv-ul meu aplicările mele"
_p = _FakePage([_OUT, _OUT])
assert _pf._probe_signed_in(_p, "ejobs") is False and _p.loads == 2   # one retry, then it stops
_p = _FakePage([_OUT, _IN])
assert _pf._probe_signed_in(_p, "ejobs") is True and _p.loads == 2    # renewed on the second look
_p = _FakePage([_IN])
assert _pf._probe_signed_in(_p, "ejobs") is True and _p.loads == 1    # healthy costs one load

# 1w. The keep-signed-in switch lives in the sign-in panel, not the weekly one, and its key does
# not start with auto_ - so it has to be let through /api/auto explicitly and saved on its own.
# Without either, ticking it looked like it worked and changed nothing.
import inspect as _i3
_src = _i3.getsource(app.get_auto)
assert 'k == "keep_signed_in"' in _src, "get_auto must return the switch, or it draws unticked"
assert "keep_signed_in" in _i3.getsource(app.set_auto), "set_auto must accept it"
assert "keep_signed_in" in _i3.getsource(app.keep_signed_in)
assert app.KEEP_HOURS * 3600 < 6 * 3600, "must touch more often than Hipo's ~6h session"

# 1x. A model that wraps its one answer in a list cost a whole job on the 144-ad run
# ("score returned list, not an object"), and nothing re-scores it afterwards.
import inspect as _i4
_ssrc = _i4.getsource(app.search)
assert "isinstance(s, list) and len(s) == 1" in _ssrc, "a single-item list must be unwrapped"
# and the prompt now asks for plain text, because the markdown is what breaks the JSON
assert "no markdown" in _i4.getsource(app.llm.score)

# 1y. The real scoring loop, driven end to end. The unit test above only covers the arithmetic,
# and the wiring underneath it was wrong once already: ask() recovers from a quota refusal by
# moving down the chain, so the loop saw no exception and never backed off. Network and model are
# stubbed and the database is a throwaway, so this costs nothing.
import asyncio as _asyncio, io as _io, contextlib as _ctx, tempfile as _tmp
_realdb, _realdone = app.DB, app._SCHEMA_DONE
_real = (scrape.discover, scrape.hydrate, app.llm.score, app.llm.language_gate,
         app.llm.ad_language)
try:
    app.DB, app._SCHEMA_DONE = pathlib.Path(_tmp.mkdtemp()) / "t.sqlite", False
    with app.db() as _c:
        for _n in range(40):
            _c.execute("INSERT INTO jobs(url,source,title,company,location,posted,description,"
                       "status,note,lang) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (f"https://www.ejobs.ro/user/locuri-de-munca/x/{_n}", "ejobs", f"Job {_n}",
                        "ACME", "Bucuresti", "2026-09-28", "long enough to score " * 12,
                        "new", "", "en"))
    scrape.discover = lambda *a, **k: []
    scrape.hydrate = lambda jobs, **k: []
    app.llm.language_gate = lambda p, j: (True, "")
    app.llm.ad_language = lambda j: "en"
    _calls = {"n": 0}
    def _fake_score(profile, job):
        _calls["n"] += 1
        if 7 <= _calls["n"] <= 18:                  # a stretch of refusals, then recovery
            app.llm.QUOTA_EVENTS.append("test")     # ask() recovers; the provider still refused
        return {"fit": 70, "why": "ok", "gaps": [], "untapped": []}
    app.llm.score = _fake_score
    _buf = _io.StringIO()
    with _ctx.redirect_stdout(_buf):
        _out = _asyncio.run(app.search({"query": "x", "country": "ro"}))
    _moves = [l for l in _buf.getvalue().splitlines() if l.startswith("[score]")]
    assert _moves, "the width never moved - the loop is not reacting to refusals"
    assert any("6 -> 3" in l for l in _moves), _moves      # halves when refused
    assert any("keeping up" in l for l in _moves), _moves  # widens again afterwards
    assert _out["scored"] == 40, f"every row must still be scored, got {_out['scored']}"
finally:
    app.DB, app._SCHEMA_DONE = _realdb, _realdone
    (scrape.discover, scrape.hydrate, app.llm.score, app.llm.language_gate,
     app.llm.ad_language) = _real
    app.llm.QUOTA_EVENTS.clear()

# 1z. A .docx laid out in a table - which is how a great many CVs are written - gave up only the
# name, because python-docx's `paragraphs` never descends into tables. The profile was then built
# from a name and nothing else, silently, and every job after that was scored against it.
import io as _io3, docx as _docx
_d = _docx.Document()
_d.add_paragraph("Razvan Vuicin")
_t = _d.add_table(rows=2, cols=2)
_t.cell(0, 0).text = "2020 - 2024"
_t.cell(0, 1).text = "Team Leader at ACME"
_t.cell(1, 0).text = "2018 - 2020"
_t.cell(1, 1).text = "Support Agent at Contoso"
_b = _io3.BytesIO(); _d.save(_b)
_txt = app._cv_text("cv.docx", _b.getvalue())
assert "ACME" in _txt and "Contoso" in _txt, _txt
assert "2020 - 2024  Team Leader at ACME" in _txt, "a date must stay beside its role"
# a Word 97 .doc decoded as text gives ~170 chars of binary noise - long enough to pass the
# "did we read anything" check and be parsed as a CV. It is refused, by signature as well as
# by extension, so renaming it does not get it through.
from fastapi import HTTPException as _HE
for _name in ("cv.doc", "cv.txt"):
    try:
        app._cv_text(_name, bytes.fromhex("d0cf11e0a1b11ae1") + b"noise" * 40)
        raise AssertionError(f"{_name}: a Word 97 file must be refused, not parsed")
    except _HE:
        pass

# 2a. suggest() is handed what employers in the candidate's own results kept asking for. Showing
# a model a list of wanted skills is exactly how a CV grows things the candidate cannot defend in
# an interview, so the no-invention rule names that list specifically, and an empty market must
# leave the prompt completely unchanged rather than mentioning an empty list.
import inspect as _i5
_ssrc3 = _i5.getsource(app.llm.suggest)
assert "say NOTHING about it" in _ssrc3, "the rule against adding missing skills must be explicit"
assert "market[:15]" in _ssrc3, "the list has to be capped"
assert 'demand = ""' in _ssrc3, "no market means no extra prompt at all"
# and the endpoint only passes things more than one ad asked for
assert 'g["jobs"] > 1' in _i5.getsource(app.suggestions)

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
