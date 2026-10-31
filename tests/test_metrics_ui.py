"""Streamlit rendering checks on synthetic metrics; no company research/API calls."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from storage import Store
from metrics import Metrics

class MetricUITests(unittest.TestCase):
    def test_manual_kpi_chart_and_calculation_without_api(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'SCOUTAI_DB_PATH':str(Path(temp)/'ui.db'),'SCOUTAI_AI_API_KEY':'','OPENAI_API_KEY':''}):
            store=Store();sid=store.save(dict(name='Synthetic UI company',stage='Seed',status='New'))
            app=AppTest.from_file('app.py').run()
            def widget(kind,label):return next(w for w in getattr(app,kind) if w.label==label)
            widget('selectbox','Metrics company').select(sid).run()
            self.assertFalse(app.exception)
            widget('selectbox','Metric definition').select('mrr').run()
            widget('text_input','Numeric value (blank for Unknown / N/A)').set_value('100')
            widget('text_input','Currency (three-letter code, currency units only)').set_value('USD')
            widget('text_area','Scope and population definition').set_value('Synthetic paid accounts')
            widget('text_input','Source URL or document reference').set_value('Synthetic source document')
            widget('button','Save measurement').click().run()
            self.assertFalse(app.exception)
            metrics=Metrics(store)
            self.assertEqual(metrics.observations(sid)[0]['value'],'100')
            # Reopen and choose company: persisted point observation produces a dated KPI.
            app=AppTest.from_file('app.py').run();widget('selectbox','Metrics company').select(sid).run()
            self.assertTrue(any(w.label=='MRR' and '100' in w.value for w in app.metric))
            self.assertTrue(any('Dated KPI' in w.value for w in app.caption))
            first=metrics.observations(sid)[0]
            second={**first,'value':'200','period_start':'2026-11-30','period_end':'2026-11-30'}
            metrics.add(sid,second)
            app=AppTest.from_file('app.py').run();widget('selectbox','Metrics company').select(sid).run()
            self.assertFalse(app.exception)
            self.assertTrue(len(app.get('arrow_vega_lite_chart'))>=1)
            self.assertTrue(any('Insufficient data' in w.value for w in app.info))

    def test_cohort_heatmap_only_observed_cells_and_funding_timeline(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'SCOUTAI_DB_PATH':str(Path(temp)/'ui.db')}):
            store=Store();sid=store.save(dict(name='Synthetic cohorts',stage='Seed',status='New'))
            from catalog import Catalog
            Catalog(store);m=Metrics(store)
            base=dict(source_ref='Synthetic retention worksheet',accessed_on='2026-10-31',scope='Paid starting cohorts',label='User-provided',period_start='2026-01-31',period_end='2026-01-31',frequency='Point')
            m.add(sid,dict(base,metric_key='cohort_retention',value='80',cohort='Synthetic January',cohort_age='1',cohort_age_unit='months'))
            m.add(sid,dict(base,metric_key='funding_round',value='1000000',currency='USD',round_name='Synthetic seed'))
            app=AppTest.from_file('app.py')
            app.query_params['view']='reader';app.query_params['startup']=str(sid);app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Funding timeline' in w.value for w in app.markdown))
            self.assertTrue(any('Observed cohort retention' in w.value for w in app.markdown))
            self.assertTrue(len(app.get('arrow_vega_lite_chart'))>=1)
