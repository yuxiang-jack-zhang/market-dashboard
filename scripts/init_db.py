"""Create the schema and, on an empty database, the starting Groups.

    .venv/bin/python scripts/init_db.py            # uses DATABASE_URL (or .env)

Safe to run again: tables are created only if missing, and seeding only
happens while there are no Groups.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, seed  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with db.connect() as conn:
        db.init_schema(conn)
        print("schema ready")
        print("seeded starting Groups" if seed.seed(conn) else "Groups already exist; not seeding")
        for g in db.list_groups(conn):
            print(f"  {g['kind']:<9} {g['name']:<16} {len(g['items'])} Symbols")


if __name__ == "__main__":
    main()
