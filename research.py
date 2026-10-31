"""Durable sequential research queue, atomic draft persistence and opt-in proposals."""
import hashlib
import json
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import date
from catalog import Catalog, HEADINGS, SECTIONS, MODELS, domain
from storage import FIELDS, STAGES
from profiles import Profiles
from research_provider import Limits, ResearchError, public_url, SCHEMA
from jsonschema import validate
from metrics import Metrics, BUILTINS, FIELDS as METRIC_FIELDS

PROMPT_VERSION = 2

class ResearchQueue:
    def __init__(self, store):
        self.store = store
        self.cat = Catalog(store)
        Profiles(store)
        with closing(store.connect()) as db:
            db.executescript('''BEGIN;
                CREATE TABLE IF NOT EXISTS research_jobs (
                    id INTEGER PRIMARY KEY, startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                    request_key TEXT NOT NULL, inputs TEXT NOT NULL, limits_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('Pending','Running','Completed','Failed')),
                    stopped INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, result TEXT,
                    analysis_id INTEGER REFERENCES analysis_versions(id) ON DELETE SET NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_research ON research_jobs(request_key) WHERE status IN ('Pending','Running');
                CREATE TABLE IF NOT EXISTS ai_analysis_metadata (
                    analysis_id INTEGER PRIMARY KEY REFERENCES analysis_versions(id) ON DELETE CASCADE,
                    job_id INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
                    generated_by TEXT NOT NULL, model TEXT NOT NULL, researched_on TEXT NOT NULL,
                    identity TEXT NOT NULL, conflicts TEXT NOT NULL, profile_snapshot TEXT, profile_suggestions TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research_proposals (
                    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
                    field TEXT NOT NULL, value TEXT NOT NULL, sources TEXT NOT NULL, reason TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'Pending');
                CREATE TABLE IF NOT EXISTS research_cache (
                    request_key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                COMMIT;''')

    def jobs(self):
        return self.cat.rows('SELECT j.*,s.name FROM research_jobs j JOIN startups s ON s.id=j.startup_id ORDER BY j.id DESC')

    def enqueue(self, startup_ids, limits=None, website=None, extra_urls=None, extra_text='', profile_id=None, fresh=False):
        limits = limits or Limits.environment()
        if not startup_ids or len(startup_ids) > limits.batch or len(startup_ids) != len(set(startup_ids)):
            raise ResearchError('Select unique companies within the configured batch limit.')
        extra_urls = extra_urls or []
        if len(extra_urls) > limits.sources or len(extra_text) > 20000:
            raise ResearchError('Too many extra URLs or more than 20,000 characters of context.')
        for url in extra_urls:
            public_url(url)
        companies = {c['id']: c for c in self.cat.companies()}
        profile = Profiles(self.store).get(profile_id)
        requests = []
        for sid in startup_ids:
            if sid not in companies:
                raise ResearchError('Company no longer exists.')
            company = companies[sid]
            target = website if len(startup_ids) == 1 and website else company['website']
            # Invalid companies are queued and fail individually; never block the rest of a batch.
            inputs = dict(startup_id=sid, name=company['name'], website=target, extra_urls=extra_urls,
                extra_text=extra_text, profile=profile, prompt_version=PROMPT_VERSION,
                metrics_snapshot=Metrics(self.store).observations(sid),metric_definitions={k:dict(name=v[0],definition=v[1],unit=v[2]) for k,v in BUILTINS.items()})
            fingerprint = hashlib.sha256(json.dumps([inputs, asdict(limits)],sort_keys=True).encode()).hexdigest()
            if fresh:
                fingerprint += ':' + uuid.uuid4().hex
            requests.append((sid, fingerprint, inputs))
        ids = []
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for sid, key, inputs in requests:
                existing = db.execute("SELECT id FROM research_jobs WHERE request_key=? AND (status IN ('Pending','Running') OR (status='Completed' AND updated_at>=datetime('now',?))) ORDER BY id DESC LIMIT 1", (key, f'-{limits.cache_hours} hours')).fetchone()
                if existing:
                    ids.append(existing[0]); continue
                ids.append(db.execute('INSERT INTO research_jobs(startup_id,request_key,inputs,limits_json,status) VALUES (?,?,?,?,?)',
                    (sid,key,json.dumps(inputs),json.dumps(asdict(limits)),'Pending')).lastrowid)
        return ids

    def recover_interrupted(self):
        # Called ONLY after the worker has the exclusive process lock, never on page refresh.
        self.cat.execute("UPDATE research_jobs SET status='Failed',error='Worker interrupted; retry explicitly. A previous API request may have been billed.',updated_at=CURRENT_TIMESTAMP WHERE status='Running'")

    def claim(self):
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM research_jobs WHERE status='Pending' AND stopped=0 ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE research_jobs SET status='Running',attempts=attempts+1,error='',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['id'],))
            return dict(row)

    def stop_pending(self):
        self.cat.execute("UPDATE research_jobs SET status='Failed',stopped=1,error='Stopped before execution',updated_at=CURRENT_TIMESTAMP WHERE status='Pending'")

    def retry(self, job_id):
        self.cat.execute("UPDATE research_jobs SET status='Pending',stopped=0,error='',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='Failed' AND NOT EXISTS (SELECT 1 FROM research_jobs active WHERE active.request_key=research_jobs.request_key AND active.status IN ('Pending','Running'))", (job_id,))

    def process_one(self, provider_factory):
        job = self.claim()
        if not job:
            return False
        try:
            limits = Limits(**json.loads(job['limits_json']))
            inputs = json.loads(job['inputs'])
            public_url(inputs['website'])
            cached = self.cat.rows("SELECT payload FROM research_cache WHERE request_key=? AND created_at>=datetime('now',?)", (job['request_key'],f'-{limits.cache_hours} hours'))
            payload = json.loads(job['result']) if job['result'] else json.loads(cached[0]['payload']) if cached else provider_factory(limits).run(inputs)
            payload.setdefault('researched_on', date.today().isoformat())
            self.validate_payload(inputs, payload, limits)
            # Save validated result before finalization: retries can finalize without calling the API again.
            self.cat.execute('UPDATE research_jobs SET result=? WHERE id=?', (json.dumps(payload),job['id']))
            self.finish(job, inputs, payload)
        except Exception as exc:
            # Never persist raw HTTP bodies/headers or exception repr that might contain secrets.
            error = str(exc)[:500] if isinstance(exc, ResearchError) else 'Research validation or persistence failed. Review inputs and retry.'
            self.cat.execute("UPDATE research_jobs SET status='Failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (error,job['id']))
        return True

    def validate_payload(self, inputs, payload, limits):
        result = payload['result']
        result.setdefault('metric_proposals',[])
        validate(result, SCHEMA)
        if not result['identity']['confirmed'] or result['identity']['domain'].lower().removeprefix('www.') != domain(inputs['website']):
            raise ResearchError('Company identity could not be confirmed for this domain. No draft created.')
        sources = result['sources']
        if not sources or len(sources) > limits.sources or len({s['url'] for s in sources}) != len(sources):
            raise ResearchError('Missing, duplicated, or excessive sources in AI output.')
        lookup = {s['url']:s for s in sources}
        for source in sources:
            public_url(source['url'])
            if source['url'] not in payload['citations'] or not source['evidence_quote'].strip():
                raise ResearchError('A source lacks tool-returned provenance or evidence excerpt.')
            if source['published_on']:
                date.fromisoformat(source['published_on'])
            source_host, company_host = domain(source['url']), domain(inputs['website'])
            if source['origin'] == 'Independent' and (source_host == company_host or source_host.endswith('.' + company_host)):
                raise ResearchError('Company-domain source cannot be independently classified.')
        def refs(urls):
            if any(url not in lookup for url in urls):
                raise ResearchError('An assertion cites a source outside the verified source set.')
        refs(result['identity']['sources'])
        if not any(domain(u) == domain(inputs['website']) for u in result['identity']['sources']):
            raise ResearchError('Identity needs a tool-returned company-domain source.')
        def claim(c):
            refs(c['sources'])
            if c['text'].strip() not in ('', 'Unknown') and not c['sources']:
                raise ResearchError('Factual claim has no sources.')
            if c['label'] == 'Independently corroborated' and (len(set(c['sources'])) < 2 or not c['basis'].strip() or not any(lookup[u]['origin']=='Independent' for u in c['sources'])):
                raise ResearchError('Independent corroboration has insufficient supporting evidence.')
        for fact in result['facts']:
            claim(fact['claim'])
        for c in result['analysis'].values():
            claim(c)
        for c in result['conflicts']:
            refs(c['sources'])
            if len(set(c['sources'])) < 2:
                raise ResearchError('Conflicting evidence must cite at least two sources.')
        for proposal in result['proposals']:
            refs(proposal['sources'])
            if not proposal['sources']:
                raise ResearchError('Proposed fact has no source.')
            if proposal['field'] == 'website':
                public_url(proposal['value'])
            if proposal['field'] == 'stage' and proposal['value'] not in STAGES:
                raise ResearchError('Invalid proposed stage.')
            if proposal['field'] == 'business_model' and proposal['value'] not in MODELS:
                raise ResearchError('Invalid proposed business model.')
        for proposal in result['metric_proposals']:
            refs(proposal['sources'])
            if not proposal['sources']:raise ResearchError('AI metric proposal has no retrieved source.')
            measurement=proposal['measurement']
            if measurement['value'] is None:raise ResearchError('Unknown metrics must not be proposed as numeric observations.')
            if measurement['label']=='Independently corroborated' and (len(proposal['sources'])<2 or not any(lookup[u]['origin']=='Independent' for u in proposal['sources'])):
                raise ResearchError('AI metric corroboration needs independent evidence.')
            Metrics(self.store).validate({**measurement,'source_ref':' | '.join(proposal['sources']),'accessed_on':payload.get('researched_on',date.today().isoformat()),
                'corroboration_ref':' | '.join(proposal['sources'][1:]),'corroboration_basis':proposal['corroboration_basis']})
        profile = inputs.get('profile')
        keys = {c['key'] for c in profile['criteria']} if profile else set()
        if {s['key'] for s in result['profile_suggestions']} != keys or len(result['profile_suggestions']) != len(keys):
            raise ResearchError('Profile suggestion does not match the captured profile.')
        for suggestion in result['profile_suggestions']:
            refs(suggestion['sources'])
            if suggestion['result'] != 'Unknown' and not suggestion['sources']:
                raise ResearchError('Profile recommendation lacks evidence.')

    def finish(self, job, inputs, payload):
        result = payload['result']
        today = payload.get('researched_on', date.today().isoformat())
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT analysis_id FROM research_jobs WHERE id=?', (job['id'],)).fetchone()
            if current['analysis_id']:
                db.execute("UPDATE research_jobs SET status='Completed' WHERE id=?", (job['id'],)); return
            source_ids = {}
            for source in result['sources']:
                source_ids[source['url']] = db.execute('INSERT INTO evidence_sources(startup_id,url,published_on,accessed_on,origin,note) VALUES (?,?,?,?,?,?)',
                    (job['startup_id'],source['url'],source['published_on'] or None,today,source['origin'],'AI-retrieved excerpt (review): '+source['evidence_quote'])).lastrowid
            def convert(c):
                if c['text'].strip() in ('', 'Unknown'):
                    return dict(text='Unknown',label='Analyst interpretation',sources=[],basis='')
                return {**c,'sources':[source_ids[u] for u in c['sources']]}
            content = {heading:convert(claim) for heading,claim in result['analysis'].items()}
            if result['conflicts']:
                c = content['Risks and open questions']
                c['text'] += '\nConflicting evidence:\n' + '\n'.join(x['topic']+': '+x['detail'] for x in result['conflicts'])
                c['label'] = 'Analyst interpretation'
                c['sources'] = list(set(c['sources'] + [source_ids[u] for x in result['conflicts'] for u in x['sources']]))
            series = db.execute('INSERT INTO analysis_series(startup_id) VALUES (?)',(job['startup_id'],)).lastrowid
            aid = db.execute("INSERT INTO analysis_versions(series_id,version,title,analyzed_on,status,content) VALUES (?,1,?,?,'Draft',?)", (series,'AI research · '+inputs['name'],today,json.dumps(content))).lastrowid
            db.execute('INSERT INTO ai_analysis_metadata VALUES (?,?,?,?,?,?,?,?,?)', (aid,job['id'],'AI-generated',payload['model'],today,json.dumps(result['identity']),json.dumps(result['conflicts']),json.dumps(inputs.get('profile')),json.dumps(result['profile_suggestions'])))
            for proposal in result['proposals']:
                if proposal['value'].strip() not in ('', 'Unknown'):
                    db.execute('INSERT INTO research_proposals(job_id,field,value,sources,reason) VALUES (?,?,?,?,?)', (job['id'],proposal['field'],proposal['value'],json.dumps([source_ids[u] for u in proposal['sources']]),proposal['reason']))
            # Detailed section findings remain reviewable proposals, never automatic company facts.
            for fact in result['facts']:
                if fact['claim']['text'].strip() not in ('','Unknown'):
                    db.execute('INSERT INTO research_proposals(job_id,field,value,sources,reason) VALUES (?,?,?,?,?)', (job['id'],'section:'+fact['section'],json.dumps(convert(fact['claim'])),json.dumps(convert(fact['claim'])['sources']),'AI-generated section finding; review before saving.'))
            for observation in inputs.get('metrics_snapshot',[]):
                db.execute('INSERT OR IGNORE INTO analysis_metric_snapshots VALUES (?,?,?)',(aid,observation['id'],json.dumps({k:observation[k] for k in METRIC_FIELDS})))
            for proposal in result.get('metric_proposals',[]):
                measurement=proposal['measurement']
                refs=proposal['sources']
                pub_dates={s['published_on'] for s in result['sources'] if s['url'] in refs and s['published_on']}
                proposed={**measurement,'source_ref':' | '.join(refs),'accessed_on':today,'published_on':next(iter(pub_dates)) if len(pub_dates)==1 else '',
                    'corroboration_ref':' | '.join(refs[1:]),'corroboration_basis':proposal['corroboration_basis']}
                db.execute('INSERT INTO ai_metric_proposals(job_id,startup_id,payload) VALUES (?,?,?)',(job['id'],job['startup_id'],json.dumps(proposed)))
            db.execute("UPDATE research_jobs SET status='Completed',analysis_id=?,error='',updated_at=CURRENT_TIMESTAMP WHERE id=?", (aid,job['id']))
            db.execute('INSERT OR REPLACE INTO research_cache VALUES (?,?,CURRENT_TIMESTAMP)', (job['request_key'],json.dumps(payload)))

    def apply_proposals(self, job_id, proposal_ids):
        with closing(self.store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM research_jobs WHERE id=? AND status='Completed'",(job_id,)).fetchone()
            if not job:
                raise ResearchError('Completed job required.')
            for pid in proposal_ids:
                proposal = db.execute("SELECT * FROM research_proposals WHERE id=? AND job_id=? AND state='Pending'",(pid,job_id)).fetchone()
                if not proposal:
                    continue
                field,value = proposal['field'],proposal['value']
                if field.startswith('section:'):
                    section = field.split(':',1)[1]
                    db.execute('INSERT INTO company_facts(startup_id,section,content) VALUES (?,?,?)',(job['startup_id'],section,value))
                elif field == 'business_model':
                    db.execute("INSERT INTO company_details(startup_id,business_model) VALUES (?,?) ON CONFLICT(startup_id) DO UPDATE SET business_model=excluded.business_model",(job['startup_id'],value))
                elif field in FIELDS:
                    db.execute(f'UPDATE startups SET {field}=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(value,job['startup_id']))
                db.execute("UPDATE research_proposals SET state='Applied' WHERE id=?",(pid,))
