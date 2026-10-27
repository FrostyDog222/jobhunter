"""What broke, and where the time went - the data behind the Health tab.

Everything the app already knew about a bad run was either a toast that vanished, a line in a log
nobody opens, or a number in a function's return value. A board that quietly returned a third of
its ads looked identical to a quiet day, and "the run took 33 minutes" could not be pulled apart.
This keeps a short record of every search, manual or scheduled, and turns the pile of warnings
into the question a person actually has: which board, what went wrong, since when, and is it
still going on.

Pure functions over plain data. The caller reads the files and hands them in, which is also what
makes every rule here testable without a browser or a network.
"""
import datetime
import json
import os
import re
import tempfile

KEEP = 40                     # searches remembered. A month of daily runs plus a few by hand.

NAMES = {"ejobs": "eJobs", "bestjobs": "BestJobs", "hipo": "Hipo", "olx": "OLX",
         "publi24": "publi24", "freehire": "freehire"}


# ---------------------------------------------------------------- the record of each search

def _round(x):
    """Floats to a tenth, recursively - a record is read by people and does not need microseconds."""
    if isinstance(x, float):
        return round(x, 1)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    return x


def load(path):
    """-> the saved records, newest first. A missing or damaged file is no records, not an error:
    this is one tab and the rest of the app must not care."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)][::-1] if isinstance(rows, list) else []


def log_search(path, body, out=None, error=None, now=None):
    """Append one search to the rolling record. Never raises: keeping a record of a search must
    not be able to cost the search anything."""
    try:
        now = now or datetime.datetime.now()
        terms = [q for q in re.split(r"[,;]", (body or {}).get("query") or "") if q.strip()]
        rec = {"when": (body or {}).get("when") or now.strftime("%Y-%m-%d %H:%M"),
               "via": (body or {}).get("via") or "manual", "terms": len(terms), "error": error}
        if out:
            rec.update({k: out.get(k) for k in ("found", "new", "scored", "vetoed", "off_mode")})
            # kept whole, cut per line: a clipped list would hide exactly the repeated
            # "did not answer for ..." lines that say how widespread a problem was
            rec["warnings"] = [str(w)[:300] for w in (out.get("warnings") or [])[:60]]
            rec["timing"] = _round(out.get("timing") or {})
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            old = old if isinstance(old, list) else []
        except (OSError, ValueError):
            old = []
        old = [r for r in old if not (isinstance(r, dict) and r.get("when") == rec["when"]
                                      and r.get("via") == rec["via"])]
        old.append(rec)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + "-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(old[-KEEP:], f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:                      # noqa: BLE001 - see the docstring
        print(f"[health] could not record the search: {type(e).__name__}: {e}")


def merge(records, scheduled):
    """Our records plus the older scheduled-run history, newest first.

    auto_runs.json predates the search record and has the earlier runs' warnings (four at most,
    and no timing) - worth showing, because "what broke last week" is the question this tab is for
    and it should not start empty. A scheduled run that is in both is counted once.
    """
    have = {(r.get("when"), r.get("via")) for r in records}
    older = [{"when": r.get("when"), "via": "scheduled", "terms": None, "error": r.get("error"),
              "found": r.get("found"), "new": r.get("new"), "scored": r.get("scored"),
              "warnings": r.get("warnings") or [], "timing": None}
             for r in scheduled or [] if isinstance(r, dict)
             and (r.get("when"), "scheduled") not in have]
    return sorted(list(records) + older, key=lambda r: str(r.get("when") or ""), reverse=True)


# ---------------------------------------------------------------- reading the warnings

# Ordered: the first that matches wins. "returned about N ads ... changed its layout" has the word
# layout in it too, so the thin-board rule has to be asked before the layout one.
RULES = (
    ("silent", r"\d+ results? but \d+ stored previously|0 results but"),
    ("thin", r"returned about \d+ ads per search term"),
    ("unreadable", r"nothing readable"),
    ("layout", r"results grid|result count|layout may have changed|none could be read"),
    # before "unanswered": "N ads could not be read this time - the board did not answer" says
    # the second thing too, and is about ad pages, not about a search term
    ("unread", r"ads? could not be read this time|could not be read this"),
    ("unanswered", r"did not answer"),
    ("scoring", r"could not be scored|could not be saved"),
    ("quota", r"rate limited|out of quota|used up|quota"),
)

# "break" is the site changing under us - it will not mend by itself. "transient" is the ordinary
# weather: a rate limit, a slow hour. The tab says which, because the right response differs.
SEVERITY = {"silent": "break", "thin": "break", "unreadable": "break", "layout": "break",
            "error": "break", "blocked": "break", "unanswered": "transient", "unread": "transient",
            "scoring": "transient", "quota": "transient", "other": "transient"}

LABEL = {
    "blocked": "Turning the app away on nearly every search",
    "silent": "Returned nothing",
    "thin": "Returning far fewer ads than usual",
    "unreadable": "Ad pages load but nothing can be read",
    "layout": "The page layout has changed",
    "unanswered": "Did not answer some searches",
    "unread": "Some ad pages did not answer",
    "scoring": "Some ads were not scored",
    "quota": "AI models out of quota",
    "error": "The search stopped with an error",
    "other": "Warning",
}

ADVICE = {
    "blocked": "Nearly every search was refused - that is a block, not ordinary rate limiting, which "
               "loses a handful of terms a run. The app falls back to a real browser where it can. "
               "If this carries on, run Update.bat: a fix may already be out.",
    "silent": "It answered with nothing where it normally answers with plenty, so its page has "
              "probably changed. Run Update.bat - a fix may already be out. The other boards are "
              "not affected.",
    "thin": "It is answering, but with far fewer ads than usual - the app is most likely reading "
            "only part of its page. Run Update.bat. This stays flagged until the board is back to "
            "normal, so it cannot quietly become the new normal.",
    "unreadable": "The ad pages load but nothing could be read from them, so none of those ads "
                  "can be scored. The board has probably changed how it publishes an ad. Run "
                  "Update.bat.",
    "layout": "The page no longer looks the way the app expects. It still worked, but the results "
              "may be incomplete or may include suggestions. Run Update.bat.",
    "unanswered": "The board refused or timed out on some searches - usually rate limiting or a "
                  "short outage. It mends itself; the only loss is those search terms for this run.",
    "unread": "Ads were found but their pages did not answer. They are fetched again on the next "
              "search, so nothing is lost.",
    "scoring": "Some ads could not be scored, usually because every AI model was busy. They are "
               "tried again on the next search.",
    "quota": "Every AI model was out of quota for a while. They reset on their own; adding another "
             "key under Settings makes it less likely.",
    "error": "The whole search stopped. auto.log has the detail.",
    "other": "",
}


def classify(line, sources=tuple(NAMES)):
    """-> (board or None, kind) for one warning line."""
    text = str(line or "")
    low = text.lower()
    head = re.match(r"\s*([a-z0-9]+)\b", low)
    board = head.group(1) if head and head.group(1) in sources else None
    if board is None:
        board = next((b for b in sources if b in low[:60]), None)
    kind = next((k for k, pat in RULES if re.search(pat, low)), "other")
    return board, kind


def _covers(rec, board):
    """Did this search actually look at that board? Without it, a one-term manual search on OLX
    would make every other board's standing problem read as fixed."""
    if board is None:
        return True
    boards = ((rec.get("timing") or {}).get("boards")) or None
    if boards is not None:
        return board in boards
    # An older record has no per-board timing, so silence proves nothing about it either way. It
    # is a scheduled run - those search every enabled board - so it counts as having looked at all
    # of them. The other reading (only the boards it complained about) made every problem that
    # was ever reported look permanent: it was the newest record to mention the board, always.
    return True


def issues(records, sources=tuple(NAMES)):
    """-> what has gone wrong lately, grouped by (board, kind), most pressing first.

    `ongoing` is whether the newest search that looked at that board still had it. A problem that
    has stopped appearing is shown as past, not hidden: "OLX was thin on Tuesday" is worth knowing
    after it has mended.
    """
    groups = {}
    for rec in records:                                  # newest first
        lines = [(classify(w, sources), w) for w in rec.get("warnings") or []]
        # Ordinary rate limiting costs a few search terms a run (eJobs: 3 to 5 of 33, every run).
        # A board refusing nearly ALL of them is something else, and the warning text is the same
        # either way, so the difference is the count: BestJobs' 403 lost all 50 for ten days and
        # read exactly like the weather.
        refused = {}
        for (b_, k_), _w in lines:
            if k_ == "unanswered" and b_:
                refused[b_] = refused.get(b_, 0) + 1
        sweep = {b_ for b_, n_ in refused.items()
                 if n_ >= max(8, int(0.6 * (rec.get("terms") or 0)))}
        lines = [(((b_, "blocked" if (k_ == "unanswered" and b_ in sweep) else k_)), w)
                 for (b_, k_), w in lines]
        if rec.get("error"):
            lines.append((((None, "error")), str(rec["error"])))
        for (board, kind), line in lines:
            g = groups.setdefault((board, kind), {
                "board": board, "kind": kind, "count": 0, "runs": set(),
                "last": rec.get("when"), "first": rec.get("when"), "example": str(line)})
            g["count"] += 1
            g["runs"].add((rec.get("when"), rec.get("via")))
            g["first"] = rec.get("when")                 # ends on the oldest one seen
    out = []
    for (board, kind), g in groups.items():
        newest = next((r for r in records if _covers(r, board)), None)
        now = {(c, k) for c, k in ((classify(w, sources)) for w in (newest or {}).get("warnings") or [])}
        if newest and newest.get("error"):
            now.add((None, "error"))
        out.append({"board": board, "name": NAMES.get(board, ""), "kind": kind,
                    "severity": SEVERITY.get(kind, "transient"), "label": LABEL.get(kind, ""),
                    "advice": ADVICE.get(kind, ""), "count": g["count"], "runs": len(g["runs"]),
                    "first": g["first"], "last": g["last"], "example": g["example"],
                    "ongoing": (board, kind) in now})
    # Two stable passes: newest first, then ongoing before past and a break before the weather.
    out.sort(key=lambda i: str(i["last"] or ""), reverse=True)
    out.sort(key=lambda i: (not i["ongoing"], i["severity"] != "break"))
    return out


# ---------------------------------------------------------------- the tab itself

def usual_per_term(hist, board):
    """The median ads-per-term this board has recently returned, or None before there is enough
    history to call anything usual. Same history the thin-board warning compares against."""
    xs = sorted(x for x in (hist or {}).get(f"{board}|any", []) if isinstance(x, (int, float)))
    return xs[len(xs) // 2] if len(xs) >= 3 else None


def board_rows(records, issue_list, sources, switches, hist, signins, saved):
    rows = []
    for b in sources:
        rec = next((r for r in records if (r.get("timing") or {}).get("boards", {}).get(b)), None)
        seen = ((rec or {}).get("timing") or {}).get("boards", {}).get(b)
        terms = max(1, (rec or {}).get("terms") or 1)
        per = round(seen["ads"] / terms, 1) if seen else None
        usual = usual_per_term(hist, b)
        mine = [i for i in issue_list if i["board"] == b and i["ongoing"]]
        if not switches.get(b, True):
            status = "off"
        elif any(i["severity"] == "break" for i in mine):
            status = "broken"
        elif mine:
            status = "unsteady"
        elif seen is None:
            status = "unknown"
        elif seen["ads"] == 0 and usual:
            status = "silent"
        else:
            status = "ok"
        row = {"id": b, "name": NAMES.get(b, b), "search": bool(switches.get(b, True)),
               "status": status, "per_term": per, "usual": usual,
               "seconds_per_term": round(seen["seconds"] / terms, 1) if seen else None,
               "last": (rec or {}).get("when"), "issues": [i["kind"] for i in mine]}
        if b in signins or b in saved:
            row["signed_in"] = signins.get(b)
            row["saved"] = bool((saved.get(b) or {}).get("saved"))
            row["locked"] = bool((saved.get(b) or {}).get("stopped"))
        rows.append(row)
    return rows


def waits(records):
    """-> the AI providers that did not answer across these searches, costliest first. Summed over
    calls that ran side by side, so it says who is costing us, not how long anyone waited."""
    tot = {}
    for r in records:
        for prov, by in (((r.get("timing") or {}).get("llm_waits")) or {}).items():
            for why, v in by.items():
                t = tot.setdefault((prov, why), {"provider": prov, "why": why, "count": 0, "seconds": 0.0})
                t["count"] += v.get("count", 0)
                t["seconds"] += v.get("seconds", 0.0)
    return sorted((dict(v, seconds=round(v["seconds"])) for v in tot.values()),
                  key=lambda v: -v["seconds"])


def runs(records, limit=8):
    out = []
    for r in records[:limit]:
        t = r.get("timing") or {}
        out.append({"when": r.get("when"), "via": r.get("via"), "found": r.get("found"),
                    "new": r.get("new"), "total": t.get("total"), "find": t.get("find"),
                    "read": t.get("read"), "score": t.get("score"),
                    "warnings": len(r.get("warnings") or []), "error": r.get("error")})
    return out


def build(records, sources, switches, hist, signins, saved, chain):
    """The whole tab in one dictionary. `chain` is [{provider, model, blocked}] in answering order."""
    iss = issues(records, sources)
    rows = board_rows(records, iss, sources, switches, hist, signins, saved)
    resting = [c for c in chain if c.get("blocked")]
    out_boards = [r["name"] for r in rows if r["search"] and r.get("saved") and r.get("signed_in") is False]
    if not records:
        level = "none"
    elif any(i["ongoing"] and i["severity"] == "break" for i in iss) \
            or (chain and len(resting) == len(chain)):
        level = "bad"
    elif any(i["ongoing"] for i in iss) or resting or out_boards:
        level = "warn"
    else:
        level = "good"
    latest = records[0] if records else {}
    return {"level": level, "checked": latest.get("when"), "via": latest.get("via"),
            "issues": iss, "boards": rows, "runs": runs(records), "waits": waits(records),
            "timing": latest.get("timing"), "terms": latest.get("terms"),
            "providers": chain, "signed_out": out_boards, "searches": len(records)}
