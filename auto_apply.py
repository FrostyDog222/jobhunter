"""The part of the scheduled run that sends applications.

Its own file because it is the only code in this project that acts on a real employer without a
person present. Everything it is allowed to do is narrowed here, in one place you can read in a
minute:

  - only boards the app can submit on without a form (prefill.AUTO_APPLY)
  - only rows nobody has touched: status 'new' or 'ready'. Applied, opened, skipped and vetoed
    are left alone, so nothing is ever sent twice and a job you rejected is not resurrected
  - only scores at or above the floor you set, highest first
  - never more than the cap you set, per run
  - no browser windows: a posting that turns out to have screening questions is marked and left
    for you, because nobody is at the keyboard at 09:00 on a Sunday to answer them

It sends the CV that sits on your board profile, and the salary figure from your profile page,
to employers whose ads nobody read. That is the deal; the dashboard says so before you switch
it on.
"""
import creds

# The note a posting carries once its apply button has been found to leave the board.
# Spelled here rather than read off app, so this module can be tested with a stub app -
# and asserted equal to app.EXTERNAL_NOTE by the suite, so the two cannot drift.
EXTERNAL_NOTE = "apply on the employer site"
import datetime


def candidates(app, prefill, min_fit, cap, boards=None, city="", county="", held=None):
    """-> the jobs this run may apply to, best score first. Pure selection, no side effects.

    `boards` limits it to the ones signed in right now. Without that a signed-out board's jobs
    filled the cap and were then refused one by one, so a week could reach its limit of five
    having sent nothing at all.
    """
    with app.db() as c:
        rows = [dict(r) for r in c.execute(
            # description too, because a fully remote job often names the employer's head
            # office as its location - Spain, Germany - and is reachable from anywhere regardless.
            # Bounded by the score floor in the WHERE below, so this is the shortlist, not the table.
            "SELECT url, title, company, source, fit, note, location, description FROM jobs "
            "WHERE status IN ('new','ready') AND fit >= ? "
            # same tie-break as the dashboard: a job with fewer people already in the queue is
            # the better use of one of this week's five
            "ORDER BY fit DESC, CASE WHEN applicants IS NULL THEN 1 ELSE 0 END, "
            "applicants ASC, found DESC", (int(min_fit),))]
    ok = set(boards) if boards is not None else None
    # Where the person set a city or a county, hold the unattended run to it. The search only
    # filters what it DISCOVERS, so everything stored before those filters were set stayed
    # eligible for ever - measured, 44 of 49 candidates were outside the county that was asked
    # for, and applications went to them. `held` counts what this drops so the run can say so.
    import scrape

    def col(r, name):
        try:
            return r[name]
        except (KeyError, IndexError):
            return None

    def here(r):
        if scrape.job_in_area({"location": col(r, "location"), "title": col(r, "title"),
                               "description": col(r, "description")}, city, county):
            return True
        if held is not None:
            held.append(f'{r["title"]} ({r["location"] or "no location given"})')
        return False

    return [r for r in rows
            if prefill.apply_mode(r["source"]) == "auto"
            and (ok is None or r["source"] in ok)
            and here(r)
            # A posting whose apply button hands you to the employer's own site cannot be sent
            # from here, and that will not change - so it must not fill one of the week's five
            # and be reported as a failure. Thirteen of fifteen Hipo ads are this kind.
            and EXTERNAL_NOTE not in (r.get("note") or "")][:max(0, int(cap))]


def sign_back_in(prefill, out, log):
    """Try the saved sign-in for each board in `out`. -> the boards that came back.

    ONE attempt per board, never a loop: an unattended retry posting a wrong password is how an
    account gets locked, which is far worse than being signed out for another two hours. Two
    failures that were the board rejecting the password and creds stops handing it over until you
    save it again.

    Shared by the keep-alive and the applying step, in one function so those guards cannot drift
    apart. It used to live only in the applying step, which meant a saved password was used only
    when "Also apply for me" was on - so saving a sign-in and leaving applying off, which is the
    ordinary combination, got you no automatic sign-in at all. The keep-alive would report
    "hipo=SIGNED OUT" every two hours and never do the one thing it had the means to do.
    """
    back = []
    for board in list(out):
        try:
            saved = creds.get(board)
        except Exception as e:                   # a credentials file we cannot read is not fatal
            log(f"could not read the saved sign-in for {board}: {type(e).__name__}")
            continue
        if not saved:
            if creds.status().get(board, {}).get("stopped"):
                # get() returns None for ever once the budget is spent, and said nothing about
                # it - so the whole symptom was runs that quietly sent nothing
                log(f"{board}: the saved sign-in is switched off after {creds.MAX_FAILS} "
                    f"failures - save it again under Settings to re-enable it")
            continue
        log(f"{board}: signed out, trying the sign-in you saved")
        ok, why = prefill.auto_signin(board, *saved)
        log(f"{board}: {'signed in again' if ok else 'could not sign in - ' + why}")
        if ok:
            creds.note_success(board)
            back.append(board)
        elif ok is False:
            # False is the board rejecting the password. None is everything else auto_signin can
            # fail on - no form, no button, a timeout, a 502 - and none of that is evidence about
            # the password, so it must not spend a strike. Two runs during a wifi outage used to
            # disable the saved sign-in permanently.
            left = creds.MAX_FAILS - creds.note_failure(board)
            if left <= 0:
                log(f"{board}: not trying the saved sign-in again until you save it afresh")
    return back


def run(app, prefill, settings, log):
    """Apply to this week's best matches. -> a report dict for auto_last.json.

    `log` is auto.py's logger, so a scheduled run leaves the same trail as everything else.
    """
    report = {"considered": 0, "applied": [], "note": None}

    # session_for() reads the status the dashboard last verified, and nothing ages that file out
    # - it can be days old. This run is unattended and about to send real applications, so ask
    # the boards themselves first: a session that expired since the last time anyone opened the
    # app would otherwise mean a week of applications silently going nowhere. A board the probe
    # could not reach at all (wifi blip) keeps its cached answer rather than being called dead.
    try:
        live = prefill.verify_boards(prefill.AUTO_APPLY)
    except Exception as e:                       # a browser that will not start is not "signed out"
        log(f"could not re-check the boards ({type(e).__name__}), using the last known status")
        live = {}
    # One board being out is not a reason to skip the others. This used to return on the first
    # one it found signed out, so a lapsed eJobs session cost the week's BestJobs applications
    # too - on a session that runs six months and had nothing wrong with it.
    usable = [b for b in prefill.AUTO_APPLY if live.get(b, prefill.session_for(b))]
    out = [b for b in prefill.AUTO_APPLY if b not in usable]

    # A board that is out, and whose sign-in you chose to save, gets one attempt. The keep-alive
    # does this too, every two hours, which is where it matters most - see sign_back_in.
    for board in sign_back_in(prefill, out, log):
        usable.append(board)
        out.remove(board)
    if out:
        log(f"not signed in to {', '.join(out)} - applying on {', '.join(usable) or 'nothing'}")
    if not usable:
        report["note"] = (f"Not signed in to {' or '.join(out)}, so nothing was sent. "
                          f"Sign in again under Settings.")
        log(report["note"])
        return report

    # the city and county saved for the scheduled run. Without these it applied to anything above
    # the score floor wherever it was - measured, 44 of 49 candidates outside the county that had
    # been set - because the search only filters what it discovers and the table is full of ads
    # found before those filters existed.
    held = []
    picks = candidates(app, prefill, settings["auto_apply_min_fit"], settings["auto_apply_cap"],
                       usable, city=settings.get("auto_location") or "",
                       county=settings.get("auto_county") or "", held=held)
    report["considered"] = len(picks)
    report["held_for_location"] = len(held)
    if held:
        # said out loud: sending nothing because everything was somewhere else looks exactly like
        # finding nothing, and the difference is the whole reason the filter exists
        log(f"held back {len(held)} job(s) outside "
            f"{settings.get('auto_location') or settings.get('auto_county')}: "
            + "; ".join(held[:5]) + (" ..." if len(held) > 5 else ""))
    if not picks:
        report["note"] = (f"Nothing scored {settings['auto_apply_min_fit']} or above on "
                          f"{' or '.join(usable)} on this run."
                          + (f" {len(held)} were outside "
                             f"{settings.get('auto_location') or settings.get('auto_county')}."
                             if held else "")
                          + (f" (Not signed in to {', '.join(out)}.)" if out else ""))
        log(report["note"])
        return report

    log(f"applying to {len(picks)} (cap {settings['auto_apply_cap']}, "
        f"floor {settings['auto_apply_min_fit']}):")
    for p in picks:
        log(f"   {p['fit']:3}  {p['title'][:56]}  [{p['source']}]")

    import asyncio
    out = asyncio.run(app.apply_batch({
        "urls": [p["url"] for p in picks],
        # no windows: a screening question is marked and left, never opened on an empty desk
        "hand_off": False,
        # ...and never submit a screening answer with nobody at the keyboard. hand_off only
        # stops a WINDOW opening; without this the run filled an employer's mini-interview with
        # model-written text and pressed Trimite, which is the opposite of what this file's own
        # header promises.
        "auto_send": False,
    }))

    fit = {p["url"]: p["fit"] for p in picks}
    for r in out["results"]:
        r["fit"] = fit.get(r["url"])
        r["when"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        state = ("sent" if r.get("submitted") else "already applied" if r.get("already")
                 else "needs you - screening questions" if r.get("needs_you")
                 else f"failed: {r.get('error')}")
        log(f"   {state} - {r['title'][:56]}")
    report["applied"] = out["results"]
    log(f"applied: {out['sent']} sent, {out['skipped']} already applied, "
        f"{out['needs_you']} need you, {out['failed']} failed")
    return report
