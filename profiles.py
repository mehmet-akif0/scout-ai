"""Versioned profile criteria and manual assessments, separate from company facts."""
import json
from datetime import date
from contextlib import closing
from urllib.parse import urlparse

RESULTS = ('Unknown', 'Meets', 'Does not meet')
PRIORITIES = ('Required', 'Preferred')
ASSESSMENT_STATES = ('Not evaluated', 'Review needed', 'Does not meet required criteria',
                     'Needs research', 'Meets required criteria', 'Reviewed (no required criteria)', 'No criteria configured')

class Profiles:
    def __init__(self, store):
        self.store = store
        with closing(store.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS scouting_profiles (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS profile_versions (
                    profile_id INTEGER NOT NULL REFERENCES scouting_profiles(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, criteria TEXT NOT NULL,
                    PRIMARY KEY(profile_id, revision));
                CREATE TABLE IF NOT EXISTS assessments (
                    profile_id INTEGER NOT NULL, startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, responses TEXT NOT NULL,
                    PRIMARY KEY(profile_id, startup_id, revision),
                    FOREIGN KEY(profile_id, revision) REFERENCES profile_versions(profile_id, revision) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS workspace_settings (key TEXT PRIMARY KEY, value TEXT);
            ''')

    def list(self):
        with closing(self.store.connect()) as db:
            rows = db.execute('''SELECT p.*, v.criteria FROM scouting_profiles p JOIN profile_versions v
                ON p.id=v.profile_id AND p.revision=v.revision ORDER BY p.id''').fetchall()
        return [{**dict(row), 'criteria': json.loads(row['criteria'])} for row in rows]

    def get(self, profile_id):
        return next((p for p in self.list() if p['id'] == profile_id), None)

    def save(self, name, criteria, profile_id=None):
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError('Profile name is required (at most 200 characters).')
        cleaned = []
        for criterion in criteria:
            item = {k: str(criterion.get(k, '')).strip() for k in ('key', 'label', 'value', 'priority')}
            if not item['value']:
                continue  # Blank criteria never constrain a company.
            if not item['key'] or not item['label'] or item['priority'] not in PRIORITIES:
                raise ValueError('Each criterion needs a name and Required or Preferred priority.')
            if any(len(v) > 20000 for v in item.values()):
                raise ValueError('Criteria must be at most 20,000 characters each.')
            cleaned.append(item)
        if len({c['key'] for c in cleaned}) != len(cleaned):
            raise ValueError('Criterion identifiers must be unique.')
        encoded = json.dumps(sorted(cleaned, key=lambda c: c['key']), sort_keys=True)
        with closing(self.store.connect()) as db, db:
            if profile_id is None:
                profile_id = db.execute('INSERT INTO scouting_profiles(name,revision) VALUES (?,1)', (name,)).lastrowid
                revision = 1
            else:
                row = db.execute('SELECT revision FROM scouting_profiles WHERE id=?', (profile_id,)).fetchone()
                if row is None:
                    raise ValueError('Profile no longer exists.')
                revision = row['revision']
                previous = db.execute('SELECT criteria FROM profile_versions WHERE profile_id=? AND revision=?', (profile_id, revision)).fetchone()[0]
                if previous != encoded:
                    revision += 1
                db.execute('UPDATE scouting_profiles SET name=?,revision=? WHERE id=?', (name, revision, profile_id))
            db.execute('INSERT OR IGNORE INTO profile_versions VALUES (?,?,?)', (profile_id, revision, encoded))
        return profile_id

    def activate(self, profile_id):
        if profile_id is not None and not self.get(profile_id):
            raise ValueError('Profile no longer exists.')
        with closing(self.store.connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO workspace_settings VALUES ('active_profile',?)", (str(profile_id) if profile_id else '',))

    def active_id(self):
        with closing(self.store.connect()) as db:
            row = db.execute("SELECT value FROM workspace_settings WHERE key='active_profile'").fetchone()
        value = int(row[0]) if row and row[0] else None
        return value if self.get(value) else None

    def delete(self, profile_id):
        with closing(self.store.connect()) as db, db:
            db.execute('DELETE FROM scouting_profiles WHERE id=?', (profile_id,))
            db.execute("DELETE FROM workspace_settings WHERE key='active_profile' AND value=?", (str(profile_id),))

    def assess(self, profile_id, startup_id, revision, responses):
        profile = self.get(profile_id)
        if not profile or profile['revision'] != revision:
            raise ValueError('Criteria changed. Reload the profile before assessing.')
        if not profile['criteria']:
            raise ValueError('Add criteria before assessing startups.')
        if set(responses) != {c['key'] for c in profile['criteria']}:
            raise ValueError('Provide a result for every current criterion.')
        cleaned = {}
        for key, response in responses.items():
            result = response.get('result')
            if result not in RESULTS:
                raise ValueError('Choose Meets, Does not meet, or Unknown.')
            rationale = str(response.get('rationale', '')).strip()
            source = str(response.get('source', '')).strip()
            if source:
                parsed = urlparse(source)
                if parsed.scheme not in ('http', 'https') or not parsed.netloc or any(c.isspace() for c in source):
                    raise ValueError('Source URL must be an http:// or https:// URL.')
            day = date.fromisoformat(str(response.get('date', ''))).isoformat()
            cleaned[key] = dict(result=result, rationale=rationale, source=source, date=day)
        with closing(self.store.connect()) as db, db:
            # Recheck inside the write transaction to reject stale sessions.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM scouting_profiles WHERE id=?', (profile_id,)).fetchone()
            if not row or row[0] != revision:
                raise ValueError('Criteria changed. Reload before saving.')
            if not db.execute('SELECT id FROM startups WHERE id=?', (startup_id,)).fetchone():
                raise ValueError('Startup no longer exists.')
            db.execute('INSERT OR REPLACE INTO assessments VALUES (?,?,?,?)', (profile_id, startup_id, revision, json.dumps(cleaned)))

    def history(self, profile_id, startup_id):
        with closing(self.store.connect()) as db:
            rows = db.execute('''SELECT a.revision,a.responses,v.criteria FROM assessments a JOIN profile_versions v
                ON a.profile_id=v.profile_id AND a.revision=v.revision
                WHERE a.profile_id=? AND a.startup_id=? ORDER BY a.revision DESC''', (profile_id, startup_id)).fetchall()
        return [dict(revision=r['revision'], responses=json.loads(r['responses']), criteria=json.loads(r['criteria'])) for r in rows]

    def state(self, profile_id, startup_id):
        profile = self.get(profile_id)
        if not profile:
            return 'Not evaluated'
        history = self.history(profile_id, startup_id)
        if history and history[0]['revision'] != profile['revision']:
            return 'Review needed'
        if not profile['criteria']:
            return 'No criteria configured'
        if not history:
            return 'Not evaluated'
        responses = history[0]['responses']
        required = [c for c in profile['criteria'] if c['priority'] == 'Required']
        if any(responses[c['key']]['result'] == 'Does not meet' for c in required):
            return 'Does not meet required criteria'
        if any(responses[c['key']]['result'] == 'Unknown' for c in required):
            return 'Needs research'
        if required:
            return 'Meets required criteria'
        return 'Reviewed (no required criteria)'
