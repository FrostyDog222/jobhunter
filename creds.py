"""Board passwords, encrypted to this Windows account.

Optional and off until you switch it on. What it buys: when a board session lapses at a moment
nobody is at the keyboard - the scheduled run, or the keep-alive every two hours - the app can
sign in again by itself instead of staying signed out until somebody notices.

What it is honest about:

* The file is encrypted with DPAPI, which ties it to this Windows user. Copied to another PC, or
  opened by another account, or lifted out of a backup, it is unreadable. That is the difference
  between a password sitting in a file on your Desktop and one only this logged-in account can
  read.
* It does NOT protect against something already running as you on this machine. Nothing stored
  on a computer does. If that is your threat, do not switch this on.
* A password is worth more than the session cookie beside it: it does not expire, it often opens
  other sites too, and it can change the account's email. That is why this is opt-in, per board,
  and why the app tries a saved sign-in at most once and then stops rather than retrying.

The value is never logged, never returned by any endpoint, and never leaves this machine except
as a POST to the board's own login form.
"""
import base64
import ctypes
import ctypes.wintypes as w
import json
import pathlib
import threading

HERE = pathlib.Path(__file__).parent
CREDS = HERE / ".creds.json"
_LOCK = threading.RLock()

# Mixed into the encryption so a blob is useless to anything but this app, and useless for a
# different board even within it - a stolen eJobs blob cannot be replayed as the Hipo one.
_APP = b"jobhunter board credentials v1:"

# Two failures and it stops trying. An unattended retry loop posting a wrong password is how an
# account gets locked, which is a great deal worse than being signed out.
MAX_FAILS = 2


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _in(data: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _out(blob: _BLOB) -> bytes:
    got = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return got


_UI_FORBIDDEN = 0x01          # never pop a Windows dialog: this runs unattended


def _protect(text: str, entropy: bytes) -> str:
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(_in(text.encode("utf-8"))), None,
            ctypes.byref(_in(entropy)), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError("Windows would not encrypt the credentials")
    return base64.b64encode(_out(out)).decode("ascii")


def _unprotect(blob64: str, entropy: bytes) -> str:
    out = _BLOB()
    raw = base64.b64decode(blob64)
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(_in(raw)), None,
            ctypes.byref(_in(entropy)), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
        # wrong Windows account, another machine, or a tampered file - all the same answer
        raise OSError("these saved credentials cannot be read on this account")
    return _out(out).decode("utf-8")


def _read():
    try:
        got = json.loads(CREDS.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(all_):
    # same write-then-replace as the profile: a half-written file here reads as "no credentials",
    # which silently turns the feature off
    tmp = CREDS.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_), encoding="utf-8")
    tmp.replace(CREDS)


def save(board, username, password):
    """Store one board's sign-in. Raises if Windows will not encrypt."""
    if not (username or "").strip() or not (password or ""):
        raise ValueError("both the username and the password are needed")
    ent = _APP + board.encode()
    with _LOCK:
        all_ = _read()
        all_[board] = {"user": _protect(username.strip(), ent),
                       "pass": _protect(password, ent), "fails": 0}
        _write(all_)


def get(board):
    """-> (username, password), or None when there is nothing usable saved.

    None also covers a file copied from another machine, which is the point of encrypting it.
    """
    with _LOCK:
        row = _read().get(board) or {}
    if not row.get("user") or int(row.get("fails", 0)) >= MAX_FAILS:
        return None
    ent = _APP + board.encode()
    try:
        return _unprotect(row["user"], ent), _unprotect(row["pass"], ent)
    except OSError:
        return None


def forget(board):
    with _LOCK:
        all_ = _read()
        if all_.pop(board, None) is None:
            return False
        if all_:
            _write(all_)
        else:
            CREDS.unlink(missing_ok=True)      # nothing left to keep, so leave no file behind
        return True


def note_failure(board):
    """A sign-in attempt that did not work. After MAX_FAILS the saved copy stops being used."""
    with _LOCK:
        all_ = _read()
        if board in all_:
            all_[board]["fails"] = int(all_[board].get("fails", 0)) + 1
            _write(all_)
            return all_[board]["fails"]
    return 0


def note_success(board):
    with _LOCK:
        all_ = _read()
        if board in all_ and all_[board].get("fails"):
            all_[board]["fails"] = 0
            _write(all_)


def status():
    """What the dashboard may know: which boards have a saved sign-in, and whether it is being
    used. Never the username, and obviously never the password."""
    with _LOCK:
        all_ = _read()
    return {b: {"saved": True, "fails": int(v.get("fails", 0)),
                "stopped": int(v.get("fails", 0)) >= MAX_FAILS}
            for b, v in all_.items() if v.get("user")}
