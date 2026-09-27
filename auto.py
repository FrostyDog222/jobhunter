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
    _write(report)           # written before applying, so a crash there still leaves the search

    if not s.get("auto_apply"):
        return report
    try:
        report["applied"] = auto_apply.run(app, prefill, s, log)
    except Exception as e:
        report["error"] = f"applying failed: {type(e).__name__}: {e}"
        log(report["error"] + "\n" + traceback.format_exc())
    _write(report)
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        run()
    except Exception:
        log("the weekly run crashed:\n" + traceback.format_exc())
        raise
