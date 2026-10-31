"""Synthetic observations only: no real company numbers or live APIs."""
import copy
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from decimal import Decimal
from catalog import Catalog, HEADINGS, read_csv, map_csv
from storage import Store
from metrics import Metrics, calculate, chart_groups, approve_metric_proposals
from metrics_ui import chart_frame
from research import ResearchQueue
from research_provider import Limits
from test_research import fixture
from unittest.mock import patch,Mock

class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'metrics.db')
        self.sid=self.store.save(dict(name='Synthetic fixture company',website='https://startup.example',stage='Seed',status='New'))
        self.cat=Catalog(self.store);self.m=Metrics(self.store)

    def row(self,key='mrr',value='100',**kw):
        data=dict(metric_key=key,value=value,currency='USD',period_start='2026-01-01',period_end='2026-01-31',frequency='Monthly',
            scope='Synthetic test entity; paying accounts; constant definition',source_ref='Synthetic document fixture',accessed_on='2026-10-31',label='User-provided')
        data.update(kw)
        if self.m.definitions()[key]['unit']!='currency':data['currency']=''
        return data

    def obs(self,key='mrr',value='100',**kw):
        oid,_=self.m.add(self.sid,self.row(key,value,**kw))
        return next(r for r in self.m.observations(self.sid) if r['id']==oid)

    def test_unknown_na_zero_and_csv_validation_idempotence_conflicts(self):
        a=self.row(value='0')
        missing=self.row(value='',availability='Unknown')
        invalid=self.row(value='',availability='Known')
        conflict=self.row(value='200',source_ref='Another synthetic document')
        preview=self.m.preview(self.sid,[a,a,missing,invalid,conflict])
        self.assertEqual([r['action'] for r in preview],['Add','Skip','Add','Error','Add'])
        self.assertIn('Conflicting',preview[-1]['warning'])
        self.assertEqual(self.m.observations(self.sid),[])
        self.assertEqual(self.m.import_rows(self.sid,[a,a,missing,invalid,conflict]),dict(added=3,skipped=1,errors=1))
        self.assertEqual(self.m.import_rows(self.sid,[a,a,missing,invalid,conflict]),dict(added=0,skipped=4,errors=1))
        self.assertIsNone(next(r for r in self.m.observations(self.sid) if r['availability']=='Unknown')['value'])
        with self.assertRaises(ValueError):self.m.add(self.sid,self.row(value='0',availability='N/A'))
        with self.assertRaises(ValueError):self.m.add(self.sid,self.row(value='NaN'))
        with self.assertRaises(ValueError):self.m.add(self.sid,self.row(value='1e9999'))
        with self.assertRaises(ValueError):self.m.add(self.sid,self.row(currency=''))

    def test_growth_zero_missing_period_currency_and_definition(self):
        a=self.obs(value='100');b=self.obs(value='150',period_start='2026-02-01',period_end='2026-02-28')
        result=calculate('Growth',dict(previous=a,current=b))
        self.assertEqual(Decimal(result['value']),50)
        self.assertEqual(result['inputs'][0]['observation']['id'],a['id'])
        for changed in ({'value':'0'},{'currency':'EUR'},{'definition':'Different revenue definition'},{'scenario':'Forecast'}):
            with self.assertRaises(ValueError):calculate('Growth',dict(previous={**a,**changed},current=b))
        with self.assertRaises(ValueError):calculate('Growth',dict(previous=a,current={**b,'period_start':'2026-03-01','period_end':'2026-03-31'}))
        with self.assertRaises(ValueError):calculate('Growth',dict(current=b))

    def test_annualized_mrr_not_arr_and_marketplace_not_revenue(self):
        result=calculate('Annualized MRR',dict(mrr=self.obs(value='200')))
        self.assertEqual(result['metric_key'],'annualized_mrr');self.assertEqual(Decimal(result['value']),2400)
        self.assertIn('not company-reported ARR',result['notes'])
        gmv=self.obs('gmv','1000');rev=self.obs('marketplace_revenue','100')
        self.assertEqual(Decimal(calculate('Take rate',dict(gmv=gmv,marketplace_revenue=rev))['value']),10)
        with self.assertRaises(ValueError):calculate('ARPA',dict(revenue=gmv,paying_customers=self.obs('paying_customers','10')))

    def test_cohort_nrr_grr_and_incompatible_starting_group(self):
        inputs={key:self.obs(key,v,cohort='Synthetic Jan 2026 customers') for key,v in [('cohort_start_revenue','1000'),('cohort_churn','100'),('cohort_contraction','50'),('cohort_expansion','250')]}
        self.assertEqual(Decimal(calculate('NRR',inputs)['value']),110)
        self.assertEqual(Decimal(calculate('GRR',{k:v for k,v in inputs.items() if k!='cohort_expansion'})['value']),85)
        inputs['cohort_expansion']['cohort']='Different starting group'
        with self.assertRaises(ValueError):calculate('NRR',inputs)
        inputs['cohort_expansion']['cohort']='Synthetic Jan 2026 customers';inputs['cohort_start_revenue']['value']='0'
        with self.assertRaises(ValueError):calculate('NRR',inputs)

    def test_unit_economics_formula_sufficiency_and_runway(self):
        arpa=self.obs('arpa','100');margin=self.obs('gross_margin','80');churn=self.obs('customer_churn','2');cac=self.obs('cac','400')
        self.assertEqual(Decimal(calculate('CAC payback',dict(cac=cac,arpa=arpa,gross_margin=margin))['value']),5)
        ltv=calculate('LTV/CAC',dict(arpa=arpa,gross_margin=margin,customer_churn=churn,cac=cac))
        self.assertEqual(Decimal(ltv['value']),10);self.assertEqual(ltv['scenario'],'Forecast');self.assertIn('Assumes steady',ltv['notes'])
        with self.assertRaises(ValueError):calculate('LTV',dict(arpa=arpa,gross_margin=margin,customer_churn={**churn,'value':'0'}))
        with self.assertRaises(ValueError):calculate('CAC payback',dict(cac=cac,arpa=arpa))
        cash=self.obs('cash_balance','120000',frequency='Point',period_start='2026-01-31');burn=self.obs('net_burn','10000')
        runway=calculate('Runway',dict(cash_balance=cash,net_burn=burn))
        self.assertEqual(Decimal(runway['value']),12);self.assertIn('constant monthly net burn',runway['notes'])
        for change in ({'value':'0'},{'value':'-100'},{'currency':'EUR'},{'period_end':'2026-02-28'}):
            with self.assertRaises(ValueError):calculate('Runway',dict(cash_balance=cash,net_burn={**burn,**change}))

    def test_chart_points_match_observations_gaps_conflicts_and_scenarios(self):
        a=self.obs(value='100');c=self.obs(value='200',period_start='2026-03-01',period_end='2026-03-31')
        conflict=self.obs(value='105',source_ref='Conflicting synthetic document')
        forecast=self.obs(value='300',scenario='Forecast')
        unknown=self.obs(value='',availability='Unknown',period_start='2026-02-01',period_end='2026-02-28')
        groups=chart_groups(self.m.observations(self.sid))
        self.assertEqual(len(groups),2)
        actual=next(g for g in groups if g['rows'][0]['scenario']=='Actual')
        frame=chart_frame(actual)
        self.assertEqual(set(frame.ID),{a['id'],c['id'],conflict['id']})
        self.assertEqual(sorted(frame.Value),[100.0,105.0,200.0])
        self.assertNotIn('2026-02-28',set(frame.Date))
        self.assertTrue(actual['conflicts'])
        self.assertNotIn(unknown['id'],set(frame.ID))

    def test_metric_revisions_freeze_published_analysis_and_inputs(self):
        old=self.obs(value='100')
        content={HEADINGS[0]:dict(text='Synthetic analysis referencing an approved metric',label='Analyst interpretation',sources=[])}
        aid=self.cat.analysis(self.sid,'Metric snapshot fixture','2026-10-31',content,metric_ids=[old['id']])
        self.cat.publish(self.sid,aid)
        new_id,_=self.m.add(self.sid,self.row(value='999'),supersedes=old['id'])
        self.assertEqual([r['id'] for r in self.m.observations(self.sid)],[new_id])
        self.assertEqual(self.m.snapshots(aid)[0]['value'],'100')
        draft=self.cat.analysis(self.sid,'Revised analysis','2026-10-31',content,aid)
        self.assertEqual(self.m.snapshots(draft)[0]['value'],'100')
        self.cat.analysis(self.sid,'Revised analysis','2026-10-31',content,draft,metric_ids=[new_id])
        self.assertEqual(self.m.snapshots(draft)[0]['value'],'999');self.assertEqual(self.m.snapshots(aid)[0]['value'],'100')
        self.assertEqual(len(self.m.observations(self.sid,history=True)),2)

    def test_custom_definitions_and_mapped_csv(self):
        self.m.define('pilot_sites','Pilot sites','Sites running a paid pilot under a signed contract.','count')
        _,rows=read_csv('Indicator,Number,From,To,Population,Evidence,Access\\npilot_sites,3,2026-01-31,2026-01-31,Paid pilots,Synthetic document,2026-10-31\\n'.replace('\\n','\n'))
        mapped=map_csv(rows,dict(metric_key='Indicator',value='Number',period_start='From',period_end='To',scope='Population',source_ref='Evidence',accessed_on='Access'))
        self.assertEqual(self.m.import_rows(self.sid,mapped)['added'],1)
        self.m.set_applicability(self.sid,['pilot_sites'])
        self.assertFalse(self.m.applicability(self.sid)['mrr'])
        self.assertEqual(self.m.observations(self.sid)[0]['value'],'3')

    def test_ai_metrics_are_only_proposals_and_approved_snapshot_immutable(self):
        observed=self.obs(value='100')
        q=ResearchQueue(self.store);data=fixture()
        data['result']['metric_proposals']=[dict(measurement=dict(metric_key='mrr',value='200',unit='currency',currency='USD',period_start='2026-01-01',period_end='2026-01-31',frequency='Monthly',scope='Synthetic test entity; paying accounts; constant definition',cohort='',basis='Not specified',scenario='Actual',label='Company-reported',round_name='',notes='Mock AI metric'),sources=['https://startup.example'],corroboration_basis='')]
        provider=Mock();provider.run.return_value=data
        with patch('research.public_url',side_effect=lambda u:u):
            jid=q.enqueue([self.sid])[0];q.process_one(lambda _:provider)
        self.assertEqual(q.jobs()[0]['status'],'Completed')
        self.assertEqual(len(self.m.observations(self.sid)),1)
        proposals=q.cat.rows('SELECT * FROM ai_metric_proposals WHERE job_id=?',(jid,))
        self.assertEqual(len(proposals),1)
        approve_metric_proposals(self.m,jid,[proposals[0]['id']]);approve_metric_proposals(self.m,jid,[proposals[0]['id']])
        self.assertEqual(len(self.m.observations(self.sid)),2)
        aid=q.jobs()[0]['analysis_id']
        self.assertEqual(self.m.snapshots(aid)[0]['value'],'100')
        self.assertEqual(self.store.list()[0]['name'],'Synthetic fixture company')

    def test_corrected_calculation_inputs_require_recalculation_and_reverts_preserved(self):
        original=self.obs(value='100')
        result=calculate('Annualized MRR',dict(mrr=original))
        calc_id,_=self.m.add(self.sid,result,calculated=True)
        corrected,_=self.m.add(self.sid,self.row(value='200'),supersedes=original['id'])
        active=self.m.observations(self.sid)
        self.assertTrue(next(r for r in active if r['id']==calc_id)['inputs_stale'])
        reverted,_=self.m.add(self.sid,self.row(value='100'),supersedes=corrected)
        self.assertNotEqual(reverted,original['id'])
        self.assertEqual(next(r for r in self.m.observations(self.sid) if r['id']==reverted)['value'],'100')
        unknown=self.m.validate(self.row(value='',availability='Unknown',currency=''))
        self.assertEqual(unknown['currency'],'');self.assertIsNone(unknown['value'])
