"""The weekly run, started by Windows Task Scheduler rather than by you opening the app.

It does the part of a Sunday morning that is pure legwork: run your saved search across all four
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
import pathlib
import sys
import time
import traceback

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))          # Task Scheduler starts us with its own working directory

import app                             # noqa: E402  (has to follow the sys.path line)
import auto_apply                      # noqa: E402
import prefill                         # noqa: E402

LOG = HERE / "auto.log"
LAST = HERE / "auto_last.json"
KEEP_LINES = 400                       # the log covers the last few runs, not for ever


def log(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {msg}"
    print(line)
    try:
        old = LOG.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:] if LOG.exists() else []
        LOG.write_text("\n".join(old + [line]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _write(report):
    try:
        LAST.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def run():
    """-> the report dict, also written to auto_last.json for the dashboard to show."""
    s = app.settings()
    report = {"when": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
              "searched": None, "waiting": 0, "applied": None, "note": None, "error": None}

    if not s.get("auto_enabled"):
        log("the weekly run is switched off - nothing to do")
        return report
    if not (s.get("auto_query") or "").strip():
        report["note"] = "No search terms saved for the weekly run."
        log(report["note"])
        _write(report)
        return report

    log(f"weekly run starting: {s['auto_query']!r}")
    try:
        found = asyncio.run(app.search({
            "query": s["auto_query"], "location": s.get("auto_location", ""),
            "county": s.get("auto_county", ""),
            "country": s.get("auto_country", "ro"), "filters": {"reality": "fresh"}}))
        report["searched"] = found
        log(f"search: {found['found']} ads seen, {found['new']} new, {found['scored']} scored"
            + (f", {found['vetoed']} skipped on language" if found.get("vetoed") else "")
            + (f"  warnings: {'; '.join(found['warnings'])}" if found.get("warnings") else ""))
    except Exception as e:
        report["error"] = f"the search failed: {type(e).__name__}: {e}"
        log(report["error"] + "\n" + traceback.format_exc())
        _write(report)
        return report

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
    import json as _json
    import prefill
    try:
        jar = _json.loads(prefill.STATE.read_text(encoding="utf-8")).get("cookies", [])
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
    import prefill
    before = _cookie_hours()
    out = prefill.verify_boards()
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
    try:
        touch() if mode == "touch" else run()
    except Exception:
        log(f"the {mode} run crashed:\n" + traceback.format_exc())
        raise
