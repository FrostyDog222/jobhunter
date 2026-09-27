"""Make a clean copy of the app to give to someone else:  share.bat  ->  jobhunter.zip

Everything personal stays behind. The zip holds the code and nothing else, so the person who
unpacks it starts with their own keys, their own profile, their own board sign-ins and an empty
job list - and cannot end up applying to jobs as you.
"""
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).parent

# yours, never shared: secrets, sessions, your CV data, your job history, your generated CVs
PRIVATE = {".env", "profile.json", "settings.json", "db.sqlite", ".session.json", ".boards.json",
           "signin.log", "srv.log", "srv.err.log",
           # what the weekly run did, including the jobs it applied to
           "auto.log", "auto_last.json"}
PRIVATE_DIRS = {".venv", "__pycache__", ".browser", "out", ".claude", ".git", "graphify-out",
                "backup"}
# rebuilt or irrelevant on the other machine
SKIP_SUFFIX = {".pyc", ".tmp", ".bak", ".zip", ".log", ".db"}
# working files that are not part of the app
SKIP_NAMES = {"audit.json", "research_ux.json", ".profile.test.json"}
NAME = "jobhunter"


def wanted(p):
    rel = p.relative_to(HERE)
    if any(part in PRIVATE_DIRS for part in rel.parts):
        return False
    if rel.name in PRIVATE or rel.name in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIX:
        return False
    return p.is_file()


def main():
    out = HERE / f"{NAME}.zip"
    files = sorted(p for p in HERE.rglob("*") if wanted(p))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, pathlib.Path(NAME) / p.relative_to(HERE))
    names = {p.relative_to(HERE).as_posix() for p in files}
    leaked = sorted(n for n in names if pathlib.PurePosixPath(n).name in PRIVATE)
    assert not leaked, f"refusing to ship private files: {leaked}"
    for must in ("app.py", "llm.py", "scrape.py", "prefill.py", "run.bat", "requirements.txt",
                 "templates/dashboard.html", "templates/cv/classic.css"):
        assert must in names, f"missing from the package: {must}"
    print(f"{out.name}: {len(files)} files, {out.stat().st_size / 1024:.0f} KB")
    print("Left out on purpose: your API keys, profile, job list, board sign-ins and CVs.")
    print("Send the zip. They unzip it anywhere and double-click run.bat.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
