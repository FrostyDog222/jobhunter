"""Job scraping. Every serious board emits schema.org JobPosting JSON-LD for Google Jobs,
so one generic extractor covers them all - a new board is one entry in BOARDS."""
import datetime, html, json, random, re, time, unicodedata
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


def bestjobs(query, limit=25, timeout=30):
    """The #2 Romanian board. Its site is a client-rendered SPA with no JSON-LD, but the API the
    SPA itself calls is public and unauthenticated. It answers 100 rows in one request and ignores
    `page`, so 100 per query is the ceiling - still more than eJobs' 40. No description and no
    posting date in the response, so these go through phase 2 like any HTML board."""
    with httpx.Client(headers={**UA, "Accept": "application/json"}, timeout=timeout) as c:
        r = _get(c, httpx.URL(BESTJOBS, params={"keyword": (query or "").translate(DIACRITICS)}))
        r.raise_for_status()
        items = (r.json().get("items") or [])[:max(int(limit or 0), 0)]
    jobs = []
    for j in items:
        slug = (j.get("slug") or "").strip()
        if not slug or j.get("state") not in (None, "active"):
            continue
        jobs.append({
            "source": "bestjobs",
            "url": BESTJOBS_AD.format(slug=slug),
            "title": _clean(j.get("title")),
            "company": _clean(j.get("companyName")),
            "location": ", ".join(_clean(l.get("name")) for l in (j.get("locations") or [])),
            "posted": "",                       # the list carries no date; the ad page shows none either
            "description": "",
            "note": _clean(j.get("salary") or j.get("estimatedSalary") or ""),
            "lang": "",
            "_full": False,
        })
    return jobs


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


def _find_jobposting(node):
    """Recurse: JSON-LD nests JobPosting under @graph, inside arrays, or under mainEntity
    depending on which SEO plugin produced it."""
    if isinstance(node, list):
        for item in node:
            found = _find_jobposting(item)
            if found:
                return found
    elif isinstance(node, dict):
        t = node.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found = _find_jobposting(node[key])
                if found:
                    return found
    return None


def _jobposting(page_html):
    """Pull the JobPosting node out of any ld+json block on the page."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(html.unescape(block.strip()))
        except json.JSONDecodeError:
            continue          # a malformed block must not stop us checking the later ones
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
    """Entities and mojibake both reach us through titles and companies, not just descriptions."""
    return _fix(html.unescape(s or "")).strip()


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
        })
    return jobs


def health(source, jobs, seen_before):
    """Scrapers rot silently: a portal changes its markup and the parser still exits cleanly with
    zero rows or blank fields. Returns a complaint string, or "" when the source looks fine.
    A source that simply has no matches today is not broken - hence seen_before."""
    if not jobs:
        return f"{source}: 0 results but {seen_before} stored previously - parser may be broken"             if seen_before else ""
    blank = lambda k: sum(1 for j in jobs if not (j.get(k) or "").strip()) == len(jobs)
    if blank("title"):
        return f"{source}: every title empty - parser broken"
    if blank("company"):
        return f"{source}: every company empty - parser broken"
    if any("&amp;" in (j.get("title") or "") or "<" in (j.get("title") or "") for j in jobs):
        return f"{source}: HTML fragments in titles - entities not decoded"
    return ""


# hipo lists career-fair events alongside real vacancies - "Workshop by BAT Romania @ Top
# Talents" and friends. They are not jobs, they never score, and they crowd out the rest. Matched
# on the event phrasing, not the bare word, so a Workshop Manager or Workshop Technician survives.
NOISE = re.compile(r"@\s*top\s+talents"
                   r"|\b(workshop|webinar|masterclass)\s+(by|with|de|cu)\b"
                   r"|^\s*training\s+(by|with|de|cu)\b"
                   r"|\b(career fair|job fair|zilele carierei|t[aâ]rg de (joburi|cariere))\b", re.I)


def _slug_title(path):
    """A board's own URL carries the job title, which is enough to dedupe and pre-filter on
    before deciding whether the detail page is worth a request."""
    seg = [s for s in path.split("/") if s and not s.isdigit()]
    # the path is url-encoded html, so it carries &amp; and %C4%83 through to the title
    return _clean(unquote(re.sub(r"[-_]+", " ", seg[-1]))).strip().title() if seg else ""


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
             "description": "", "note": "", "lang": "", "_full": False}
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


# How many detail pages to fetch at once. Sequential meant a minute and a half of nothing for a
# normal search, because each page is about a second of waiting on the network and nothing else.
# Kept low deliberately: these are small boards, the requests are spread across four of them,
# and _get already backs off on a 429.
FETCH_WORKERS = 5


def hydrate(jobs, timeout=30, on_progress=None):
    """Phase 2: fetch the detail page only for jobs that survived deduplication. This is where
    the requests are, so the caller should drop everything it already knows about first.

    on_progress(done, total) is called as pages arrive, so a caller can show where it is up to.
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
                    continue
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
                j.update({
                    "title": _flat(jp.get("title")) or j["title"],
                    "company": _flat(jp.get("hiringOrganization")),
                    "location": _place(_flat(jp.get("jobLocation")))
                                or ("Remote" if jp.get("jobLocationType") else ""),
                    "posted": _flat(jp.get("datePosted"))[:10],
                    "description": body,
                    "_full": True,
                })
    # The real title only arrives with the detail page, so re-check the noise filter here - and
    # dedupe on (title, company) here rather than before hydrate, because phase 1 leaves company
    # empty for the HTML boards. Without this the same ad reaches the database from two sources,
    # gets scored twice, and can be applied to twice.
    out, seen = [], set()
    for j in jobs:
        if not j.get("_full") or NOISE.search(j["title"]) or _too_old(j.get("posted")):
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
