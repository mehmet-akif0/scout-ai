import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from storage import Store
from profiles import Profiles

class ProfileUITest(unittest.TestCase):
    def test_profile_create_assess_change_and_delete(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'SCOUTAI_DB_PATH': str(Path(temp) / 'ui.db')}):
            store = Store()
            company = store.save(dict(name='Existing startup', status='New', stage='Unknown'))
            app = AppTest.from_file('app.py').run()
            def widget(kind, label):
                return next(w for w in getattr(app, kind) if w.label == label)
            widget('text_input', 'Profile name').set_value('My lens')
            widget('text_area', 'Target sectors').set_value('Climate')
            widget('selectbox', 'Target sectors priority').select('Required')
            widget('button', 'Save profile').click().run()
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            p = Profiles(store).list()[0]['id']
            widget('selectbox', 'Active Scouting Profile').select(p).run()
            self.assertEqual(Profiles(store).active_id(), p)
            widget('selectbox', 'Result').select('Unknown')
            widget('text_area', 'Rationale').set_value('Need more evidence')
            widget('button', 'Save assessment').click().run()
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            self.assertEqual(Profiles(store).state(p, company), 'Needs research')
            widget('selectbox', 'Filter by profile assessment').select('Not evaluated').run()
            self.assertFalse(any('Company' in w.value.columns for w in app.dataframe))
            widget('selectbox', 'Filter by profile assessment').select('All assessments').run()
            widget('selectbox', 'Profile to manage').select(p).run()
            widget('text_area', 'Target sectors').set_value('Climate, Energy')
            widget('button', 'Save profile').click().run()
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            self.assertEqual(Profiles(store).state(p, company), 'Review needed')
            self.assertTrue(any('Criteria have changed' in w.value for w in app.warning))
            widget('selectbox', 'Profile to manage').select(p).run()
            widget('checkbox', 'Delete this profile and its assessments; keep all startups.').check().run()
            widget('button', 'Delete profile').click().run()
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(Profiles(store).list(), [])
