"""Make a clean copy of the app to give to someone else:  share.bat  ->  jobhunter.zip

Everything personal stays behind. The zip holds the code and nothing else, so the person who
unpacks it starts with their own keys, their own profile, their own board sign-ins and an empty
job list - and cannot end up applying to jobs as you.
"""
import pathlib
import re
import sys
import zipfile

HERE = pathlib.Path(__file__).parent

# yours, never shared: secrets, sessions, your CV data, your job history, your generated CVs
PRIVATE = {".env", ".creds.json", "profile.json", "profile.previous.json", "settings.json", "db.sqlite", ".session.json", ".boards.json",
           # your face. It goes on your CV, so it is as personal as the CV - and a copy of the
           # app that carries it would put your photo on someone else's CV by default.
           "photo.jpg", "photo.png",
           # the write-ahead log holds the most recent job rows - it is the database too
           "db.sqlite-wal", "db.sqlite-shm",
           "signin.log", "srv.log", "srv.err.log",
           # what the weekly run did, including the jobs it applied to
           "auto.log", "auto_last.json"}
PRIVATE_DIRS = {".venv", "__pycache__", ".browser", "out", ".claude", ".git", "graphify-out",
                "backup"}
# rebuilt or irrelevant on the other machine
SKIP_SUFFIX = {".pyc", ".tmp", ".bak", ".zip", ".log", ".db"}
# working files that are not part of the app
SKIP_NAMES = {"audit.json", "research_ux.json", ".profile.test.json",
              ".profile.test.prev.json", ".auto.lock",
              # which provider was last found to be down HERE. Local, momentary and wrong on
              # anyone else's machine, where their keys and their luck are different.
              ".llm_down.json",
              # one ranking of one person's shortlist. Meaningless to anyone else, and stale the
              # moment their list differs - which it does, being their list.
              ".shortlist.json"}
NAME = "jobhunter"


def wanted(p):
    rel = p.relative_to(HERE)
    if any(part in PRIVATE_DIRS for part in rel.parts):
        return False
    if rel.name in PRIVATE or rel.name in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIX:
        return False
    return p.is_file()


# What a key looks like once it is out of .env: the provider prefixes, plus any NAME_KEY= with
# something long after it. Names alone are everywhere in the source and must not trip this, so a
# value is required.
SECRET = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[A-Za-z0-9_-]{20,}"
                    r"|xai-[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{16,}|r8_[A-Za-z0-9]{16,})"
                    r"|(?:API_)?KEY\s*[=:]\s*[\"\']?[A-Za-z0-9_\-]{24,}")
READABLE = {".py", ".html", ".css", ".js", ".json", ".md", ".txt", ".bat", ".cfg", ".ini", ".yml"}


def secrets_in(files):
    """-> [(file, line)] for anything that looks like a real key inside a file we would ship.

    The name list cannot catch this: the file is one of ours, it is meant to be in the zip, and
    the key is a line in the middle of it.
    """
    hits = []
    for f in files:
        if f.suffix.lower() not in READABLE:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if SECRET.search(line):
                hits.append(f"{f.relative_to(HERE).as_posix()}:{i}")
    return hits


def main():
    out = HERE / f"{NAME}.zip"
    files = sorted(p for p in HERE.rglob("*") if wanted(p))
    names = {p.relative_to(HERE).as_posix() for p in files}

    # Everything is checked BEFORE a byte is written. The zip used to be built first and
    # inspected after, so a failure left the leaking zip in the folder - and sending the zip is
    # the next thing you do.
    leaked = sorted(n for n in names if pathlib.PurePosixPath(n).name in PRIVATE
                    or any(part in PRIVATE_DIRS for part in pathlib.PurePosixPath(n).parts))
    assert not leaked, f"refusing to ship private files: {leaked}"
    found = secrets_in(files)
    assert not found, ("refusing to build: that looks like a real API key inside a file that "
                       f"would be shipped: {found}. Move it to .env.")
    for must in ("app.py", "llm.py", "scrape.py", "prefill.py", "run.bat", "requirements.txt",
                 "templates/dashboard.html", "templates/cv/classic.css"):
        assert must in names, f"missing from the package: {must}"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, pathlib.Path(NAME) / f.relative_to(HERE))
    # and once more against what the archive actually holds, not against the list we hoped it
    # was built from
    inside = [n for n in zipfile.ZipFile(out).namelist()
              if pathlib.PurePosixPath(n).name in PRIVATE]
    if inside:
        out.unlink(missing_ok=True)
        raise AssertionError(f"private files reached the zip, which has been deleted: {inside}")
    print(f"{out.name}: {len(files)} files, {out.stat().st_size / 1024:.0f} KB")
    print("Left out on purpose: your API keys, profile, job list, board sign-ins and CVs.")
    print("Send the zip. They unzip it anywhere and double-click run.bat.")


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
    main()
