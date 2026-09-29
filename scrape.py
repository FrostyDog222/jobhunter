"""Job scraping. Every serious board emits schema.org JobPosting JSON-LD for Google Jobs,
so one generic extractor covers them all - a new board is one entry in BOARDS."""
import datetime, functools, html, json, random, re, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
import httpx
from urllib.parse import unquote, urlsplit

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8"}

BOARDS = {
    # name: (listing url template, regex finding job-detail paths in the listing html)
    "ejobs": ("https://www.ejobs.ro/locuri-de-munca/{loc}{q}",
              r'(/user/locuri-de-munca/[a-z0-9-]+/\d+)'),
    # Hipo's own search form POSTs to /cautajob and lands on this path. The shorter
    # /cautajob/{q} looks like a search and is not: it returns the same default 40 ads whatever
    # you type, which is why every Hipo row in this app used to be unrelated to the query.
    "hipo": ("https://www.hipo.ro/locuri-de-munca/cautajob/Toate-Domeniile/{loc}/{q}/",
             r'href="(/locuri-de-munca/locuri_de_munca/[^"]+)"'),
    # neither board paginates server-side: page 2 returns page 1, so ~40 per query is the ceiling.
    # bestjobs.eu is a client-rendered SPA with no server-side JSON-LD -> would need a
    # browser + hand-written selectors. Left out until the two above stop being enough.
}
BASE = {"ejobs": "https://www.ejobs.ro", "hipo": "https://www.hipo.ro"}
# BOARDS are HTML boards scraped via JSON-LD; freehire and bestjobs are JSON APIs, each handled
# separately below.
SOURCES = ["freehire", "bestjobs"] + list(BOARDS)

BESTJOBS = "https://api.bestjobs.eu/v1/jobs"
BESTJOBS_AD = "https://www.bestjobs.eu/loc-de-munca/{slug}"

# bestjobs renders its own markup and emits no JSON-LD, but the ad body sits in one predictable
# block with nothing nested inside it, so a single pattern replaces a hand-written parser.
DESC = {"bestjobs": re.compile(r'<div class="[^"]*job-description[^"]*"[^>]*>(.*?)</div>', re.S),
        # eJobs splits an ad into sections and puts only the first in its JSON-LD. The rest -
        # "Candidatul ideal", where the requirements and language demands are - is markup only.
        "ejobs": re.compile(r'<div class="jobs-show-main-description__section">(.*?)</div>', re.S)}


# A posting that hands the application to the employer's own website. Hipo writes it straight
# into the href, so reading the page once at search time settles it - no browser, no attempt,
# and the "you apply yourself" list is right before anything is clicked.
GOES_EXTERNAL = re.compile(r"redirectAnuntExtern", re.I)
EXTERNAL_NOTE = "apply on the employer site"


def _markup(source, page):
    """The ad body from the board's own markup, every section of it, or ""."""
    pat = DESC.get(source)
    return "\n\n".join(t for t in (_text(x) for x in pat.findall(page)) if t) if pat else ""


def _ld_body(jp):
    """The ad body from JSON-LD. Hipo puts the company blurb in `description` and the actual
    duties and requirements in the fields beside it, repeating one text under several names."""
    parts = (_text(v) for v in map(jp.get, ("description", "responsibilities", "qualifications"))
             if isinstance(v, str) and v.strip())
    return "\n\n".join(dict.fromkeys(t for t in parts if t))


def _bj_pay(text):
    """BestJobs writes pay as a bare "960 - 1060". Give it the currency and period it means.

    The API has no currency field; the site prints these ranges in EUR per month and has done
    for as long as this has been checked. Saying so beats printing a naked number next to
    eJobs' "4000 - 5000 RON/month", which is how a 960 looked like the smaller offer.
    """
    t = _clean(text)
    return f"{t} EUR/month" if t and re.fullmatch(r"[\d][\d\s.,-]*", t) else t


def bestjobs(query, limit=25, timeout=30):
    """The #2 Romanian board. Its site is a client-rendered SPA with no JSON-LD, but the API the
    SPA itself calls is public and unauthenticated. It answers 100 rows in one request and ignores
    `page`, so 100 per query is the ceiling - still more than eJobs' 40. No description and no
    posting date in the response, so these go through phase 2 like any HTML board.

    It also answers three things no other source here gives, and all three were being dropped:
    how many people have already applied, the employer's own salary as distinct from the board's
    estimate of it, and whether Apply leaves the board for the employer's own site.
    """
    with httpx.Client(headers={**UA, "Accept": "application/json"}, timeout=timeout) as c:
        r = _get(c, httpx.URL(BESTJOBS, params={"keyword": (query or "").translate(DIACRITICS)}))
        r.raise_for_status()
        items = r.json().get("items") or []
    jobs = []
    for j in items:
        slug = (j.get("slug") or "").strip()
        if not slug or j.get("state") not in (None, "active"):
            continue
        flags = []
        if j.get("hasOwnApplyUrl"):
            flags.append("applies on the employer site")
        jobs.append({
            "source": "bestjobs",
            "url": BESTJOBS_AD.format(slug=slug),
            "title": _clean(j.get("title")),
            "company": _clean(j.get("companyName")),
            "location": ", ".join(_clean(l.get("name")) for l in (j.get("locations") or [])),
            "posted": "",                       # the list carries no date; the ad page shows none either
            "description": "",
            # the employer's own figure ONLY. estimatedSalary is BestJobs' guess for an ad that
            # states no pay, and merging the two printed a guess on the card as if the employer
            # had said it - which is the number someone then repeats in a screening answer.
            "salary": _bj_pay(j.get("salary")),
            "pay_est": _bj_pay(j.get("estimatedSalary")) if not _clean(j.get("salary")) else "",
            # How many people you are up against. The one number here that decides whether an
            # application is worth the half hour it takes to tailor a CV for it.
            "applicants": int(j["applications"]) if isinstance(j.get("applications"), int) else None,
            "note": " · ".join(flags),
            "lang": "",
            "_full": False,
        })
    # ...and only now the limit, so the choice below is made over everything the board returned
    return _bj_pick(jobs, limit)


def _bj_pick(jobs, limit):
    """-> which of the 100 to spend phase 2 and a model call on.

    One request brings back 100 and the app used to keep whichever 20 came first. Half the budget
    still goes to the board's own order, which is its relevance ranking and must not be lost; the
    other half goes to the least crowded of what is left. Measured on one live query: the first
    20 have a median of 128 applicants, the least crowded 20 a median of 21, and the two sets
    share only 4 ads - so the old slice was not seeing 16 of the least contested jobs at all.
    """
    limit = max(int(limit or 0), 0)
    if len(jobs) <= limit:
        return jobs
    keep = jobs[:limit // 2]
    seen = {j["url"] for j in keep}
    rest = sorted((j for j in jobs if j["url"] not in seen),
                  key=lambda j: (j["applicants"] is None, j["applicants"] or 0))
    return keep + rest[:limit - len(keep)]


# Both boards slug their URLs without diacritics, so transliterate rather than treating every
# accented letter as a separator. NFKD alone leaves s-comma and t-comma intact, hence the map.
DIACRITICS = str.maketrans({"ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
                            "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t"})


def _slug(text):
    flat = unicodedata.normalize("NFKD", (text or "").lower().translate(DIACRITICS))
    flat = flat.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", flat).strip("-")


def _url(board, query, location):
    tpl = BOARDS[board][0]
    q, loc = _slug(query), _slug(location)
    if board == "hipo":
        # hipo wants a city segment either way, and has its own word for "everywhere"
        return tpl.format(q=q or "-", loc=loc.title() if loc else "Toate-Orasele")
    return tpl.format(q=q, loc=f"{loc}/" if loc else "")


def _get(c, url, tries=5, _sleep=time.sleep):
    """Retry only what is worth retrying: 429 and 5xx are hiccups, 403/404 are answers.
    Exponential backoff capped at 5s, with jitter so parallel callers do not resynchronise."""
    for attempt in range(tries):
        r = c.get(url)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
            _sleep(min(0.5 * 2 ** attempt, 5.0) + random.random() * 0.5)
            continue
        return r
    return r


def _find_jobposting(node, depth=0):
    """Recurse: JSON-LD nests JobPosting under @graph, inside arrays, or under mainEntity
    depending on which SEO plugin produced it."""
    # Real nesting is two or three deep. A page with hundreds raised RecursionError, and hydrate
    # only catches httpx errors - so one hostile page lost every job in the run, not just itself.
    if depth > 12:
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_jobposting(item, depth + 1)
            if found:
                return found
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                found = _find_jobposting(node[key], depth + 1)
                if found:
                    return found
    return None


# BestJobs' list API gives a bare "1135 - 1255"; only the ad page says what that means, and it
# says it more than once - the similar-jobs rail carries other people's numbers without a unit.
# The ad's own figure is the one that names a currency.
SALARY = re.compile(r'"estimatedSalary"\s*:\s*"([^"]{1,40})"')
CURRENCY = re.compile(r"eur|ron|lei|€", re.I)


def _salary(page):
    """-> the ad's own pay, with its unit, or "" when the ad does not say.

    A figure, never prose. Without this "negociabil, lei la interviu" and "confidential - EUR"
    both reached the salary pill, which is worse than showing nothing - the same reason _pay
    checks. Known limit: the first currency-bearing hit wins, and on a page whose similar-jobs
    rail is serialised before the ad itself that is the wrong job's number. JSON-LD is tried
    first by the caller, which is where the ads that matter carry it.
    """
    for hit in SALARY.findall(page or ""):
        if CURRENCY.search(hit) and re.search(r"\d", hit):
            money = _clean(hit)
            if re.fullmatch(r"[\d][\d\s.,/-]*(?:[A-Za-z\u20ac/ ]{0,12})", money):
                return money
    return ""


# schema.org units, as the boards actually write them.
UNIT = {"HOUR": "hour", "DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}


def _pay(jp):
    """'4000 - 5000 RON/month' from schema.org baseSalary, or "" when the ad does not say.

    Both eJobs and Hipo publish this - measured, 4 ads in 10 carry it - and neither repeats it
    in the ad text, so it was the one hard number on the page that never reached the dashboard.
    """
    b = jp.get("baseSalary")
    if not isinstance(b, dict):
        return ""
    val = b.get("value")
    if isinstance(val, list):                    # schema.org allows a list here
        val = next((x for x in val if isinstance(x, dict)), {})
    v = val if isinstance(val, dict) else {}

    def num(x):
        """'4000', 4000, 4000.0 -> '4000'. A JSON float printed as '4000.0 - 5000.0 RON'."""
        if x is None or isinstance(x, bool) or (isinstance(x, str) and not x.strip()):
            return ""
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x).strip()

    lo, hi = num(v.get("minValue")), num(v.get("maxValue"))
    # a reversed range is the employer's typo, not ours to repeat
    try:
        if lo and hi and float(lo.replace(" ", "")) > float(hi.replace(" ", "")):
            lo, hi = hi, lo
    except ValueError:
        pass
    amount = f"{lo} - {hi}" if lo and hi and lo != hi else (lo or hi or num(v.get("value")))
    # a figure, not prose: anything else here is a field we have misread, and a wrong number on
    # a salary pill is worse than no pill
    if not amount or not re.fullmatch(r"[\d][\d\s.,-]*", amount):
        return ""
    # _flat, not str(): currency arrives as {"name": "RON"} often enough to matter, and str()
    # printed the dict
    cur = _flat(b.get("currency") or v.get("currency") or "")
    unit = UNIT.get(str(v.get("unitText") or "").upper(), "")
    return " ".join(x for x in (amount, cur) if x) + (f"/{unit}" if unit else "")


# FULL_TIME is what nearly every ad says, and repeating it on every card is noise. The rest
# change whether the job is worth an application at all.
TERMS = {"PART_TIME": "part time", "TEMPORARY": "temporary", "CONTRACTOR": "contract",
         "INTERN": "internship", "INTERNSHIP": "internship", "VOLUNTEER": "volunteer",
         "PER_DIEM": "per diem", "SEASONAL": "seasonal"}


def _years(months):
    """'wants 2+ years' - the phrasing a person scanning a card can act on."""
    if isinstance(months, bool):
        return ""                       # True is an int, and "wants 1+ months" is not a fact
    if isinstance(months, str):
        m = re.match(r"\s*(\d{1,4})", months)      # "24 months" is a real value in the wild
        months = m.group(1) if m else None
    try:
        months = int(months)
    except (TypeError, ValueError):
        return ""
    if months > 60 * 12:
        return ""                       # "wants 50000+ years" was a real output of this

    if months >= 12:
        y = months // 12
        return f"wants {y}+ year" + ("s" if y > 1 else "")
    return f"wants {months}+ months" if months > 0 else ""


def _terms(jp):
    """The deal in a few words: anything other than a normal full-time job, plus the experience
    the ad asks for. Both sit in the ad's own structured data and neither was ever shown, so an
    internship looked exactly like a permanent role on the dashboard."""
    raw = jp.get("employmentType")
    out = []
    for t in (raw if isinstance(raw, list) else [raw]):
        # {"@type": "DefinedTerm", "name": "INTERN"} is a shape schema.org allows, and it was
        # coming back empty - which is exactly the "an internship looked like a permanent role"
        # case this function exists to stop
        if isinstance(t, dict):
            t = t.get("name") or t.get("value") or ""
        word = TERMS.get(str(t or "").strip().upper().replace(" ", "_").replace("-", "_"), "")
        if word and word not in out:
            out.append(word)
    exp = jp.get("experienceRequirements")
    if isinstance(exp, list):
        exp = next((x for x in exp if isinstance(x, dict)), None)
    yrs = _years(exp.get("monthsOfExperience")) if isinstance(exp, dict) else ""
    if yrs:
        out.append(yrs)
    return " · ".join(out)


def _jobposting(page_html):
    """Pull the JobPosting node out of any ld+json block on the page."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S):
        raw = block.strip()
        data = None
        for attempt in (raw, html.unescape(raw)):
            # The raw text FIRST. html.unescape on the whole block turns &quot; inside a JSON
            # string into a bare quote, which ends the string and breaks the document - so an ad
            # that merely wrote "atentie la detalii" in quotes lost its salary, its dates, its
            # company and its closing date. Unescaping is the fallback for the boards that
            # really do double-encode, not the first move.
            try:
                data = json.loads(attempt)
                break
            except json.JSONDecodeError:
                continue      # a malformed block must not stop us checking the later ones
        if data is None:
            continue
        found = _find_jobposting(data)
        if found:
            return found
    return None


def _fix(s):
    """hipo.ro serves UTF-8 that was already UTF-8 encoded once, so Romanian diacritics arrive as
    'Ã®' or 'Ä'. A marker list kept missing cases, so test the round trip instead: natural text
    in the Latin-1 range almost never forms a valid UTF-8 sequence, while mojibake always does -
    'PeÃ±a' decodes, 'Peña' raises and is left alone."""
    if not s or not any("" <= ch <= "ÿ" for ch in s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _clean(s):
    """Entities and mojibake both reach us through titles and companies, not just descriptions.

    Unescaped until it stops changing, because some ads are encoded twice: "T&amp;amp;D Manager"
    needs two passes and one pass leaves "T&amp;D" on the card. Bounded at three so a literal
    "&amp;amp;" that someone genuinely typed cannot loop.
    """
    out = s or ""
    for _ in range(3):
        once = html.unescape(out)
        if once == out:
            break
        out = once
    return _fix(out).strip()


def _text(h):
    return re.sub(r"\n{3,}", "\n\n", _clean(re.sub(r"<[^>]+>", "\n", h or "")))


def _place(s):
    """'BUCURESTI, ' -> 'Bucuresti'. Boards shout their cities and leave separators behind."""
    s = (s or "").strip(" ,")
    return s.title() if s.isupper() else s


def _flat(v):
    """schema.org fields are wildly inconsistent - squash to a plain string."""
    if isinstance(v, dict):
        for k in ("name", "addressLocality", "addressRegion", "address", "value"):
            if k in v:
                return _flat(v[k])
        return ""
    if isinstance(v, list):
        return ", ".join(x for x in (_flat(i) for i in v) if x)
    return _clean(str(v or ""))


def _safe_url(url, fallback=""):
    """A stored url later decides where a real browser navigates, so reject anything whose
    authority is ambiguous. Python ends the authority at a backslash and Chromium does not, so
    "https://evil.com\\@boards.greenhouse.io/x" reads as greenhouse.io here and loads evil.com
    there; userinfo plays the same trick."""
    url = (url or "").strip()
    if (not url.lower().startswith(("http://", "https://"))
            or "\\" in url or "@" in urlsplit(url).netloc):
        return fallback
    return url


FREEHIRE = "https://freehire.me/api/v1/agent/jobs/search"


WORLDWIDE = ("", "*", "any", "world", "worldwide")

# freehire exposes 24 facets; these are the ones worth a control in the UI. Notably `reality`:
# roughly three quarters of the index is stale, so filtering to fresh is the single biggest
# quality win available. `auto_apply_available` is true exactly when the posting lives on a
# standard ATS (greenhouse/lever/ashby/workable), i.e. a predictable application form.
FILTERS = ("reality", "work_mode", "seniority", "employment_type", "posting_language",
           "english_level", "category", "experience_years_max", "auto_apply_available",
           "visa_sponsorship", "company_type", "skills")


def freehire(query, country="ro", limit=25, timeout=30, filters=None):
    """freehire.me is a public REST API, not a page to scrape: full descriptions inline, an
    ISO-3166 country filter, and per-posting freshness/quality flags the HTML boards do not have.
    Set country to "" to search worldwide."""
    country = "" if (country or "").strip().lower() in WORLDWIDE else country.strip().lower()
    limit = max(int(limit or 0), 0)
    if not limit:
        return []
    params = {"q": query, "limit": min(limit, 100)}
    page_size = params["limit"]
    if country:
        params["countries"] = country
    for k, v in (filters or {}).items():
        if k in FILTERS and str(v).strip():
            params[k] = v
    data = []
    with httpx.Client(headers=UA, timeout=timeout) as c:
        for offset in range(0, max(limit, 1), page_size):     # freehire pages; the HTML boards do not
            r = _get(c, httpx.URL(FREEHIRE, params={**params, "offset": offset}))
            r.raise_for_status()
            page = r.json().get("data") or []
            data += page
            if len(page) < page_size:
                break
    data = data[:limit]

    jobs = []
    for j in data:
        if j.get("closed_at"):
            continue
        # the API ORs geography, so a countries=ro query also returns neighbours - keep our own filter
        if country and country not in [x.lower() for x in (j.get("countries") or [])]:
            continue
        reality, enr = j.get("reality") or {}, j.get("enrichment") or {}
        flags = [f for f in (
            reality.get("class") if reality.get("class") in ("stale", "old") else None,
            f"reposted x{reality['repost_count']}" if reality.get("repost_count", 0) > 1 else None,
            "mass posting" if reality.get("mass_posting_count", 0) > 1 else None,
            "suspicious freshness" if reality.get("fake_freshness") else None,
        ) if f]
        url = _safe_url(j.get("url"), f"https://freehire.me/jobs/{j.get('public_slug','')}")
        jobs.append({
            "source": "freehire",
            "url": url,
            "title": _clean(j.get("title")),
            "company": _flat(j.get("company")),
            "location": j.get("location") or ", ".join(j.get("cities") or []),
            "posted": (j.get("posted_at") or "")[:10],
            "description": _text(j.get("description")),
            "note": " · ".join(flags),
            "lang": enr.get("posting_language") or "",
            # freehire's own wording for the two facts the HTML boards put in JSON-LD
            "terms": " · ".join(x for x in (
                (enr.get("employment_type") or "").replace("_", " ")
                if (enr.get("employment_type") or "") not in ("", "full_time") else "",
                _years((enr.get("experience_years_min") or 0) * 12)) if x),
        })
    return jobs


def health(source, jobs, seen_before):
    """Scrapers rot silently: a portal changes its markup and the parser still exits cleanly with
    zero rows or blank fields. Returns a complaint string, or "" when the source looks fine.
    The empty case is not here: the caller checks it at phase 1, against what the board
    actually returned, because by the time these rows exist "nothing" and "nothing NEW" look
    identical and the second one is the normal result of searching twice."""
    if not jobs:
        return ""
    blank = lambda k: sum(1 for j in jobs if not (j.get(k) or "").strip()) == len(jobs)
    if blank("title"):
        return f"{source}: every title empty - parser broken"
    if blank("company"):
        return f"{source}: every company empty - parser broken"
    if any("&amp;" in (j.get("title") or "") or "<" in (j.get("title") or "") for j in jobs):
        return f"{source}: HTML fragments in titles - entities not decoded"
    return ""


# hipo lists career-fair events alongside real vacancies - "Workshop by BAT Romania @ Top
# Talents", "Conferinta gratuita de dezvoltare personala" and friends. They are not jobs, they
# never score, and they crowd out the rest.
#
# An event ANNOUNCES itself: the title OPENS with the word. A job only mentions it in passing,
# and matching the bare word dropped every one of those - "Specialist Webinar Marketing",
# "Tehnician Workshop De Reparatii" and "Organizator Conferinta Medicala" are real vacancies
# that nobody would ever have seen. The roles that genuinely open with the word are named,
# because "Workshop Manager" starts exactly the way "Workshop inspirational - ..." does.
ROLE = (r"manager|technician|tehnician|supervisor|coordinator|lead|specialist|operator|sef"
        r"|\u0219ef|responsabil|assistant|asistent|engineer|inginer|administrator|director"
        r"|consultant|analyst|analist|planner|organizator|designer|developer")
NOISE = re.compile(r"@\s*top\s+talents"
                   r"|\b(workshop|webinar|masterclass)\s+(by|with|cu)\b"
                   rf"|^\s*(workshop|webinar|masterclass|conferint\w*|seminar)\b(?!\s+({ROLE}))"
                   r"|^\s*training\s+(by|with|de|cu)\b"
                   rf"|\b(career fair|job fair|zilele carierei|t[a\u00e2]rg de (joburi|cariere))\b"
                   rf"(?!\s+({ROLE}))", re.I)


def _slug_title(path):
    """A board's own URL carries the job title, which is enough to dedupe and pre-filter on
    before deciding whether the detail page is worth a request."""
    seg = [s for s in path.split("/") if s and not s.isdigit()]
    # the path is url-encoded html, so it carries &amp; and %C4%83 through to the title
    return _clean(unquote(re.sub(r"[-_]+", " ", seg[-1]))).strip().title() if seg else ""



# Romania's 41 counties and Bucharest. Each entry is (display name, towns whose ads should count
# as that county) - the county seat first, then the other towns that actually turn up in job ads.
#
# This exists because the boards disagree about what a location IS. eJobs takes a county slug and
# filters on it properly. Hipo takes CITY names: "Cluj-Napoca" filters, "Cluj" is ignored and it
# returns the whole country instead, silently - measured, not assumed. So a county is sent to the
# boards (it helps where it is understood) AND the ads that come back are checked here, which is
# the only part that holds for every board.
COUNTIES = {
    "alba": ("Alba", ("Alba Iulia", "Sebes", "Aiud", "Cugir", "Blaj")),
    "arad": ("Arad", ("Arad", "Ineu", "Lipova", "Chisineu-Cris")),
    "arges": ("Argeș", ("Pitesti", "Mioveni", "Campulung", "Curtea de Arges")),
    "bacau": ("Bacău", ("Bacau", "Onesti", "Moinesti", "Comanesti")),
    "bihor": ("Bihor", ("Oradea", "Salonta", "Marghita", "Beius")),
    "bistrita-nasaud": ("Bistrița-Năsăud", ("Bistrita", "Nasaud", "Beclean")),
    "botosani": ("Botoșani", ("Botosani", "Dorohoi")),
    "braila": ("Brăila", ("Braila", "Ianca")),
    "brasov": ("Brașov", ("Brasov", "Fagaras", "Sacele", "Codlea", "Zarnesti", "Ghimbav")),
    "bucuresti": ("București", ("Bucuresti", "Bucharest")),
    "buzau": ("Buzău", ("Buzau", "Ramnicu Sarat")),
    "calarasi": ("Călărași", ("Calarasi", "Oltenita")),
    "caras-severin": ("Caraș-Severin", ("Resita", "Caransebes")),
    "cluj": ("Cluj", ("Cluj-Napoca", "Turda", "Dej", "Campia Turzii", "Gherla", "Floresti")),
    "constanta": ("Constanța", ("Constanta", "Mangalia", "Medgidia", "Navodari", "Cernavoda")),
    "covasna": ("Covasna", ("Sfantu Gheorghe", "Targu Secuiesc", "Covasna")),
    "dambovita": ("Dâmbovița", ("Targoviste", "Moreni", "Pucioasa")),
    "dolj": ("Dolj", ("Craiova", "Bailesti", "Calafat")),
    "galati": ("Galați", ("Galati", "Tecuci")),
    "giurgiu": ("Giurgiu", ("Giurgiu", "Bolintin-Vale")),
    "gorj": ("Gorj", ("Targu Jiu", "Motru", "Rovinari")),
    "harghita": ("Harghita", ("Miercurea Ciuc", "Odorheiu Secuiesc", "Gheorgheni", "Toplita")),
    "hunedoara": ("Hunedoara", ("Deva", "Hunedoara", "Petrosani", "Orastie", "Simeria")),
    "ialomita": ("Ialomița", ("Slobozia", "Fetesti", "Urziceni")),
    "iasi": ("Iași", ("Iasi", "Pascani", "Targu Frumos")),
    "ilfov": ("Ilfov", ("Voluntari", "Popesti-Leordeni", "Buftea", "Otopeni", "Pantelimon",
                        "Bragadiru", "Chitila", "Magurele", "Chiajna", "Mogosoaia")),
    "maramures": ("Maramureș", ("Baia Mare", "Sighetu Marmatiei", "Borsa", "Viseu de Sus")),
    "mehedinti": ("Mehedinți", ("Drobeta-Turnu Severin", "Orsova")),
    "mures": ("Mureș", ("Targu Mures", "Reghin", "Sighisoara", "Ludus")),
    "neamt": ("Neamț", ("Piatra Neamt", "Roman", "Targu Neamt")),
    "olt": ("Olt", ("Slatina", "Caracal", "Bals")),
    "prahova": ("Prahova", ("Ploiesti", "Campina", "Baicoi", "Mizil", "Sinaia", "Busteni")),
    "salaj": ("Sălaj", ("Zalau", "Simleu Silvaniei", "Jibou")),
    "satu-mare": ("Satu Mare", ("Satu Mare", "Carei", "Negresti-Oas")),
    "sibiu": ("Sibiu", ("Sibiu", "Medias", "Cisnadie", "Avrig")),
    "suceava": ("Suceava", ("Suceava", "Falticeni", "Radauti", "Campulung Moldovenesc")),
    "teleorman": ("Teleorman", ("Alexandria", "Rosiori de Vede", "Turnu Magurele")),
    "timis": ("Timiș", ("Timisoara", "Lugoj", "Sannicolau Mare", "Jimbolia", "Dumbravita",
                        "Giroc", "Ghiroda")),
    "tulcea": ("Tulcea", ("Tulcea", "Macin", "Babadag")),
    "valcea": ("Vâlcea", ("Ramnicu Valcea", "Dragasani", "Balcesti")),
    "vaslui": ("Vaslui", ("Vaslui", "Barlad", "Husi")),
    "vrancea": ("Vrancea", ("Focsani", "Adjud", "Marasesti")),
}


# Every county name, its slug and its towns, as compiled patterns - built once. This used to be
# rebuilt inside in_county on every call: 240 re.escape calls and 240 f-strings per row, which
# is 265 ms for a 600-row dashboard, on the one request that has to feel instant.
_NAMES = [(re.compile(rf"(^|-){re.escape(_n)}($|-)"), len(_n), _slug_key)
          for _slug_key, (_display, _towns) in COUNTIES.items()
          for _n in {_slug(x) for x in (_display, _slug_key, *_towns) if _slug(x)}]


@functools.lru_cache(maxsize=4096)
def in_county(text, county):
    """Does this ad's location sit in that county? Diacritics are folded on both sides, because
    half the boards write "Timisoara" and half write "Timișoara", and people type either.

    Cached: a job list is a few dozen distinct locations repeated, and the county table does not
    change while the app is running.
    """
    entry = COUNTIES.get((county or "").lower())
    if not entry:
        return True                       # not a county we know - do not silently drop the ad
    flat = _slug(text)
    if not flat:
        # An ad that names no location cannot be confirmed local - but it cannot be called far
        # away either, so callers asking "is this out of reach" must treat it as unknown.
        return False
    # A remote job is open to someone in any county, and the boards pad their county pages with
    # them - dropping those would have thrown away the roles that suit a county search best.
    if re.search(r"(^|-)(remote|telemunca|munca-de-acasa|work-from-home|anywhere"
                 r"|toata-tara|nationwide|hybrid|hibrid)($|-)", flat):
        return True
    # "Romania" alone means the whole country; as a suffix it is just the postal address, and
    # most ads carry it. Treating the suffix as nationwide marked every job in the country
    # reachable from every county.
    bare = re.sub(r"(^|-)(romania|national)($|-)", "-", flat).strip("-")
    if not bare:
        return True
    # Every place name that appears, with where it appears. An ad naming several towns is open
    # in all of them, so this cannot pick a single winner - but a short name sitting INSIDE a
    # longer one is not a match at all: "Campulung Moldovenesc" is in Suceava and contains
    # Arges's "Campulung", "Turnu Magurele" is in Teleorman and contains Ilfov's "Magurele".
    # Both used to report the wrong county, which shows a job as near when it is hours away.
    hits = []
    for rx, width, slug in _NAMES:
        for m in rx.finditer(flat):
            hits.append((m.start(1), m.start(1) + width + 1, slug))
    want = (county or "").lower()
    for start, end, slug in hits:
        if slug != want:
            continue
        # shadowed by a longer name that covers the same words?
        if any(o_start <= start and end <= o_end and (o_end - o_start) > (end - start)
               for o_start, o_end, o_slug in hits if o_slug != want):
            continue
        return True
    return False


def discover(board, query, location="", limit=25, timeout=30, country="ro", filters=None):
    """Phase 1, cheap: one request per board, returning candidate urls with a slug-derived title.
    freehire answers in full from its API, so it needs no second phase at all."""
    if board == "freehire":
        jobs = freehire(query, country, limit, timeout, filters)
        for j in jobs:
            j["_full"] = True
        return jobs
    if board == "bestjobs":
        return bestjobs(query, limit, timeout)

    base, (tpl, pat) = BASE[board], BOARDS[board]
    with httpx.Client(headers=UA, follow_redirects=True, timeout=timeout) as c:
        listing = _get(c, _url(board, query, location))
        listing.raise_for_status()
        # hrefs come out of raw html, so &amp; must be undone before the url is stored
        paths = list(dict.fromkeys(html.unescape(p) for p in re.findall(pat, listing.text)))[:limit]
    # drop event listings here, before phase 2 spends a request on each of them
    return [{"source": board, "url": p if p.startswith("http") else base + p,
             "title": t, "company": "", "location": "", "posted": "",
             "description": "", "note": "", "salary": "", "lang": "", "_full": False}
            for p, t in ((p, _slug_title(p)) for p in paths) if not NOISE.search(t)]


# below this many characters an "ad" is a stub: a title, a company and no requirements
MIN_AD = 200

# An ad this old is filled, withdrawn or being ignored by the employer. Applying to it wastes an
# application; keeping it wastes a scoring call and a row on the dashboard. Undated ads are kept,
# because "no date" is not "old" - BestJobs publishes no posting date at all.
MAX_AGE_DAYS = 14


def _too_old(posted):
    try:
        return (datetime.date.today()
                - datetime.date.fromisoformat((posted or "")[:10])).days > MAX_AGE_DAYS
    except ValueError:
        return False


def _closed(valid_through):
    """schema.org validThrough: the date the employer said the posting stops accepting people.

    eJobs publishes it, Hipo does not - which is why a dead Hipo ad can only be caught at apply
    time. Unset means unknown, never closed: most ads carry no date at all and dropping those
    would empty the list. It is also a floor, not a guarantee - an employer can fill a role
    early, and that case still shows up as "closed on the board" when an apply is attempted.
    """
    try:
        return datetime.date.fromisoformat((valid_through or "")[:10]) < datetime.date.today()
    except ValueError:
        return False


# How many detail pages to fetch at once. Sequential meant a minute and a half of nothing for a
# normal search, because each page is about a second of waiting on the network and nothing else.
# Kept low deliberately: these are small boards, the requests are spread across four of them,
# and _get already backs off on a 429.
FETCH_WORKERS = 5


def hydrate(jobs, timeout=30, on_progress=None, report=None):
    """Phase 2: fetch the detail page only for jobs that survived deduplication. This is where
    the requests are, so the caller should drop everything it already knows about first.

    on_progress(done, total) is called as pages arrive, so a caller can show where it is up to.
    report, if given, comes back with {"unread": n}: postings whose page never answered. They
    are dropped here, and were dropped in silence - a board rate-limiting us for a minute could
    swallow twenty of thirty and the search still reported success.
    """
    todo = [j for j in jobs if not j.get("_full")]
    if not todo:
        return [dict(j, **{}) for j in jobs]
    with httpx.Client(headers=UA, follow_redirects=True, timeout=timeout) as c:
        def fetch(j):
            try:
                return j, _get(c, j["url"]).text
            except httpx.HTTPError:
                return j, None

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            pages = pool.map(fetch, todo)
            for done, (j, page) in enumerate(pages, 1):
                if on_progress:
                    on_progress(done, len(todo))
                if page is None:
                    if report is not None:
                        report["unread"] = report.get("unread", 0) + 1
                    continue
                if GOES_EXTERNAL.search(page):
                    # keep whatever the board already said about the ad; this is one more fact
                    j["note"] = " · ".join(x for x in (j.get("note"), EXTERNAL_NOTE) if x)
                jp = _jobposting(page)
                markup = _markup(j["source"], page)
                if not jp:
                    # no JSON-LD: fall back to the board's own markup, keeping what phase 1 gave us
                    if markup:
                        j.update(description=markup, _full=True)
                    continue
                # whichever source carries more of the ad wins - a score computed from a third of
                # a posting is confident and wrong
                body = max(_ld_body(jp), markup, key=len)
                if len(body) < MIN_AD:
                    continue                  # scoring a title is a guess dressed up as a number
                # JSON-LD first: it is the employer's own figure, with a currency and a
                # unit. _salary() reads BestJobs' unlabelled range off the markup and is the
                # fallback, not the other way round.
                pay = _pay(jp) or _salary(page)
                if pay:
                    j["salary"] = pay
                terms = _terms(jp)
                if terms:
                    j["terms"] = terms
                # `or j[...]` on every one of them: an ad whose JSON-LD omits
                # hiringOrganization used to overwrite a company phase 1 had already found with
                # an empty string, and the card then showed no employer at all
                j.update({
                    "title": _flat(jp.get("title")) or j["title"],
                    "company": _flat(jp.get("hiringOrganization")) or j.get("company", ""),
                    "location": (_place(_flat(jp.get("jobLocation")))
                                 or ("Remote" if jp.get("jobLocationType") else "")
                                 or j.get("location", "")),
                    "posted": _flat(jp.get("datePosted"))[:10] or j.get("posted", ""),
                    "description": body,
                    # the employer's own closing date. eJobs publishes it on most ads and
                    # it is the difference between "apply this week" and "apply sometime"
                    "expires": _flat(jp.get("validThrough"))[:10],
                    "_full": True,
                })
    # The real title only arrives with the detail page, so re-check the noise filter here - and
    # dedupe on (title, company) here rather than before hydrate, because phase 1 leaves company
    # empty for the HTML boards. Without this the same ad reaches the database from two sources,
    # gets scored twice, and can be applied to twice.
    out, seen = [], set()
    for j in jobs:
        if (not j.get("_full") or NOISE.search(j["title"]) or _too_old(j.get("posted"))
                or _closed(j.get("expires"))):
            continue
        key = (j["title"].lower().strip(), (j.get("company") or "").lower().strip()[:18])
        if key[1] and key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def search(board, query, location="", limit=25, timeout=30, country="ro", filters=None):
    """One-shot discover+hydrate. The app uses the two phases separately so that a repeat search
    costs one request per board instead of one per posting."""
    return hydrate(discover(board, query, location, limit, timeout, country, filters), timeout)


if __name__ == "__main__":  # smoke check: python scrape.py
    for b in BOARDS:
        try:
            r = search(b, "programator", limit=3)
            print(b, len(r), r[0]["title"] if r else "-")
            assert not r or all(j["title"] and j["description"] for j in r), "empty fields"
        except Exception as e:
            print(b, "FAILED", type(e).__name__, e)
