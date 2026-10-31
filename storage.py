"""SQLite storage and validation for ScoutAI (standard library only)."""
import csv
import io
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

STATUSES = ('New', 'Researching', 'Shortlisted', 'Passed')
STAGES = ('Idea', 'Pre-seed', 'Seed', 'Series A', 'Series B+', 'Bootstrapped', 'Unknown')
FIELDS = ('name', 'website', 'founders', 'sector', 'country', 'stage', 'description', 'sources', 'notes', 'status')
DEFAULT_DB = Path(__file__).parent / 'data' / 'scoutai.db'

class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('SCOUTAI_DB_PATH', DEFAULT_DB))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS startups (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, website TEXT NOT NULL,
                founders TEXT NOT NULL, sector TEXT NOT NULL, country TEXT NOT NULL,
                stage TEXT NOT NULL, description TEXT NOT NULL, sources TEXT NOT NULL,
                notes TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def list(self, name='', sector='', stage='', status=''):
        # Literal substring search: '%' and '_' are not treated as SQL wildcards.
        with closing(self.connect()) as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM startups ORDER BY id DESC')]
        return [r for r in rows if name.casefold() in r['name'].casefold()
                and (not sector or r['sector'] == sector)
                and (not stage or r['stage'] == stage)
                and (not status or r['status'] == status)]

    def save(self, values, record_id=None):
        item = {key: str(values.get(key, '')).strip() for key in FIELDS}
        if not item['name']:
            raise ValueError('Company name is required.')
        if item['status'] not in STATUSES or item['stage'] not in STAGES:
            raise ValueError('Choose a valid status and investment stage.')
        if any(len(value) > 20000 for value in item.values()):
            raise ValueError('Each field must be at most 20,000 characters.')
        for link in ([item['website']] if item['website'] else []) + item['sources'].splitlines():
            if not link.strip():
                continue
            parsed = urlparse(link.strip())
            if parsed.scheme not in ('http', 'https') or not parsed.netloc or any(c.isspace() for c in link.strip()):
                raise ValueError('Website and source links must be valid http:// or https:// URLs (one source per line).')
        with closing(self.connect()) as db, db:
            if record_id is None:
                result = db.execute(f"INSERT INTO startups ({','.join(FIELDS)}) VALUES ({','.join('?' for _ in FIELDS)})", tuple(item.values()))
                return result.lastrowid
            result = db.execute(f"UPDATE startups SET {','.join(f'{f}=?' for f in FIELDS)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", (*item.values(), record_id))
            if not result.rowcount:
                raise ValueError('This startup no longer exists. Refresh the list.')
            return record_id

    def delete(self, record_id):
        with closing(self.connect()) as db, db:
            if not db.execute('DELETE FROM startups WHERE id=?', (record_id,)).rowcount:
                raise ValueError('This startup no longer exists.')


def export_csv(rows):
    """UTF-8 BOM for spreadsheets; neutralize formula-like user-provided cells."""
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    headers = ('id', *FIELDS, 'created_at', 'updated_at')
    writer.writerow(headers)
    for row in rows:
        cells = []
        for field in headers:
            value = str(row.get(field, ''))
            if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return output.getvalue().encode('utf-8-sig')
