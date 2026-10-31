"""Research screen tests with no live API calls."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from streamlit.testing.v1 import AppTest
from storage import Store
from research import ResearchQueue
from test_research import fixture

class ResearchUITests(unittest.TestCase):
    def test_missing_key_manual_app_still_works_and_no_jobs(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'SCOUTAI_DB_PATH':str(Path(temp)/'ui.db'),'SCOUTAI_AI_API_KEY':'','OPENAI_API_KEY':''}),patch('research_ui.start_worker') as worker:
            store=Store()
            sid=store.save(dict(name='Mock company',website='https://startup.example',stage='Unknown',status='New'))
            app=AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Research is not configured' in w.value for w in app.warning))
            self.assertTrue(next(w for w in app.button if w.label=='Research startup').disabled)
            self.assertEqual(ResearchQueue(store).jobs(),[])
            app.run()
            self.assertEqual(ResearchQueue(store).jobs(),[])
            worker.assert_not_called()
            self.assertEqual(len(store.list()),1)

    def test_explicit_single_job_mock_flow_and_refresh_no_resubmit(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'SCOUTAI_DB_PATH':str(Path(temp)/'ui.db'),'SCOUTAI_AI_API_KEY':'mock-key'}),patch('research_ui.start_worker',return_value=True) as worker,patch('research.public_url',side_effect=lambda u:u):
            store=Store();sid=store.save(dict(name='Mock company',website='https://startup.example',stage='Unknown',status='New'))
            app=AppTest.from_file('app.py').run()
            next(w for w in app.selectbox if w.label=='Company to research').select(sid).run()
            next(w for w in app.checkbox if w.label=='I understand paid APIs may be used and have reviewed the companies and limits.').check().run()
            next(w for w in app.button if w.label=='Research startup').click().run()
            self.assertFalse(app.exception)
            q=ResearchQueue(store)
            self.assertEqual(len(q.jobs()),1)
            provider=Mock();provider.run.return_value=fixture()
            q.process_one(lambda _:provider)
            app=AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            self.assertEqual(len(q.jobs()),1)
            worker.assert_called_once()
            next(w for w in app.selectbox if w.label=='Research result to review').select(q.jobs()[0]['id']).run()
            self.assertFalse(app.exception)
            self.assertTrue(any('AI-generated' in w.value for w in app.caption))
            self.assertEqual(q.cat.analyses(sid,reader=True),[])
