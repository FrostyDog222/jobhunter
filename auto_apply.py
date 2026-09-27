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


def candidates(app, prefill, min_fit, cap):
    """-> the jobs this run may apply to, best score first. Pure selection, no side effects."""
    with app.db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT url, title, company, source, fit FROM jobs "
            "WHERE status IN ('new','ready') AND fit >= ? "
            "ORDER BY fit DESC, found DESC", (int(min_fit),))]
    return [r for r in rows if prefill.apply_mode(r["source"]) == "auto"][:max(0, int(cap))]


def run(app, prefill, settings, log):
    """Apply to this week's best matches. -> a report dict for auto_last.json.

    `log` is auto.py's logger, so a scheduled run leaves the same trail as everything else.
    """
    report = {"considered": 0, "applied": [], "note": None}

    for board in prefill.AUTO_APPLY:
        if not prefill.session_for(board):
            report["note"] = (f"Not signed in to {board}, so nothing was sent. "
                              f"Sign in again under Settings.")
            log(report["note"])
            return report

    picks = candidates(app, prefill, settings["auto_apply_min_fit"], settings["auto_apply_cap"])
    report["considered"] = len(picks)
    if not picks:
        report["note"] = (f"Nothing scored {settings['auto_apply_min_fit']} or above on "
                          f"{' or '.join(prefill.AUTO_APPLY)} this week.")
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
