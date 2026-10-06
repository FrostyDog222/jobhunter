"""The scheduled run, started by Windows Task Scheduler rather than by you opening the app.

It does the part of a morning that is pure legwork: run your saved search across all four
boards, score everything new against your profile, and leave the result waiting on the dashboard.
If you switched applying on as well, it then sends the best of what it found, on the boards that
take an application without a form. auto_apply.py holds that step and the limits on it.

Everything it does goes to auto.log, and a summary to auto_last.json, which the dashboard shows
the next time you open it. It decides nothing the dashboard cannot: it calls the same search the
Search & score button calls.
"""
import asyncio
import datetime
import json
import os
import pathlib
import sys
import threading
import time
import traceback

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))          # Task Scheduler starts us with its own working directory

import app                             # noqa: E402  (has to follow the sys.path line)
import auto_apply                      # noqa: E402
import prefill                         # noqa: E402

LOG = HERE / "auto.log"
LAST = HERE / "auto_last.json"
# The last twenty runs, oldest first. auto_last.json answers "did last night work"; this answers
# "has it been working all week", which is the question somebody actually has about something that
# runs while they are asleep. Twenty because a person scrolls this, not a report.
RUNS = HERE / "auto_runs.json"
KEEP_RUNS = 20
KEEP_LINES = 400                       # the log covers the last few runs, not for ever

# Where this run says how far it has got, for a dashboard in another process to read.
#
# The progress bar lives in app.PROGRESS, which `step()` fills as the search works - and this runs
# as its OWN process, started either by that button or by Task Scheduler, so the server's copy of
# that dict stays empty and the page has nothing to show. Pressing "Run it now" looked like nothing
# happening for several minutes: on 27 search terms the first phase alone is 108 requests.
#
# A file, because the two sides are separate processes and this is the smallest thing that crosses
# that line. Rewritten every couple of seconds by a daemon thread, so it also covers the run
# Windows starts on its own, which the server never hears about at all.
NOW = HERE / ".auto_now.json"
HEARTBEAT = 2.0
_LAST_LINE = [""]


def _beat():
    """Mirror this process's progress to a file until the run ends. Daemon, so it never holds
    the run open, and every failure is swallowed: a run must not die because a status file could
    not be written."""
    while True:
        try:
            p = dict(app.PROGRESS)
            p["when"], p["note"] = time.time(), _LAST_LINE[0]
            tmp = NOW.with_suffix(".tmp")
            tmp.write_text(json.dumps(p), encoding="utf-8")
            os.replace(tmp, NOW)
        except Exception:
            pass
        time.sleep(HEARTBEAT)


def _watch():
    t = threading.Thread(target=_beat, daemon=True)
    t.start()
    return t


def log(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {msg}"
    _LAST_LINE[0] = str(msg)[:200]     # the newest line, for the panel to show while this runs
    print(line)
    try:
        # errors="replace", and Exception rather than OSError. A partly-written line - a crash or a
        # full disk mid-write, which this plain write_text can leave - makes read_text raise
        # UnicodeDecodeError, which is a ValueError and sailed straight past an OSError-only guard.
        # run() opens by calling this, and the crash handler at the bottom calls it again, so a
        # torn log file killed the run twice over and wrote nothing anywhere saying why.
        old = (LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-KEEP_LINES:]
               if LOG.exists() else [])
        LOG.write_text("\n".join(old + [line]) + "\n", encoding="utf-8")
    except Exception:
        pass                   # the log is a convenience; it never costs the run anything


def _write(report):
    try:
        LAST.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    _remember(report)


def _remember(report):
    """Append this run to the rolling history. Never lets a history problem cost the run anything.

    Written after auto_last.json rather than instead of it: the summary is what the panel needs to
    draw at all, and a failure here must not take it with it.
    """
    try:
        old = json.loads(RUNS.read_text(encoding="utf-8")) if RUNS.exists() else []
        if not isinstance(old, list):
            old = []
    except (OSError, ValueError):
        old = []                       # a damaged history starts again rather than ending the run
    ap = report.get("applied") or {}
    s = report.get("searched") or {}
    try:
        row = {
            "when": report.get("when"),
            "error": report.get("error"),
            "note": report.get("note") or (ap.get("note") if isinstance(ap, dict) else None),
            "found": s.get("found"), "new": s.get("new"), "scored": s.get("scored"),
            "waiting": report.get("waiting"),
            # A board that did not answer, or answered nothing where it has always answered
            # something. _search returns these and the manual search shows them; the history
            # dropped them, so "eJobs was down all Sunday" and a clean run read identically here.
            "warnings": (s.get("warnings") or [])[:4],
            # one line per application, with the reason where there is one. The panel drew a cross
            # and dropped the text, which is the half that says what to do about it.
            "sent": [{"title": r.get("title"), "fit": r.get("fit"), "board": r.get("source"),
                      "ok": bool(r.get("submitted")),
                      "why": (None if r.get("submitted") else
                              "already applied" if r.get("already") else
                              "needs you - screening questions" if r.get("needs_you") else
                              str(r.get("error") or "did not send")[:200])}
                     for r in (ap.get("applied") or [] if isinstance(ap, dict) else [])],
        }
        # One row per run, not per write. run() writes twice when applying is switched on - once
        # before the applying step so a crash there still leaves the search behind, once after -
        # and appending both put two rows with the SAME timestamp in the panel: the first with no
        # error and nothing sent, the second with the real failure. A run that died while applying
        # left a clean-looking row sitting directly beneath it, and the twenty kept covered ten
        # runs rather than twenty.
        old = [r for r in old if not (isinstance(r, dict) and r.get("when") == row["when"])]
        old.append(row)
        RUNS.write_text(json.dumps(old[-KEEP_RUNS:], ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except (OSError, TypeError, ValueError) as e:
        print(f"[auto] could not write the run history: {type(e).__name__}: {e}")


def run():
    """-> the report dict, also written to auto_last.json for the dashboard to show."""
    s = app.settings()
    report = {"when": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
              "searched": None, "waiting": 0, "applied": None, "note": None, "error": None}

    if not s.get("auto_enabled"):
        log("the scheduled run is switched off - nothing to do")
        return report
    if not (s.get("auto_query") or "").strip():
        report["note"] = "No search terms saved for the scheduled run."
        log(report["note"])
        _write(report)
        return report

    log(f"scheduled run starting: {s['auto_query']!r}")
    try:
        found = asyncio.run(app.search({
            "query": s["auto_query"], "location": s.get("auto_location", ""),
            "county": s.get("auto_county", ""),
            "country": s.get("auto_country", "ro"),
            # the same four the search bar sends. "reality" is freshness; it defaulted to fresh
            # here and was the only one the scheduled run had at all.
            "filters": {"reality": s.get("auto_fresh", "fresh"),
                        "work_mode": s.get("auto_work_mode", ""),
                        "seniority": s.get("auto_seniority", ""),
                        "auto_apply_available": s.get("auto_ats", "")}}))
        report["searched"] = found
        log(f"search: {found['found']} ads seen, {found['new']} new, {found['scored']} scored"
            + (f", {found['vetoed']} skipped on language" if found.get("vetoed") else "")
            # never read, never scored: the whole point of the skip list is this number
            + (f", {found['off_family']} skipped as the wrong kind of job"
               if found.get("off_family") else "")
            # A closed ad going is housekeeping and not worth a line. One you would have APPLIED
            # to going is the only part of that number you can act on, and it used to be folded
            # into "27 dropped as over two weeks old" with nothing to say an 85 was among them.
            + (f", {found['expired']} closed or aged out"
               + (f" - {found['expired_good']} of them a job at "
                  f"{s.get('auto_min_fit', 75)}+ that the employer closed"
                  if found.get("expired_good") else "")
               if found.get("expired") else "")
            + (f"  warnings: {'; '.join(found['warnings'])}" if found.get("warnings") else ""))
    except Exception as e:
        report["error"] = f"the search failed: {type(e).__name__}: {e}"
        log(report["error"] + "\n" + traceback.format_exc())
        _write(report)
        return report

    # Once a month, ask the boards which saved jobs they still have. Inside this run rather than
    # a task of its own: it is some nine hundred requests, so a daily pass would be thirty times
    # the traffic to learn the same thing, and a third scheduled task is a third thing to go wrong.
    #
    # After the search on purpose. The search has already added today's ads, so they are checked
    # too - and if this throws, the search above is still saved below.
    if app.recheck_due(s):
        try:
            rc = app.recheck_jobs()
            report["rechecked"] = rc
            log(f"monthly recheck: asked the boards about {rc['asked']} saved jobs, "
                f"{rc['gone']} are gone"
                + (f" ({rc['gone_good']} of them at {s.get('auto_min_fit', 75)}+)"
                   if rc["gone_good"] else "")
                + (" - " + ", ".join(f"{n} {w}" for w, n in rc["why"].items()) if rc["why"] else ""))
        except Exception as e:
            # NOT "nothing was removed": recheck_jobs deletes the rows it found gone and only then
            # writes the timestamp, so the write is the likeliest thing here to throw - by which
            # point the deleting is done. Saying otherwise told somebody their list was untouched
            # when it had just shrunk.
            log(f"the monthly recheck failed ({type(e).__name__}: {e}) - it may have removed "
                f"some jobs before it stopped, and it will run again on the next scheduled run")

    # what is now sitting there for you, by the standard you set for a job worth opening
    with app.db() as c:
        report["waiting"] = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('new','ready') AND fit >= ?",
            (int(s.get("auto_min_fit", 75)),)).fetchone()[0]
    log(f"{report['waiting']} job(s) at {s.get('auto_min_fit', 75)}+ are waiting on the dashboard")
    # Written BEFORE the applying step, so a crash there still leaves the search behind - and so
    # a run with applying switched off, which returns just below, reports at all. Losing this
    # line meant every successful run left auto_last.json untouched and the dashboard showing
    # the previous run's numbers as if they were today's.
    _write(report)

    if not s.get("auto_apply"):
        return report
    try:
        report["applied"] = auto_apply.run(app, prefill, s, log)
    except Exception as e:
        report["error"] = f"applying failed: {type(e).__name__}: {e}"
        log(report["error"] + "\n" + traceback.format_exc())
    _write(report)
    return report


# The cookie that actually carries each board's session, and how long it had left. Hipo is the
# interesting one: ctlyst_hp_sss is renewed by visiting, hhppctly is not, so if hhppctly's fixed
# life is what ends the session there is nothing a keep-alive can do about it.
SESSION_COOKIES = {
    "hipo": ("ctlyst_hp_sss", "hhppctly"),
    "ejobs": ("user-access-token", "user-refresh-token"),
    "bestjobs": ("_ast",),
}


def _cookie_hours():
    """-> {board: "name 5.9h, other 20.0h"} for the cookies that carry each session."""
    try:
        jar = json.loads(prefill.STATE.read_text(encoding="utf-8")).get("cookies", [])
    except (OSError, ValueError):
        return {}
    now, out = datetime.datetime.now().timestamp(), {}
    for board, names in SESSION_COOKIES.items():
        host = {"hipo": "hipo.ro", "ejobs": "ejobs.ro", "bestjobs": "bestjobs"}[board]
        bits = []
        for c in jar:
            if host in (c.get("domain") or "") and c.get("name") in names:
                exp = c.get("expires") or -1
                bits.append(f"{c['name']} {((exp - now) / 3600):.1f}h" if exp > 0
                            else f"{c['name']} session")
        if bits:
            out[board] = ", ".join(sorted(bits))
    return out


def touch():
    """Load each board with the saved session, which renews it, and write the jar back.

    This is the whole keep-alive. It is the same call the dashboard makes to check sign-ins -
    the checking IS the refreshing, because a board renews its cookie when you visit.
    """
    before = _cookie_hours()
    out = prefill.verify_boards()
    # A session that lapsed while the PC was off is the exact thing this task exists to prevent,
    # and it could do nothing about it: the saved sign-in was only ever used by the applying step,
    # so with applying off - the ordinary case - nothing used it at all. Hipo's session is a
    # rolling six hours, so one night with the machine off outlives it, and it then stayed signed
    # out until somebody noticed by hand. Now the worst case is two hours.
    down = [b for b, ok in out.items() if not ok]
    if down:
        for board in auto_apply.sign_back_in(prefill, down, log):
            out[board] = True
    # sampled after the sign-in, so the 'after' column shows the session that is actually there
    after = _cookie_hours()
    log("keep-alive: " + ", ".join(f"{b}={'ok' if v else 'SIGNED OUT'}"
                                   for b, v in sorted(out.items())))
    for board in sorted(set(before) | set(after)):
        log(f"   {board:9s} before[{before.get(board, '-')}]  after[{after.get(board, '-')}]")
    return out


LOCK = HERE / ".auto.lock"
_HELD = []                             # the handle has to outlive this function or Windows frees it


def only_one(wait=0):
    """-> True if we got the lock. False means another run is going, so this one stops.

    One lock for both modes on purpose: they drive the same browser profile directory, and two
    Chromiums sharing one is how a signed-in session gets corrupted.

    `wait` seconds is how long to keep trying, and the two modes deliberately differ. The search
    waits, because Task Scheduler does not retry a run that returned success - so giving up
    silently costs a whole day's search. The keep-alive does not, because skipping one costs
    nothing: the next is two hours away, and the search it yielded to visits every board itself.
    """
    try:
        import msvcrt
    except ImportError:
        return True                    # not Windows: nothing schedules two runs here anyway
    deadline = time.monotonic() + max(0, wait)
    while True:
        try:
            f = open(LOCK, "a+b")
        except OSError as e:
            # Not the same thing as another run, and saying so sent someone looking for a second
            # process that was never there: read-only file, a backup tool holding it, a share
            # that refuses locks.
            log(f"could not open {LOCK.name} ({type(e).__name__}) - running without the lock")
            return True
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            f.close()
            if time.monotonic() >= deadline:
                return False
            time.sleep(5)
            continue
        _HELD.append(f)                # released by the OS when this process ends, crash or not
        return True


if __name__ == "__main__":
    # pythonw.exe - which is what Task Scheduler runs - has no console, so sys.stdout and
    # sys.stderr are None and .reconfigure() on None is an AttributeError that kills the process
    # on its first line, before any logging. Every scheduled run failed this way, silently.
    for _s in (sys.stdout, sys.stderr):
        if _s is not None:
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    mode = "touch" if "--touch" in sys.argv else "run"
    # The search waits for a keep-alive to finish; a keep-alive never waits for the search.
    if not only_one(wait=0 if mode == "touch" else 180):
        log(f"the {mode} run stopped: another run is already going")
        sys.exit(0)                    # not a failure - Task Scheduler must not retry it
    # Only the full run is worth watching: --touch is a couple of page loads and is over before a
    # panel could draw anything about it.
    if mode == "run":
        _watch()
    try:
        touch() if mode == "touch" else run()
    except Exception:
        log(f"the {mode} run crashed:\n" + traceback.format_exc())
        raise
    finally:
        # The page decides a run is live from this file being recent, so leaving a stale one behind
        # would show "still running" over a run that finished - or crashed - minutes ago.
        try:
            NOW.unlink(missing_ok=True)
        except OSError:
            pass
