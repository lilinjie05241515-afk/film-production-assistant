"""Read-only change hints, including SQLite WAL commits; no scans or migrations."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from . import __version__
from .projects import catalog_path


def database_stamp(path):
    result = []
    for name in (str(path), str(path) + '-wal'):
        try:
            s = Path(name).stat()
            result.append([name, s.st_size, s.st_mtime_ns, s.st_ctime_ns])
        except FileNotFoundError:
            result.append([name, None])
    return result


def freshness(root=None):
    catalog = catalog_path()
    stamps = database_stamp(catalog)
    roots = set()
    if root:
        roots.add(str(Path(root).resolve()))
    if catalog.is_file():
        with closing(sqlite3.connect(catalog.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
            roots.update(row[0] for row in conn.execute('SELECT root FROM projects'))
    for directory in sorted(roots):
        stamps.extend(database_stamp(Path(directory) / '.project/registry.sqlite3'))
    token = hashlib.sha256(json.dumps(stamps, ensure_ascii=False).encode()).hexdigest()
    return {'freshness_token': token, 'system_version': __version__}
