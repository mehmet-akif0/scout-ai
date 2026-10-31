"""Additive catalog schema, evidence, immutable published analyses and bulk intake."""
import csv
import io
import hashlib
import json
from contextlib import closing
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import urlsplit
from storage import FIELDS, STAGES, STATUSES
from metrics import Metrics

SECTIONS = ('Overview', 'Product', 'Founders', 'Business Model', 'Target Customers', 'Traction', 'Funding', 'Market', 'Competitors')
HEADINGS = ('Problem and customer need', 'Product and value proposition', 'Market opportunity',
            'Competition and differentiation', 'Go-to-market', 'Traction and evidence', 'Team', 'Strengths', 'Risks and open questions')
LABELS = ('Company claim', 'Independently corroborated', 'Analyst interpretation')
MODELS = ('Unknown', 'B2B', 'B2C', 'B2B2C')


def domain(url):
    if not url:
        return ''
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in url):
            raise ValueError()
        host = parsed.hostname.encode('idna').decode().lower().rstrip('.')
        if '.' not in host or not all(part and all(c.isalnum() or c == '-' for c in part) for part in host.split('.')):
            raise ValueError()
        _ = parsed.port
        return host.removeprefix('www.')
    except (ValueError, UnicodeError):
        raise ValueError('Use a valid http:// or https:// company website URL.') from None


class Catalog:
    def __init__(self, store):
        self.store = store
        with closing(store.connect()) as db:
            db.executescript('''BEGIN;
                CREATE TABLE IF NOT EXISTS company_details (
                    startup_id INTEGER PRIMARY KEY REFERENCES startups(id) ON DELETE CASCADE,
                    business_model TEXT NOT NULL DEFAULT 'Unknown', research_status TEXT NOT NULL DEFAULT 'Not researched');
                CREATE TABLE IF NOT EXISTS evidence_sources (
                    id INTEGER PRIMARY KEY, startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                    url TEXT NOT NULL, published_on TEXT, accessed_on TEXT NOT NULL, origin TEXT NOT NULL, note TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS company_facts (
                    id INTEGER PRIMARY KEY, startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                    section TEXT NOT NULL, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analysis_series (
                    id INTEGER PRIMARY KEY, startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS analysis_versions (
                    id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES analysis_series(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, title TEXT NOT NULL, analyzed_on TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('Draft','Published')), content TEXT NOT NULL,
                    UNIQUE(series_id,version));
                CREATE TABLE IF NOT EXISTS watchlists (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS watchlist_members (
                    list_id INTEGER REFERENCES watchlists(id) ON DELETE CASCADE,
                    startup_id INTEGER REFERENCES startups(id) ON DELETE CASCADE, PRIMARY KEY(list_id,startup_id));
                CREATE TABLE IF NOT EXISTS research_selection (
                    startup_id INTEGER PRIMARY KEY REFERENCES startups(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS import_keys (
                    fingerprint TEXT PRIMARY KEY, startup_id INTEGER REFERENCES startups(id) ON DELETE CASCADE);
                COMMIT;''')
        Metrics(store)

    def rows(self, sql, args=()):
        with closing(self.store.connect()) as db:
            return [dict(r) for r in db.execute(sql, args)]

    def execute(self, sql, args=()):
        with closing(self.store.connect()) as db, db:
            return db.execute(sql, args).lastrowid

    def companies(self):
        return self.rows('''SELECT s.*, COALESCE(d.business_model,'Unknown') AS business_model,
            COALESCE(d.research_status,'Not researched') AS research_status
            FROM startups s LEFT JOIN company_details d ON d.startup_id=s.id ORDER BY s.id DESC''')

    def details(self, startup_id, model, research_status):
        if model not in MODELS or research_status not in ('Not researched', 'In progress', 'Researched'):
            raise ValueError('Invalid company metadata.')
        self.execute('INSERT OR REPLACE INTO company_details VALUES (?,?,?)', (startup_id, model, research_status))

    def source(self, startup_id, url, published, accessed, origin, note=''):
        domain(url)
        if origin not in ('Company', 'Independent', 'Other'):
            raise ValueError('Invalid source origin.')
        if published:
            date.fromisoformat(published)
        date.fromisoformat(accessed)
        return self.execute('INSERT INTO evidence_sources(startup_id,url,published_on,accessed_on,origin,note) VALUES (?,?,?,?,?,?)',
                            (startup_id, url.strip(), published or None, accessed, origin, note))

    def sources(self, startup_id):
        return self.rows('SELECT * FROM evidence_sources WHERE startup_id=? ORDER BY id', (startup_id,))

    def validate_claim(self, startup_id, claim):
        if claim.get('label') not in LABELS:
            raise ValueError('Choose a valid evidence label.')
        if not str(claim.get('text', '')).strip():
            raise ValueError('Claim or analysis text is required.')
        sources = {s['id']: s for s in self.sources(startup_id)}
        ids = claim.get('sources', [])
        if any(i not in sources for i in ids):
            raise ValueError('Sources must belong to this startup.')
        if claim['label'] != 'Analyst interpretation' and not ids:
            raise ValueError('Factual claims require at least one source.')
        if claim['label'] == 'Independently corroborated':
            if not any(sources[i]['origin'] == 'Independent' for i in ids) or not claim.get('basis', '').strip():
                raise ValueError('Independent corroboration requires an Independent source and an explanation of the supporting evidence.')
        return claim

    def fact(self, startup_id, section, claim, fact_id=None):
        if section not in SECTIONS:
            raise ValueError('Invalid section.')
        self.validate_claim(startup_id, claim)
        if fact_id:
            self.execute('UPDATE company_facts SET section=?,content=? WHERE id=? AND startup_id=?', (section, json.dumps(claim), fact_id, startup_id))
            return fact_id
        return self.execute('INSERT INTO company_facts(startup_id,section,content) VALUES (?,?,?)', (startup_id, section, json.dumps(claim)))

    def facts(self, startup_id):
        return [{**r, 'content': json.loads(r['content'])} for r in self.rows('SELECT * FROM company_facts WHERE startup_id=? ORDER BY id', (startup_id,))]

    def analyses(self, startup_id, reader=False):
        sql = '''SELECT v.* FROM analysis_versions v JOIN analysis_series s ON s.id=v.series_id WHERE s.startup_id=?'''
        if reader:
            sql += " AND v.status='Published' AND v.version=(SELECT MAX(x.version) FROM analysis_versions x WHERE x.series_id=v.series_id AND x.status='Published')"
        return [{**r, 'content': json.loads(r['content'])} for r in self.rows(sql + ' ORDER BY v.id DESC', (startup_id,))]

    def analysis(self, startup_id, title, analyzed_on, content, version_id=None, metric_ids=None):
        if not title.strip() or not any(c.get('text', '').strip() for c in content.values()):
            raise ValueError('An analysis needs a title and at least one populated section.')
        date.fromisoformat(analyzed_on)
        if set(content) - set(HEADINGS):
            raise ValueError('Invalid analysis section.')
        for claim in content.values():
            if claim.get('text', '').strip():
                self.validate_claim(startup_id, claim)
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('''SELECT v.* FROM analysis_versions v JOIN analysis_series s ON s.id=v.series_id
                WHERE v.id=? AND s.startup_id=?''', (version_id, startup_id)).fetchone() if version_id else None
            if version_id and not old:
                raise ValueError('Analysis version not found.')
            if old and old['status'] == 'Draft':
                db.execute('UPDATE analysis_versions SET title=?,analyzed_on=?,content=? WHERE id=?', (title, analyzed_on, json.dumps(content), version_id))
                if metric_ids is not None:
                    db.execute('DELETE FROM analysis_metric_snapshots WHERE analysis_id=?',(version_id,))
                    Metrics.snapshot(db,version_id,metric_ids,startup_id)
                return version_id
            series = old['series_id'] if old else db.execute('INSERT INTO analysis_series(startup_id) VALUES (?)', (startup_id,)).lastrowid
            number = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM analysis_versions WHERE series_id=?', (series,)).fetchone()[0]
            new_id = db.execute("INSERT INTO analysis_versions(series_id,version,title,analyzed_on,status,content) VALUES (?,?,?,?,'Draft',?)", (series, number, title.strip(), analyzed_on, json.dumps(content))).lastrowid
            if old and db.execute("SELECT name FROM sqlite_master WHERE name='ai_analysis_metadata'").fetchone():
                db.execute('INSERT INTO ai_analysis_metadata SELECT ?,job_id,generated_by,model,researched_on,identity,conflicts,profile_snapshot,profile_suggestions FROM ai_analysis_metadata WHERE analysis_id=?', (new_id,version_id))
            if metric_ids is not None:
                Metrics.snapshot(db,new_id,metric_ids,startup_id)
            elif old:
                db.execute('INSERT INTO analysis_metric_snapshots SELECT ?,observation_id,payload FROM analysis_metric_snapshots WHERE analysis_id=?',(new_id,version_id))
            return new_id

    def publish(self, startup_id, version_id):
        version = next((v for v in self.analyses(startup_id) if v['id'] == version_id), None)
        if not version or version['status'] != 'Draft':
            raise ValueError('Select an existing draft to publish.')
        for claim in version['content'].values():
            if claim.get('text', '').strip():
                self.validate_claim(startup_id, claim)
        self.execute("UPDATE analysis_versions SET status='Published' WHERE id=? AND status='Draft'", (version_id,))

    def lists(self):
        return self.rows('SELECT * FROM watchlists ORDER BY id')

    def save_list(self, name, list_id=None):
        if not name.strip():
            raise ValueError('List name is required.')
        if list_id:
            self.execute('UPDATE watchlists SET name=? WHERE id=?', (name.strip(), list_id))
            return list_id
        return self.execute('INSERT INTO watchlists(name) VALUES (?)', (name.strip(),))

    def set_members(self, list_id, startup_ids):
        with closing(self.store.connect()) as db, db:
            db.execute('DELETE FROM watchlist_members WHERE list_id=?', (list_id,))
            db.executemany('INSERT INTO watchlist_members VALUES (?,?)', [(list_id, i) for i in startup_ids])

    def prepare_import(self, incoming):
        seen = set()
        existing = self.companies()
        known = set()
        for company in existing:
            try:
                if company['website']:
                    known.add('domain:' + domain(company['website']))
            except ValueError:
                pass
        known.update(r['fingerprint'] for r in self.rows('SELECT fingerprint FROM import_keys'))
        preview = []
        for number, raw in enumerate(incoming, 1):
            item = {key: str(raw.get(key, '') or '').strip() for key in (*FIELDS, 'business_model')}
            error = ''
            try:
                if not item['name'] and not item['website']:
                    raise ValueError('Company name or website is required.')
                host = domain(item['website']) if item['website'] else ''
                item['name'] = item['name'] or host
                item['stage'] = item['stage'] or 'Unknown'
                item['status'] = item['status'] or 'New'
                item['business_model'] = item['business_model'] or 'Unknown'
                if item['stage'] not in STAGES or item['status'] not in STATUSES or item['business_model'] not in MODELS:
                    raise ValueError('Invalid stage, status, or business model.')
                if any(len(v) > 20000 for v in item.values()):
                    raise ValueError('Field exceeds 20,000 characters.')
                for link in item['sources'].splitlines():
                    if link.strip():
                        domain(link.strip())
                fingerprint = 'domain:' + host if host else 'row:' + hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
            except ValueError as exc:
                error = str(exc)
                fingerprint = ''
            duplicate = fingerprint in known or fingerprint in seen if fingerprint else False
            similar = any(SequenceMatcher(None, c['name'].casefold(), item['name'].casefold()).ratio() >= 0.85 for c in existing)
            preview.append(dict(row=number, item=item, fingerprint=fingerprint, action='Error' if error else 'Skip' if duplicate else 'Add', reason=error or ('Existing domain or repeated input' if duplicate else 'Similar name exists; kept separate' if similar else '')))
            if fingerprint:
                seen.add(fingerprint)
        return preview

    def import_rows(self, incoming):
        counts = dict(added=0, skipped=0, errors=0)
        # Serialize concurrent imports and recompute duplicates under the write lock.
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for row in self.prepare_import(incoming):
                if row['action'] != 'Add':
                    counts['errors' if row['action'] == 'Error' else 'skipped'] += 1
                    continue
                item = row['item']
                sid = db.execute(f"INSERT INTO startups ({','.join(FIELDS)}) VALUES ({','.join('?' for _ in FIELDS)})", tuple(item[f] for f in FIELDS)).lastrowid
                db.execute('INSERT INTO company_details VALUES (?,?,?)', (sid, item['business_model'], 'Not researched'))
                db.execute('INSERT INTO import_keys VALUES (?,?)', (row['fingerprint'], sid))
                counts['added'] += 1
        return counts

    def select_for_research(self, startup_ids):
        if len(startup_ids) != len(set(startup_ids)):
            raise ValueError('Select each startup only once.')
        with closing(self.store.connect()) as db, db:
            db.execute('DELETE FROM research_selection')
            db.executemany('INSERT INTO research_selection VALUES (?,?)', [(sid, position) for position, sid in enumerate(startup_ids)])


def read_csv(text):
    reader = csv.DictReader(io.StringIO(text), strict=True)
    columns = reader.fieldnames or []
    if not columns or any(not c.strip() for c in columns) or len(set(columns)) != len(columns):
        raise ValueError('CSV needs unique, nonempty column headers.')
    rows = list(reader)
    if len(rows) > 5000:
        raise ValueError('Import at most 5,000 rows at a time.')
    if any(None in row for row in rows):
        raise ValueError('A CSV row has more values than the header. Check delimiters and quoting.')
    return columns, rows


def map_csv(rows, mapping):
    return [{field: row.get(column, '') for field, column in mapping.items() if column != '(not mapped)'} for row in rows]
