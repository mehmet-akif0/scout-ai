"""Immutable, sourced metric observations and explicit, conservative calculations."""
import calendar
import hashlib
import json
import math
import re
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

LABELS = ('Company-reported','Independently corroborated','User-provided','Calculated')
SCENARIOS = ('Actual','Forecast','Target')
FREQUENCIES = ('Point','Monthly','Quarterly','Annual','Custom')
AVAILABILITY = ('Known','Unknown','N/A')
# Definitions are metadata, never demo observations or benchmarks.
BUILTINS = {
 'revenue':('Revenue','Recognized revenue for the stated period; not GMV.','currency'),
 'mrr':('MRR','Recurring monthly revenue at the stated date/period; exclude one-off revenue.','currency'),
 'arr':('Reported ARR','Annual recurring revenue explicitly reported by the source; not MRR × 12.','currency'),
 'annualized_mrr':('Annualized MRR','MRR × 12; an annualized run rate, not reported ARR.','currency'),
 'paying_customers':('Paying customers','Customers with a paid relationship under the stated population definition.','count'),
 'arpa':('ARPA/ARPU','Revenue per account/user; scope must state account versus user and revenue basis.','currency'),
 'customer_churn':('Customer churn','Lost starting customers / starting customers, for the stated period/cohort.','percent'),
 'revenue_churn':('Revenue churn','Revenue lost from the starting cohort / starting revenue; scope must state gross/net.','percent'),
 'retention':('Retention','Retained members of the stated starting population / starting population.','percent'),
 'grr':('GRR','(Starting cohort revenue − churn − contraction) / starting revenue.','percent'),
 'nrr':('NRR','(Starting cohort revenue − churn − contraction + expansion) / starting revenue.','percent'),
 'cac':('CAC','Acquisition costs / newly acquired paying customers; scope must state included costs.','currency'),
 'cac_payback':('CAC payback','CAC / (monthly ARPA × gross margin fraction), under constant unit economics.','months'),
 'gross_margin':('Gross margin','(Recognized revenue − cost of goods sold) / recognized revenue.','percent'),
 'ltv':('Estimated LTV','Monthly ARPA × gross margin fraction / monthly customer churn fraction; steady-state estimate.','currency'),
 'ltv_cac':('Estimated LTV/CAC','Steady-state gross-profit LTV divided by CAC; assumptions must be reviewed.','ratio'),
 'cash_balance':('Cash balance','Available cash on the measurement date, for the specified entity/scope.','currency'),
 'gross_burn':('Gross burn','Monthly cash outflows before cash inflows; not net burn.','currency'),
 'net_burn':('Net burn','Monthly cash outflows minus cash inflows; negative values mean net cash generation.','currency'),
 'runway':('Runway','Cash balance / monthly net burn; assumes constant positive burn.','months'),
 'dau':('DAU','Distinct active users during one day; state the active-user definition.','count'),
 'wau':('WAU','Distinct active users during the stated seven-day window.','count'),
 'mau':('MAU','Distinct active users during the stated monthly window.','count'),
 'activation':('Activation rate','Users reaching the specified activation event / eligible users.','percent'),
 'conversion':('Conversion rate','Users completing a defined conversion / eligible users in the same population.','percent'),
 'gmv':('GMV','Gross merchandise value of marketplace transactions; not company revenue.','currency'),
 'take_rate':('Take rate','Marketplace recognized revenue / GMV for a comparable transaction scope.','percent'),
 'transactions':('Transaction volume','Number of transactions, with completed/cancelled/refunded definition in scope.','count'),
 'funding_round':('Funding round amount','Disclosed amount of a single funding round on its date.','currency'),
 'valuation':('Disclosed valuation','Reported pre-money or post-money valuation; specify basis, never total funding.','currency'),
 'cohort_retention':('Cohort retention','Observed percentage retained for a named cohort and explicit age.','percent'),
 'cohort_start_revenue':('Starting cohort revenue','Revenue at the start of the same named customer cohort.','currency'),
 'cohort_churn':('Churned cohort revenue','Starting-cohort revenue lost to churn during the period.','currency'),
 'cohort_contraction':('Contracted cohort revenue','Starting-cohort revenue lost to contraction during the period.','currency'),
 'cohort_expansion':('Expanded cohort revenue','Expansion from the same starting cohort during the period.','currency'),
 'acquisition_spend':('Acquisition spend','Sales/marketing costs included in the acquisition definition.','currency'),
 'new_customers':('New paying customers','Newly acquired paying customers attributable to the stated costs/period.','count'),
 'cogs':('Cost of goods sold','COGS associated with the stated recognized revenue.','currency'),
 'cash_outflows':('Cash outflows','Monthly cash expenses for the stated entity/scope.','currency'),
 'cash_inflows':('Cash inflows','Monthly cash inflows for the same entity/scope; state financing inclusion.','currency'),
 'marketplace_revenue':('Marketplace revenue','Recognized marketplace revenue from the transactions included in GMV.','currency'),
}
FIELDS = ('metric_key','name','definition','value','unit','currency','period_start','period_end','frequency',
 'scope','cohort','cohort_age','cohort_age_unit','basis','scenario','availability','source_ref','accessed_on','published_on',
 'label','corroboration_ref','corroboration_basis','notes','round_name','formula','inputs')


def canonical(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or not math.isfinite(float(number)) or (number!=0 and float(number)==0):raise InvalidOperation()
        return format(number.normalize(),'f')
    except (InvalidOperation,ValueError):
        raise ValueError('Value must be a finite number; leave missing data Unknown, not zero.') from None


def next_period(row):
    end=date.fromisoformat(row['period_end'])
    return (end+timedelta(days=1)).isoformat()


def period_valid(start,end,frequency):
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    if a>b:raise ValueError('Period start must not follow period end.')
    if frequency=='Point' and a!=b:raise ValueError('Point measurements must use the same start and end date.')
    if frequency in ('Monthly','Quarterly','Annual'):
        months={'Monthly':1,'Quarterly':3,'Annual':12}[frequency]
        index=a.year*12+a.month-1+months
        year,month=divmod(index,12)
        expected=date(year,month+1,1)-timedelta(days=1)
        if a.day!=1 or b!=expected:raise ValueError('Use a complete calendar period for Monthly, Quarterly or Annual.')


class Metrics:
    def __init__(self,store):
        self.store=store
        with closing(store.connect()) as db,db:
            db.executescript('''BEGIN;
                CREATE TABLE IF NOT EXISTS metric_definitions (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metric_observations (
                    id INTEGER PRIMARY KEY, startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    supersedes INTEGER UNIQUE REFERENCES metric_observations(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(startup_id,fingerprint));
                CREATE TABLE IF NOT EXISTS metric_applicability (
                    startup_id INTEGER REFERENCES startups(id) ON DELETE CASCADE, metric_key TEXT,
                    applicable INTEGER NOT NULL, PRIMARY KEY(startup_id,metric_key));
                CREATE TABLE IF NOT EXISTS analysis_metric_snapshots (
                    analysis_id INTEGER REFERENCES analysis_versions(id) ON DELETE CASCADE,
                    observation_id INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(analysis_id,observation_id));
                CREATE TABLE IF NOT EXISTS ai_metric_proposals (
                    id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES research_jobs(id) ON DELETE CASCADE,
                    startup_id INTEGER NOT NULL REFERENCES startups(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'Pending', observation_id INTEGER REFERENCES metric_observations(id));
                COMMIT;''')
            for key,(name,definition,unit) in BUILTINS.items():
                db.execute('INSERT OR IGNORE INTO metric_definitions VALUES (?,?)',(key,json.dumps(dict(name=name,definition=definition,unit=unit))))

    def definitions(self):
        with closing(self.store.connect()) as db:
            return {r['key']:json.loads(r['payload']) for r in db.execute('SELECT * FROM metric_definitions ORDER BY key')}

    def define(self,key,name,definition,unit):
        if not re.fullmatch('[a-z][a-z0-9_]{1,79}',key) or not all(v.strip() for v in (name,definition,unit)):
            raise ValueError('Use a unique lowercase metric key, a name, definition and unit.')
        with closing(self.store.connect()) as db,db:
            if db.execute('SELECT key FROM metric_definitions WHERE key=?',(key,)).fetchone():raise ValueError('Metric key already exists; use a new key for a changed definition.')
            db.execute('INSERT INTO metric_definitions VALUES (?,?)',(key,json.dumps(dict(name=name.strip(),definition=definition.strip(),unit=unit.strip()))))

    def validate(self,raw,calculated=False):
        key=raw.get('metric_key','')
        definition=self.definitions().get(key)
        if not definition:raise ValueError('Unknown metric key. Create a custom definition first.')
        item={f:str(raw.get(f,'') or '').strip() for f in FIELDS if f not in ('value','inputs','cohort_age')}
        for field in ('name','definition','unit'):item[field]=item[field] or definition[field]
        item['currency']=item['currency'].upper()
        item['frequency']=item['frequency'] or 'Point'
        item['scenario']=item['scenario'] or 'Actual'
        item['availability']=item['availability'] or 'Known'
        item['label']=item['label'] or 'User-provided'
        item['basis']=item['basis'] or 'Not specified'
        if item['frequency'] not in FREQUENCIES or item['scenario'] not in SCENARIOS or item['availability'] not in AVAILABILITY or item['label'] not in LABELS:
            raise ValueError('Invalid period, scenario, availability or evidence label.')
        if item['basis'] not in ('Not specified','Gross','Net'):raise ValueError('Basis must be Not specified, Gross, or Net.')
        if item['unit']!=definition['unit']:raise ValueError('Unit must match the metric definition. Create a different key for a different unit.')
        if item['unit']=='currency':
            if (item['currency'] and not re.fullmatch('[A-Z]{3}',item['currency'])) or (item['availability']=='Known' and not item['currency']):raise ValueError('Known currency values need a three-letter currency code.')
        elif item['currency']:raise ValueError('Non-currency units must leave currency blank.')
        if not item['scope']:raise ValueError('Scope/population definition is required for comparability.')
        period_valid(item['period_start'],item['period_end'],item['frequency'])
        if key in ('funding_round','valuation') and item['frequency']!='Point':raise ValueError('Funding events and disclosed valuations require a dated Point measurement.')
        date.fromisoformat(item['accessed_on'])
        if item['published_on']:date.fromisoformat(item['published_on'])
        if not item['source_ref']:raise ValueError('A source URL or document reference is required, including for user-provided data.')
        if item['label']=='Independently corroborated' and not (item['corroboration_ref'] and item['corroboration_basis']):
            raise ValueError('Independent corroboration requires a second reference and supporting explanation.')
        if item['label']=='Calculated' and not calculated:raise ValueError('Use the calculation workflow to create Calculated metrics.')
        if item['availability']=='Known':
            if raw.get('value') in (None,''):raise ValueError('Missing value: choose Unknown or N/A instead of inventing zero.')
            item['value']=canonical(raw['value'])
            value=Decimal(item['value'])
            if item['unit']=='count' and (value<0 or value!=int(value)):raise ValueError('Counts must be nonnegative whole numbers.')
            if key=='gross_margin' and value>100:raise ValueError('Gross margin cannot exceed 100 percent.')
            if key in ('customer_churn','retention','cohort_retention','grr','activation','conversion','take_rate') and not 0<=value<=100:
                raise ValueError('This rate must be between 0 and 100 percent.')
        else:
            if raw.get('value') not in (None,''):raise ValueError('Unknown and N/A must not contain a numeric value.')
            item['value']=None
        item['cohort_age']=None
        if raw.get('cohort_age') not in (None,''):
            age=int(raw['cohort_age'])
            if age<0 or str(age)!=str(raw['cohort_age']):raise ValueError('Cohort age must be a nonnegative whole number.')
            if not item['cohort']:raise ValueError('Cohort age needs a cohort identifier.')
            if item['cohort_age_unit'] not in ('days','weeks','months','years'):raise ValueError('Cohort age needs explicit units: days, weeks, months, or years.')
            item['cohort_age']=age
        else:item['cohort_age_unit']=''
        item['inputs']=raw.get('inputs',[])
        if calculated and not(item['formula'] and item['inputs']):raise ValueError('Calculated metrics need a formula and input snapshots.')
        if not calculated and (item['formula'] or item['inputs']):raise ValueError('Formula and input snapshots are reserved for calculations.')
        if any(len(str(v))>50000 for v in item.values()):raise ValueError('Metric field too long.')
        return item

    def observations(self,startup_id,history=False):
        sql='SELECT o.* FROM metric_observations o WHERE startup_id=?'
        if not history:sql+=' AND NOT EXISTS (SELECT 1 FROM metric_observations newer WHERE newer.supersedes=o.id)'
        with closing(self.store.connect()) as db:
            rows=[dict(id=r['id'],startup_id=r['startup_id'],supersedes=r['supersedes'],**{'cohort_age_unit':'',**json.loads(r['payload'])}) for r in db.execute(sql+' ORDER BY id',(startup_id,))]
            current={r['id'] for r in db.execute('SELECT id FROM metric_observations o WHERE startup_id=? AND NOT EXISTS (SELECT 1 FROM metric_observations n WHERE n.supersedes=o.id)',(startup_id,))}
        def stale(inputs):
            return any((entry['observation'].get('id') not in current) or stale(entry['observation'].get('inputs',[])) for entry in inputs)
        for row in rows:row['inputs_stale']=stale(row['inputs'])
        return rows

    def add(self,startup_id,raw,supersedes=None,calculated=False,db=None):
        item=self.validate(raw,calculated)
        fingerprint=hashlib.sha256(json.dumps([item,supersedes],sort_keys=True).encode()).hexdigest()
        def insert(conn):
            duplicate=conn.execute('SELECT id FROM metric_observations WHERE startup_id=? AND fingerprint=?',(startup_id,fingerprint)).fetchone()
            if duplicate:return duplicate[0],False
            if supersedes is None:
                same=next((r['id'] for r in conn.execute('SELECT id,payload FROM metric_observations WHERE startup_id=?',(startup_id,)) if json.loads(r['payload'])==item),None)
                if same:return same,False
            if supersedes:
                previous=conn.execute('SELECT id FROM metric_observations WHERE id=? AND startup_id=?',(supersedes,startup_id)).fetchone()
                if not previous or conn.execute('SELECT id FROM metric_observations WHERE supersedes=?',(supersedes,)).fetchone():raise ValueError('Correction requires a current measurement from this company.')
            result=conn.execute('INSERT INTO metric_observations(startup_id,payload,fingerprint,supersedes) VALUES (?,?,?,?)',(startup_id,json.dumps(item),fingerprint,supersedes))
            return result.lastrowid,True
        if db is not None:return insert(db)
        with closing(self.store.connect()) as conn,conn:return insert(conn)

    def preview(self,startup_id,rows):
        seen={json.dumps({k:r[k] for k in FIELDS},sort_keys=True) for r in self.observations(startup_id,history=True)}
        result=[]
        comparable=list(self.observations(startup_id))
        for index,raw in enumerate(rows,1):
            try:
                item=self.validate(raw)
                encoded=json.dumps(item,sort_keys=True)
                action='Skip' if encoded in seen else 'Add'
                warning='Conflicting value for the same metric/period; retained separately' if item['availability']=='Known' and any(r['availability']=='Known' and signature(r)==signature(item) and (r['period_start'],r['period_end'])==(item['period_start'],item['period_end']) and r['value']!=item['value'] for r in comparable) else ''
                result.append(dict(row=index,action=action,error='',warning=warning,data=item));seen.add(encoded);comparable.append(item)
            except (ValueError,TypeError) as exc:result.append(dict(row=index,action='Error',error=str(exc),warning='',data=raw))
        return result

    def import_rows(self,startup_id,rows):
        counts=dict(added=0,skipped=0,errors=0)
        for row in self.preview(startup_id,rows):
            if row['action']=='Error':counts['errors']+=1
            elif row['action']=='Skip':counts['skipped']+=1
            else:
                _,created=self.add(startup_id,row['data']);counts['added' if created else 'skipped']+=1
        return counts

    def applicability(self,startup_id):
        with closing(self.store.connect()) as db:return {r['metric_key']:bool(r['applicable']) for r in db.execute('SELECT * FROM metric_applicability WHERE startup_id=?',(startup_id,))}

    def set_applicability(self,startup_id,relevant):
        with closing(self.store.connect()) as db,db:
            db.execute('DELETE FROM metric_applicability WHERE startup_id=?',(startup_id,))
            db.executemany('INSERT INTO metric_applicability VALUES (?,?,?)',[(startup_id,key,int(key in relevant)) for key in self.definitions()])

    @staticmethod
    def snapshot(db,analysis_id,ids,startup_id):
        # Explicit IDs selected by analyst; each snapshot includes source, definition and calculation lineage.
        for oid in ids:
            row=db.execute('SELECT payload FROM metric_observations WHERE id=? AND startup_id=?',(oid,startup_id)).fetchone()
            if not row:raise ValueError('Metric reference belongs to a different company or no longer exists.')
            db.execute('INSERT OR IGNORE INTO analysis_metric_snapshots VALUES (?,?,?)',(analysis_id,oid,row['payload']))

    def snapshots(self,analysis_id):
        with closing(self.store.connect()) as db:
            return [dict(observation_id=r['observation_id'],**{'cohort_age_unit':'',**json.loads(r['payload'])}) for r in db.execute('SELECT * FROM analysis_metric_snapshots WHERE analysis_id=?',(analysis_id,))]


def signature(row,scenario=True):
    fields=['metric_key','definition','unit','currency','frequency','scope','cohort','cohort_age_unit','basis']
    if scenario:fields.append('scenario')
    return tuple(row[f] for f in fields)


def chart_groups(rows):
    groups={}
    for r in rows:
        if r['availability']=='Known':groups.setdefault(signature(r),[]).append(r)
    result=[]
    for key,values in groups.items():
        values=sorted(values,key=lambda r:(r['period_end'],r['id']))
        periods={}
        for r in values:periods.setdefault((r['period_start'],r['period_end']),[]).append(r)
        conflicts={p for p,rs in periods.items() if len({r['value'] for r in rs})>1}
        result.append(dict(key=key,rows=values,conflicts=conflicts))
    return result


RECIPES={
 'Growth':['previous','current'], 'Annualized MRR':['mrr'], 'ARPA':['revenue','paying_customers'],
 'Gross margin':['revenue','cogs'], 'CAC':['acquisition_spend','new_customers'],
 'Net burn':['cash_outflows','cash_inflows'], 'Runway':['cash_balance','net_burn'],
 'GRR':['cohort_start_revenue','cohort_churn','cohort_contraction'],
 'NRR':['cohort_start_revenue','cohort_churn','cohort_contraction','cohort_expansion'],
 'CAC payback':['cac','arpa','gross_margin'], 'LTV':['arpa','gross_margin','customer_churn'],
 'LTV/CAC':['arpa','gross_margin','customer_churn','cac'], 'Take rate':['marketplace_revenue','gmv']}


def calculate(recipe,inputs):
    required=RECIPES[recipe]
    if set(inputs)!=set(required):raise ValueError('Insufficient data: required inputs: '+', '.join(required))
    rows=list(inputs.values());base=rows[0]
    if any(r['availability']!='Known' for r in rows):raise ValueError('Insufficient data: every input needs a known value.')
    if len({r.get('startup_id') for r in rows})>1:raise ValueError('Inputs must belong to the same company.')
    for field in ('scope','scenario','cohort','cohort_age','cohort_age_unit','basis'):
        if len({r[field] for r in rows})!=1:raise ValueError('Incompatible '+field+'; no silent mixing is allowed.')
    currencies={r['currency'] for r in rows if r['unit']=='currency'}
    if len(currencies)>1:raise ValueError('Different currencies cannot be combined without an explicit conversion dataset.')
    for role,r in inputs.items():
        if recipe!='Growth' and r['metric_key']!=role:raise ValueError('Input does not match required metric '+role)
        expected=BUILTINS.get(r['metric_key'])
        if expected and r['unit']!=expected[2]:raise ValueError('Input unit does not match its metric definition.')
    same_period=recipe not in ('Growth','Runway')
    if same_period and len({(r['period_start'],r['period_end'],r['frequency']) for r in rows})!=1:
        raise ValueError('Inputs must cover the same period and frequency.')
    nums={k:Decimal(r['value']) for k,r in inputs.items()}
    output_key=None;formula='';assumption='';frequency=base['frequency'];start=base['period_start'];end=base['period_end']
    def positive(key):
        if nums[key]<=0:raise ValueError('Undefined: '+key+' must be positive (zero denominator is not defined).')
    if recipe=='Growth':
        a,b=inputs['previous'],inputs['current']
        if signature(a)!=signature(b):raise ValueError('Growth requires the same metric definition, scope, unit, currency and frequency.')
        if a['frequency']=='Point' or next_period(a)!=b['period_start']:
            raise ValueError('Insufficient data: two consecutive comparable periods are required; point measurements cannot imply period growth.')
        if a['frequency']=='Custom' and (date.fromisoformat(a['period_end'])-date.fromisoformat(a['period_start']))!=(date.fromisoformat(b['period_end'])-date.fromisoformat(b['period_start'])):
            raise ValueError('Custom periods must have equal duration.')
        positive('previous');value=(nums['current']/nums['previous']-1)*100
        output_key='growth_'+a['metric_key'];name=a['name']+' period growth';definition='Change between two consecutive comparable '+a['frequency']+' periods.';unit='percent'
        start=b['period_start'];end=b['period_end'];formula='(current / previous − 1) × 100'
    elif recipe=='Annualized MRR':
        if base['frequency']!='Monthly':raise ValueError('Insufficient data: Monthly MRR is required.')
        value=nums['mrr']*12;output_key='annualized_mrr';formula='MRR × 12';assumption='Annualized run rate; not company-reported ARR.'
    elif recipe in ('ARPA','CAC','Take rate','Gross margin','Net burn'):
        if recipe=='ARPA':positive('paying_customers');value=nums['revenue']/nums['paying_customers'];output_key='arpa';formula='period revenue / paying customers'
        if recipe=='CAC':positive('new_customers');value=nums['acquisition_spend']/nums['new_customers'];output_key='cac';formula='acquisition spend / new paying customers'
        if recipe=='Take rate':positive('gmv');value=nums['marketplace_revenue']/nums['gmv']*100;output_key='take_rate';formula='marketplace revenue / GMV × 100'
        if recipe=='Gross margin':positive('revenue');value=(nums['revenue']-nums['cogs'])/nums['revenue']*100;output_key='gross_margin';formula='(revenue − COGS) / revenue × 100'
        if recipe=='Net burn':
            if base['frequency']!='Monthly':raise ValueError('Monthly cash flows are required.')
            value=nums['cash_outflows']-nums['cash_inflows'];output_key='net_burn';formula='monthly cash outflows − monthly cash inflows'
    elif recipe=='Runway':
        cash,burn=inputs['cash_balance'],inputs['net_burn'];positive('net_burn')
        if cash['frequency']!='Point' or burn['frequency']!='Monthly' or cash['period_end']!=burn['period_end']:
            raise ValueError('Insufficient data: cash on the same period-end date and monthly net burn required.')
        if nums['cash_balance']<0:raise ValueError('Cash balance must be nonnegative.')
        value=nums['cash_balance']/nums['net_burn'];output_key='runway';frequency='Point';start=end=cash['period_end'];formula='cash balance / monthly net burn';assumption='Assumes constant monthly net burn; excludes future funding or changes in spending.'
    elif recipe in ('NRR','GRR'):
        if not base['cohort']:raise ValueError('Insufficient data: the same explicit starting customer cohort is required.')
        positive('cohort_start_revenue')
        if any(v<0 for v in nums.values()) or nums['cohort_churn']+nums['cohort_contraction']>nums['cohort_start_revenue']:raise ValueError('Invalid starting-cohort revenue movements.')
        value=(nums['cohort_start_revenue']-nums['cohort_churn']-nums['cohort_contraction']+nums.get('cohort_expansion',0))/nums['cohort_start_revenue']*100
        output_key=recipe.lower();formula='(starting cohort revenue − churn − contraction'+(' + expansion' if recipe=='NRR' else '')+') / starting cohort revenue × 100'
    elif recipe in ('CAC payback','LTV','LTV/CAC'):
        if base['frequency']!='Monthly':raise ValueError('Insufficient data: all unit-economics inputs must be Monthly for the same period.')
        positive('arpa');positive('gross_margin')
        if nums['gross_margin']>100:raise ValueError('Gross margin cannot exceed 100%.')
        monthly_profit=nums['arpa']*nums['gross_margin']/100
        assumption='Constant monthly ARPA and gross margin; no discounting or cohort-age effects.'
        if recipe=='CAC payback':positive('cac');value=nums['cac']/monthly_profit;output_key='cac_payback';formula='CAC / (monthly ARPA × gross margin / 100)'
        else:
            positive('customer_churn')
            if nums['customer_churn']>100:raise ValueError('Customer churn cannot exceed 100%.')
            value=monthly_profit/(nums['customer_churn']/100);output_key='ltv';formula='monthly ARPA × (gross margin / 100) / (monthly customer churn / 100)';assumption+=' Assumes steady monthly customer churn; estimate, not a reported LTV.'
            if recipe=='LTV/CAC':positive('cac');value/=nums['cac'];output_key='ltv_cac';formula='[monthly ARPA × gross margin fraction / monthly churn fraction] / CAC'
    if recipe!='Growth':name,definition,unit=BUILTINS[output_key]
    result={**{k:base.get(k,'') for k in FIELDS},'metric_key':output_key,'name':name,'definition':definition,
        'value':canonical(value),'unit':unit,'currency':next(iter(currencies),'') if unit=='currency' else '',
        'period_start':start,'period_end':end,'frequency':frequency,'label':'Calculated','source_ref':'Input observation snapshots',
        'accessed_on':date.today().isoformat(),'published_on':'','corroboration_ref':'','corroboration_basis':'',
        'formula':formula,'inputs':[dict(role=k,observation=v) for k,v in inputs.items()],
        'notes':assumption,'scenario':('Forecast' if recipe in ('Runway','CAC payback','LTV','LTV/CAC') and base['scenario']=='Actual' else base['scenario']),'availability':'Known','cohort_age':None,'round_name':''}
    return result


def approve_metric_proposals(metrics,job_id,ids):
    with closing(metrics.store.connect()) as db,db:
        db.execute('BEGIN IMMEDIATE')
        for pid in ids:
            row=db.execute("SELECT * FROM ai_metric_proposals WHERE id=? AND job_id=? AND state='Pending'",(pid,job_id)).fetchone()
            if not row:continue
            oid,_=metrics.add(row['startup_id'],json.loads(row['payload']),db=db)
            db.execute("UPDATE ai_metric_proposals SET state='Approved',observation_id=? WHERE id=?",(oid,pid))
