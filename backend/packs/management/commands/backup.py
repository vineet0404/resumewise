"""Make a backup of the whole database (all people's data) and delete old backups.

    python manage.py backup                 # writes backups/resumewise-YYYYmmdd-HHMMSS.<sqlite3|dump>
    python manage.py backup --keep-days 30  # how long to keep old files (default BACKUP_KEEP_DAYS)
    python manage.py backup --verify FILE   # check that a backup file is readable

SQLite: a consistent copy made with SQLite's own backup call (safe while the site is running).
PostgreSQL: `pg_dump` custom format (restore with `pg_restore`). The server needs the postgres client tools.
Backup files contain personal data: keep them private, copy them OFF the server, and delete old ones.
Backups older than the 30-day promise still hold deleted people's data until they are removed, so keep
BACKUP_KEEP_DAYS at 30 or less (it is 14 by default).
"""

import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def make_backup(directory):
    db = settings.DATABASES["default"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    engine = db["ENGINE"]
    if engine.endswith("sqlite3"):
        target = directory / ("resumewise-%s.sqlite3" % stamp)
        source = sqlite3.connect(db["NAME"])
        try:
            dest = sqlite3.connect(str(target))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
    elif engine.endswith("postgresql"):
        target = directory / ("resumewise-%s.dump" % stamp)
        cmd = ["pg_dump", "-Fc", "-f", str(target), "-d", db["NAME"]]
        if db.get("HOST"):
            cmd += ["-h", db["HOST"]]
        if db.get("PORT"):
            cmd += ["-p", str(db["PORT"])]
        if db.get("USER"):
            cmd += ["-U", db["USER"]]
        env = dict(os.environ)
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = db["PASSWORD"]
        try:
            subprocess.run(cmd, check=True, env=env, capture_output=True, timeout=1800)
        except FileNotFoundError:
            raise CommandError("pg_dump is not installed on this machine (install the PostgreSQL client tools)")
        except subprocess.CalledProcessError as exc:
            raise CommandError("pg_dump failed: " + exc.stderr.decode("utf-8", "replace")[:300])
    else:
        raise CommandError("backup supports SQLite and PostgreSQL; use your database's own backup tool for " + engine)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def prune(directory, keep_days):
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for path in Path(directory).glob("resumewise-*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def verify(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise CommandError("backup file is missing or empty")
    if path.suffix == ".sqlite3":
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            users = conn.execute("SELECT COUNT(*) FROM auth_user").fetchone()[0]
        finally:
            conn.close()
        if ok != "ok":
            raise CommandError("backup is damaged: " + ok)
        return "sqlite backup is readable (%d accounts)" % users
    try:
        out = subprocess.run(["pg_restore", "--list", str(path)], check=True, capture_output=True, timeout=300)
    except FileNotFoundError:
        raise CommandError("pg_restore is not installed on this machine")
    except subprocess.CalledProcessError as exc:
        raise CommandError("backup is damaged: " + exc.stderr.decode("utf-8", "replace")[:300])
    return "postgres backup is readable (%d entries)" % len(out.stdout.splitlines())


class Command(BaseCommand):
    help = "Back up the database and delete old backups (run daily)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None, help="folder for backup files (default BACKUP_DIR)")
        parser.add_argument("--keep-days", type=int, default=None)
        parser.add_argument("--verify", metavar="FILE", help="only check a backup file, make nothing")

    def handle(self, *args, **options):
        if options["verify"]:
            self.stdout.write(verify(options["verify"]))
            return
        directory = options["dir"] or settings.BACKUP_DIR
        keep = options["keep_days"] if options["keep_days"] is not None else settings.BACKUP_KEEP_DAYS
        connection.close()  # a fresh connection for the copy
        target = make_backup(directory)
        message = verify(target)
        removed = prune(directory, keep)
        self.stdout.write("Backup written: %s (%d bytes). %s. Old backups removed: %d." % (target, target.stat().st_size, message, removed))
