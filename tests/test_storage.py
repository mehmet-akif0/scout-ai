import csv
import io
import tempfile
import unittest
from pathlib import Path
from storage import Store, export_csv

class StorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'scout.db'
        self.store = Store(self.path)
        self.item = dict(name='Acme', website='https://example.com', founders='Jane, John', sector='Fintech', country='Türkiye', stage='Seed', description='Payments', sources='https://example.com/about\nhttps://example.com/news', notes='First contact', status='New')

    def tearDown(self):
        self.temp.cleanup()

    def test_crud_persistence_and_filters(self):
        key = self.store.save(self.item)
        self.assertEqual(Store(self.path).list()[0]['founders'], 'Jane, John')
        self.store.save({**self.item, 'status': 'Shortlisted', 'notes': 'Call next week'}, key)
        self.assertEqual(len(self.store.list('ACM', 'Fintech', 'Seed', 'Shortlisted')), 1)
        self.assertEqual(self.store.list('Acme', status='Passed'), [])
        self.assertEqual(self.store.list('%'), [])
        self.assertEqual(Store(self.path).list()[0]['notes'], 'Call next week')
        self.store.delete(key)
        self.assertEqual(Store(self.path).list(), [])

    def test_validation(self):
        for patch in ({'name': ' '}, {'website': 'javascript:alert(1)'}, {'sources': 'not a link'}, {'status': 'invalid'}, {'stage': 'invalid'}):
            with self.assertRaises(ValueError):
                self.store.save({**self.item, **patch})
        with self.assertRaises(ValueError):
            self.store.save(self.item, 9999)
        with self.assertRaises(ValueError):
            self.store.delete(9999)

    def test_csv_unicode_multiline_and_formula_safety(self):
        self.store.save({**self.item, 'notes': '=1+1', 'description': 'First line\nSecond, line'})
        rows = list(csv.DictReader(io.StringIO(export_csv(self.store.list()).decode('utf-8-sig'))))
        self.assertEqual(rows[0]['country'], 'Türkiye')
        self.assertEqual(rows[0]['notes'], "'=1+1")
        self.assertEqual(rows[0]['description'], 'First line\nSecond, line')
