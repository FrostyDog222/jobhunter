"""Update the app to the latest version:  Update.bat

Your data is never touched. Only the app's own files are replaced, and the ones that were
replaced are copied into backup/ first, so a bad update can be undone by hand.

Two ways in, picked automatically:
  - a git checkout (the way the author works)     -> git pull
  - anything else, which is how it reaches you    -> download the current code from GitHub
"""
import hashlib
import io
import pathlib
import shutil
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).parent
REPO = "FrostyDog222/jobhunter"
BRANCH = "main"

sys.path.insert(0, str(HERE))
from share import PRIVATE, PRIVATE_DIRS          # noqa: E402  one list, so the two cannot drift

# Nothing here is ever written by an update, whatever arrives in the download.
KEEP = set(PRIVATE) | {"backup"}


def digest(path):
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.is_file() else None


def safe(rel):
    """Is this a path an update is allowed to write?"""
    # Parsed as a Windows path throughout: it understands both separators, so "..\\..\\x" is
    # seen as traversal rather than as one long filename, and "C:/x" is seen as absolute.
    win = pathlib.PureWindowsPath(rel)
    parts = win.parts
    # root as well as drive: Windows calls "/etc/passwd" rooted but not absolute, since it
    # names no drive - it would still land outside this folder.
    if not parts or ".." in parts or win.drive or win.root or win.is_absolute():
        return False                              # never climb out of the folder
    return not (set(parts) & (set(PRIVATE_DIRS) | KEEP))


def from_git():
    """-> True if this is a git checkout and the pull worked."""
    if not (HERE / ".git").is_dir():
        return False
    print("  This is a git checkout - pulling instead.\n")
    r = subprocess.run(["git", "pull", "--ff-only"], cwd=HERE, text=True,
                       capture_output=True)
    print((r.stdout or "").strip() or (r.stderr or "").strip())
    if r.returncode:
        print("\n  git could not fast-forward - you have local changes. Sort those out first.")
        return True                               # handled, even though nothing was updated
    return True


def download():
    """-> {path: bytes} of the current code, straight from GitHub."""
    import httpx
    url = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
    print(f"  Downloading the latest version from github.com/{REPO} ...")
    r = httpx.get(url, follow_redirects=True, timeout=120,
                  headers={"User-Agent": "jobhunter-update"})
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    out = {}
    for info in z.infolist():
        if info.is_dir() or "/" not in info.filename:
            continue
        rel = info.filename.split("/", 1)[1]       # strip the jobhunter-main/ wrapper
        if rel and safe(rel):
            out[rel] = z.read(info)
    if "app.py" not in out:
        raise RuntimeError("that download does not look like jobhunter - nothing was changed")
    return out


def apply(files):
    stamp = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-Date -Format yyyyMMdd-HHmm"],
                           capture_output=True, text=True).stdout.strip() or "update"
    backup = HERE / "backup" / stamp
    added, changed, same = [], [], 0

    for rel, data in sorted(files.items()):
        target = HERE / rel
        if target.is_file() and digest(target) == hashlib.sha1(data).hexdigest():
            same += 1
            continue
        # THIS script is being read line by line by cmd, from a byte offset, as it runs. Writing
        # over it makes execution resume at that offset in different text - a fragment of a line,
        # run as a command, in the middle of an update. The new copy waits beside it, and the
        # batch swaps it in at the top of the next run, which is what it already looks for.
        if rel.lower() == "update.bat":
            (HERE / "Update.bat.new").write_bytes(data)
            changed.append("Update.bat (arrives on the next run)")
            continue
        if target.is_file():
            backup.mkdir(parents=True, exist_ok=True)
            dest = backup / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)             # keep what we are about to overwrite
            changed.append(rel)
        else:
            added.append(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    for rel in changed + added:
        print(f"     {'updated' if rel in changed else 'new    '}  {rel}")
    print(f"\n  {len(changed)} updated, {len(added)} new, {same} already current.")
    if changed:
        print(f"  The previous versions are in  backup\\{stamp}")
    return changed + added


def main():
    print("\n  jobhunter - update\n")
    print("  Your API keys, profile, job list, applied history, board sign-ins and CVs")
    print("  are never touched by this.\n")

    if from_git():
        done()
        return
    try:
        files = download()
    except Exception as e:
        print(f"\n  Could not download the update: {type(e).__name__}: {e}")
        print("  Check the internet connection and try again. Nothing was changed.")
        done()
        return

    touched = apply(files)

    # Update.bat cannot safely overwrite itself while cmd is reading it line by line, so a new
    # one waits as Update.bat.new and the batch swaps it in at the start of the next run.
    newbat = HERE / "Update.bat.new"
    if newbat.exists() and digest(newbat) == digest(HERE / "Update.bat"):
        newbat.unlink()

    if "requirements.txt" in touched:
        print("\n  The dependencies changed - installing them...")
        py = HERE / ".venv" / "Scripts" / "python.exe"
        r = subprocess.run([str(py if py.exists() else sys.executable),
                            "-m", "pip", "install", "-q", "-r", str(HERE / "requirements.txt")])
        print("  done." if r.returncode == 0 else
              "  that failed - run FirstTimeSetup.bat to sort it out.")
    if touched:
        print("\n  Close the app's black window if it is open, then start it again with run.bat.")
    done()


def done():
    print()
    try:
        input("  Press Enter to close. ")
    except EOFError:
        pass


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
