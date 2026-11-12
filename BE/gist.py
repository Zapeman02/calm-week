import json
import subprocess

FILENAME = "calendar.ics"
BACKUP = "state.json"


def _gh(*args, stdin=None):
    done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip() or f"gh exited with {done.returncode}")
    return done.stdout


def upload(ics_text, backup_text, gist_id=None):
    """Upload calendar and state backup to the secret gist, creating it the first time. Returns the gist id."""
    if not gist_id:
        url = _gh("gist", "create", "--filename", FILENAME, "--desc", "Calm Week calendar", "-", stdin=ics_text)
        gist_id = url.strip().rstrip("/").split("/")[-1]
    payload = json.dumps({"files": {FILENAME: {"content": ics_text}, BACKUP: {"content": backup_text}}})
    _gh("api", "-X", "PATCH", f"gists/{gist_id}", "--input", "-", stdin=payload)
    return gist_id


def raw_url(gist_id):
    login = _gh("api", "user", "-q", ".login").strip()
    return f"https://gist.githubusercontent.com/{login}/{gist_id}/raw/{FILENAME}"
