"""Settings read from the environment.

On Vercel these are project environment variables. Locally they come from a
`.env` file at the project root (see README), which never overrides a variable
that is already set.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ON_VERCEL = bool(os.environ.get("VERCEL"))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


if not ON_VERCEL:
    _load_dotenv(ROOT / ".env")


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def dashboard_password() -> str | None:
    """The one password that unlocks editing. Editing is off when it's unset."""
    return os.environ.get("DASHBOARD_PASSWORD") or None


def session_secret() -> str | None:
    return os.environ.get("SESSION_SECRET") or None


# Vercel's filesystem is read-only except for /tmp, and yfinance keeps small
# sqlite caches (timezones, cookies) on disk.
YF_CACHE_DIR = str(Path(tempfile.gettempdir()) / "py-yfinance")
