"""Turn one DATABASE_URL string into a Django DATABASES entry.

Examples:
    sqlite:///db.sqlite3
    postgres://user:pass@localhost:5432/resumewise
    oracle://user:pass@localhost:1521/XEPDB1
    mssql://user:pass@localhost:1433/resumewise

Switching database is only a change to this one setting. The matching Django
driver must be installed and the test suite run against it before you rely on it
(see DEPENDENCIES.md). SQL Server needs the `mssql-django` package.
"""

from urllib.parse import unquote, urlparse

_ENGINES = {
    "sqlite": "django.db.backends.sqlite3",
    "postgres": "django.db.backends.postgresql",
    "postgresql": "django.db.backends.postgresql",
    "oracle": "django.db.backends.oracle",
    "mssql": "mssql",
}


def parse_database_url(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ENGINES:
        raise ValueError("Unsupported database scheme %r. Use one of: %s" % (scheme, ", ".join(sorted(_ENGINES))))

    if scheme == "sqlite":
        # sqlite:///relative.db  or  sqlite:////absolute/path.db  or  sqlite://:memory:
        path = unquote(parsed.path)
        name = ":memory:" if parsed.netloc == ":memory:" or path in ("", "/:memory:") else path[1:]
        config = {"ENGINE": _ENGINES[scheme], "NAME": name}
        if name != ":memory:":
            # Several requests at once: wait up to 20 s for a write lock instead of failing, take the write lock
            # at the start of a transaction (no deadlock-style "database is locked"), and let readers continue
            # while someone writes (WAL mode).
            config["OPTIONS"] = {"timeout": 20, "transaction_mode": "IMMEDIATE",
                                 "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"}
        return config

    config = {
        "ENGINE": _ENGINES[scheme],
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port) if parsed.port else "",
    }
    if scheme == "mssql":
        config["OPTIONS"] = {"driver": "ODBC Driver 18 for SQL Server"}
    return config
