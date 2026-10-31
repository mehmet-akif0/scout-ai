import tempfile
import unittest
from pathlib import Path
from catalog import Catalog, domain, HEADINGS, read_csv, map_csv
from storage import Store
from profiles import Profiles
from test_profiles import criterion, response

class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'catalog.db')
        self.sid = self.store.save(dict(name='Existing', website='https://www.existing.example/path', notes='Keep private notes', stage='Seed', status='New'))
        self.profiles = Profiles(self.store)
        self.pid = self.profiles.save('Keep profile', [criterion()])
        self.profiles.assess(self.pid, self.sid, 1, {'sector': response('Meets')})
        self.original = self.store.list()
        self.cat = Catalog(self.store)

    def test_additive_schema_and_existing_profile_preservation(self):
        Catalog(self.store)
        self.assertEqual(self.store.list(), self.original)
        self.assertEqual(self.profiles.state(self.pid, self.sid), 'Meets required criteria')
        self.assertEqual(self.cat.companies()[0]['business_model'], 'Unknown')
        self.cat.details(self.sid, 'B2B', 'Researched')
        self.assertEqual(self.cat.companies()[0]['business_model'], 'B2B')

    def test_source_claims_and_independent_evidence(self):
        company = self.cat.source(self.sid, 'https://existing.example/news', '', '2026-10-31', 'Company')
        independent = self.cat.source(self.sid, 'https://news.example/story', '2026-10-20', '2026-10-31', 'Independent')
        claim = dict(text='A sourced claim', label='Independently corroborated', sources=[company], basis='Supporting basis')
        with self.assertRaises(ValueError):
            self.cat.fact(self.sid, 'Traction', claim)
        claim['sources'] = [independent]
        claim['basis'] = ''
        with self.assertRaises(ValueError):
            self.cat.fact(self.sid, 'Traction', claim)
        claim['basis'] = 'Independent report supports the statement.'
        key = self.cat.fact(self.sid, 'Traction', claim)
        self.cat.fact(self.sid, 'Traction', {**claim, 'text': 'Updated evidence'}, key)
        self.assertEqual(self.cat.facts(self.sid)[0]['content']['text'], 'Updated evidence')
        self.assertIsNone(self.cat.sources(self.sid)[0]['published_on'])
        other = self.store.save(dict(name='Other', stage='Unknown', status='New'))
        with self.assertRaises(ValueError):
            self.cat.fact(other, 'Market', claim)

    def test_published_immutable_versions_and_multiple_dated_analyses(self):
        content = {HEADINGS[0]: dict(text='Initial interpretation', label='Analyst interpretation', sources=[])}
        draft = self.cat.analysis(self.sid, 'Research memo', '2026-10-30', content)
        self.assertEqual(self.cat.analyses(self.sid, reader=True), [])
        self.cat.publish(self.sid, draft)
        second = self.cat.analysis(self.sid, 'Revised memo', '2026-10-31', {HEADINGS[0]: {**content[HEADINGS[0]], 'text': 'New draft opinion'}}, draft)
        self.assertNotEqual(second, draft)
        reader = self.cat.analyses(self.sid, reader=True)
        self.assertEqual(reader[0]['title'], 'Research memo')
        self.assertEqual(reader[0]['content'], content)
        self.assertEqual(next(v for v in self.cat.analyses(self.sid) if v['id'] == second)['status'], 'Draft')
        self.cat.publish(self.sid, second)
        self.assertEqual(self.cat.analyses(self.sid, reader=True)[0]['id'], second)
        third = self.cat.analysis(self.sid, 'Separate study', '2026-10-31', content)
        self.cat.publish(self.sid, third)
        self.assertEqual(len(self.cat.analyses(self.sid, reader=True)), 2)
        self.assertEqual(len(self.cat.analyses(self.sid)), 3)

    def test_lists_are_separate_from_companies(self):
        key = self.cat.save_list('Favorites')
        self.cat.set_members(key, [self.sid])
        self.cat.save_list('Watch next', key)
        self.assertEqual(self.cat.lists()[0]['name'], 'Watch next')
        self.cat.set_members(key, [])
        self.assertEqual(self.cat.rows('SELECT * FROM watchlist_members'), [])
        self.cat.set_members(key, [self.sid])
        self.cat.execute('DELETE FROM watchlists WHERE id=?', (key,))
        self.assertEqual(self.store.list(), self.original)
        self.assertEqual(self.cat.rows('SELECT * FROM watchlist_members'), [])

    def test_import_preview_idempotence_no_overwrite_and_domain_rules(self):
        rows = [dict(name='Overwrite?', website='https://existing.example/other'),
                dict(website='https://WWW.NEW.example/a'), dict(website='http://new.example/b'),
                dict(name='Existing', website='https://different.example'), dict(name='Name only'),
                dict(website='not a URL'), {}, dict(name='Invalid stage', stage='Bad')]
        preview = self.cat.prepare_import(rows)
        self.assertEqual([r['action'] for r in preview], ['Skip', 'Add', 'Skip', 'Add', 'Add', 'Error', 'Error', 'Error'])
        self.assertEqual(len(self.store.list()), 1)  # Preview never writes.
        self.assertEqual(self.cat.import_rows(rows), dict(added=3, skipped=2, errors=3))
        self.assertEqual(self.cat.import_rows(rows), dict(added=0, skipped=5, errors=3))
        self.assertEqual(next(r for r in self.store.list() if r['id'] == self.sid), self.original[0])
        added = [r for r in self.cat.companies() if r['id'] != self.sid]
        self.assertTrue(all(r['research_status'] == 'Not researched' for r in added))
        self.assertEqual(domain('https://www.New.example./path?q=1'), 'new.example')
        self.assertNotEqual(domain('https://sub.new.example'), domain('https://new.example'))
        reopened = Catalog(Store(self.store.path))
        self.assertEqual(reopened.import_rows(rows)['added'], 0)

    def test_csv_mapping_and_ordered_future_selection(self):
        columns, rows = read_csv('Company,Site,Notes\nMapped,https://mapped.example,"Line one\nLine two"\n')
        self.assertEqual(columns, ['Company', 'Site', 'Notes'])
        incoming = map_csv(rows, {'name': 'Company', 'website': 'Site', 'notes': 'Notes'})
        self.assertEqual(self.cat.import_rows(incoming)['added'], 1)
        self.assertEqual(self.cat.import_rows(incoming)['added'], 0)
        added = self.store.list()[0]
        self.assertEqual(added['notes'], 'Line one\nLine two')
        self.cat.select_for_research([added['id'], self.sid])
        reopened = Catalog(Store(self.store.path))
        self.assertEqual([r['startup_id'] for r in reopened.rows('SELECT * FROM research_selection ORDER BY position')], [added['id'], self.sid])
        self.assertEqual(reopened.companies()[0]['research_status'], 'Not researched')
        with self.assertRaises(ValueError):
            read_csv('Company,Company\na,b\n')
        with self.assertRaises(ValueError):
            read_csv('Company,Site\na,b,c\n')
