import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from storage import Store

class AppFlowTest(unittest.TestCase):
    def test_complete_personal_scouting_flow(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'SCOUTAI_DB_PATH': str(Path(temp) / 'ui.db')}):
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            def field(kind, label):
                return next(widget for widget in getattr(app, kind) if widget.label == label)
            def button(label):
                return next(widget for widget in app.button if widget.label == label)
            field('text_input', 'Company name *').set_value('Test Startup')
            field('text_input', 'Sector').set_value('Climate')
            field('text_input', 'Founders').set_value('Test Founder')
            button('Add startup').click().run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(Store().list()[0]['name'], 'Test Startup')
            # Browse tab appears before the creation tab in the element tree.
            edit_status = [w for w in app.selectbox if w.label == 'Status'][0]
            edit_status.set_value('Shortlisted')
            [w for w in app.text_area if w.label == 'Personal notes'][0].set_value('Follow up next week')
            button('Save changes').click().run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(Store().list()[0]['status'], 'Shortlisted')
            # A new Streamlit session reads the persisted data.
            reopened = AppTest.from_file('app.py').run()
            self.assertFalse(reopened.exception)
            self.assertEqual(len(reopened.dataframe[0].value), 1)
            field('text_input', 'Search company name').set_value('missing').run()
            self.assertFalse(any('Company' in w.value.columns for w in app.dataframe))
            field('text_input', 'Search company name').set_value('test').run()
            field('selectbox', 'Filter by sector').select('Climate').run()
            field('selectbox', 'Filter by stage').select('Unknown').run()
            field('selectbox', 'Filter by status').select('Shortlisted').run()
            self.assertEqual(len(app.dataframe[0].value), 1)
            field('checkbox', 'I understand. Delete this startup permanently.').check().run()
            button('Delete startup').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(Store().list(), [])
