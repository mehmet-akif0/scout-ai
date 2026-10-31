import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from catalog import Catalog, HEADINGS
from storage import Store

class CatalogUITest(unittest.TestCase):
    def test_bulk_url_preview_commit_repeat_and_catalog_filters(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'SCOUTAI_DB_PATH': str(Path(temp) / 'ui.db')}):
            app = AppTest.from_file('app.py').run()
            def widget(kind, label):
                return next(w for w in getattr(app, kind) if w.label == label)
            widget('radio', 'Import method').set_value('Website URLs').run()
            widget('text_area', 'One company website URL per line').set_value('https://new.example\nhttps://www.new.example/about\nbad').run()
            self.assertEqual(Store().list(), [])
            widget('checkbox', 'I reviewed the preview. Add valid new rows and skip duplicates and errors.').check().run()
            widget('button', 'Import valid rows').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(Store().list()), 1)
            app = AppTest.from_file('app.py').run()
            self.assertFalse(app.exception)
            widget('text_input', 'Catalog company search').set_value('missing').run()
            self.assertFalse(any(w.label == 'Open company details' for w in app.get('link_button')))
            widget('text_input', 'Catalog company search').set_value('new').run()
            widget('selectbox', 'Catalog business model').select('B2C').run()
            self.assertTrue(any('No companies match' in w.value for w in app.info))

    def test_direct_reader_hides_drafts_and_local_editors(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'SCOUTAI_DB_PATH': str(Path(temp) / 'ui.db')}):
            store = Store()
            cat = Catalog(store)
            sid = store.save(dict(name='Reader company', stage='Unknown', status='New'))
            content = {HEADINGS[0]: dict(text='Visible published opinion', label='Analyst interpretation', sources=[])}
            published = cat.analysis(sid, 'Public title', '2026-10-31', content)
            cat.publish(sid, published)
            cat.analysis(sid, 'SECRET DRAFT TITLE', '2026-10-31', content, published)
            app = AppTest.from_file('app.py')
            app.query_params['view'] = 'reader'
            app.query_params['startup'] = str(sid)
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any(w.value == 'Reader company' for w in app.header))
            self.assertTrue(any('Public title' in w.label for w in app.expander))
            self.assertFalse(any('SECRET' in w.label for w in app.expander))
            self.assertFalse(any(w.label == 'Save draft' for w in app.button))

    def test_local_analysis_draft_publish_and_revise_flow(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'SCOUTAI_DB_PATH': str(Path(temp) / 'ui.db')}):
            store = Store()
            sid = store.save(dict(name='Local company', stage='Unknown', status='New'))
            def fresh():
                app = AppTest.from_file('app.py')
                app.query_params['startup'] = str(sid)
                return app.run()
            app = fresh()
            self.assertFalse(app.exception)
            next(w for w in app.text_input if w.label == 'Analysis title').set_value('Local draft')
            app.text_area(key=f'analysis_{sid}_0_{HEADINGS[0]}_text').set_value('Manual interpretation')
            next(w for w in app.button if w.label == 'Save draft').click().run()
            self.assertFalse(app.exception)
            cat = Catalog(store)
            draft = cat.analyses(sid)[0]
            self.assertEqual(cat.analyses(sid, reader=True), [])
            app = fresh()
            next(w for w in app.selectbox if w.label == 'Analysis version to edit').select(draft['id']).run()
            next(w for w in app.button if w.label == 'Publish saved draft').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(cat.analyses(sid, reader=True)[0]['title'], 'Local draft')
            app = fresh()
            next(w for w in app.selectbox if w.label == 'Analysis version to edit').select(draft['id']).run()
            next(w for w in app.text_input if w.label == 'Analysis title').set_value('Unpublished revision')
            next(w for w in app.button if w.label == 'Save draft').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(cat.analyses(sid)[0]['status'], 'Draft')
            self.assertEqual(cat.analyses(sid, reader=True)[0]['title'], 'Local draft')
