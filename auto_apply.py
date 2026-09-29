"""The part of the weekly run that sends applications.

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
import datetime


def candidates(app, prefill, min_fit, cap, boards=None):
    """-> the jobs this run may apply to, best score first. Pure selection, no side effects.

    `boards` limits it to the ones signed in right now. Without that a signed-out board's jobs
    filled the cap and were then refused one by one, so a week could reach its limit of five
    having sent nothing at all.
    """
    with app.db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT url, title, company, source, fit FROM jobs "
            "WHERE status IN ('new','ready') AND fit >= ? "
            # same tie-break as the dashboard: a job with fewer people already in the queue is
            # the better use of one of this week's five
            "ORDER BY fit DESC, CASE WHEN applicants IS NULL THEN 1 ELSE 0 END, "
            "applicants ASC, found DESC", (int(min_fit),))]
    ok = set(boards) if boards is not None else None
    return [r for r in rows
            if prefill.apply_mode(r["source"]) == "auto"
            and (ok is None or r["source"] in ok)][:max(0, int(cap))]


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

    # A board that is out, and whose sign-in you chose to save, gets ONE attempt - here, and
    # nowhere else in the app. This is the moment the feature exists for: nobody is at the
    # keyboard, and without it the week sends nothing. One attempt, never a loop; two failures
    # and creds stops handing the password over at all, because an unattended retry loop is how
    # an account gets locked.
    for board in list(out):
        try:
            import creds
            saved = creds.get(board)
        except Exception as e:                   # a credentials file we cannot read is not fatal
            log(f"could not read the saved sign-in for {board}: {type(e).__name__}")
            continue
        if not saved:
            continue
        log(f"{board}: signed out, trying the sign-in you saved")
        ok, why = prefill.auto_signin(board, *saved)
        log(f"{board}: {'signed in again' if ok else 'could not sign in - ' + why}")
        if ok:
            creds.note_success(board)
            usable.append(board)
            out.remove(board)
        else:
            left = creds.MAX_FAILS - creds.note_failure(board)
            if left <= 0:
                log(f"{board}: not trying the saved sign-in again until you save it afresh")
    if out:
        log(f"not signed in to {', '.join(out)} - applying on {', '.join(usable) or 'nothing'}")
    if not usable:
        report["note"] = (f"Not signed in to {' or '.join(out)}, so nothing was sent. "
                          f"Sign in again under Settings.")
        log(report["note"])
        return report

    picks = candidates(app, prefill, settings["auto_apply_min_fit"], settings["auto_apply_cap"],
                       usable)
    report["considered"] = len(picks)
    if not picks:
        report["note"] = (f"Nothing scored {settings['auto_apply_min_fit']} or above on "
                          f"{' or '.join(usable)} this week."
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
