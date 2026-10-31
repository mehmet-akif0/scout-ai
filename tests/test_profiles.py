import tempfile
import unittest
from pathlib import Path
from storage import Store
from profiles import Profiles


def criterion(key='sector', value='Climate', priority='Required'):
    return dict(key=key, label=key, value=value, priority=priority)


def response(result='Unknown'):
    return dict(result=result, rationale='Manual research', source='https://example.com', date='2026-10-31')

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'existing.db'
        self.store = Store(self.path)
        self.startup = self.store.save(dict(name='Existing company', status='New', stage='Seed', notes='Preserve my notes'))
        self.original = self.store.list()
        self.profiles = Profiles(self.store)

    def test_additive_migration_and_delete_preserve_companies(self):
        self.assertEqual(self.original, self.store.list())
        Profiles(Store(self.path))  # Idempotent initialization.
        p = self.profiles.save('Personal lens', [criterion()])
        self.profiles.activate(p)
        self.profiles.assess(p, self.startup, 1, {'sector': response()})
        self.assertEqual(Profiles(Store(self.path)).active_id(), p)
        self.profiles.delete(p)
        self.assertEqual(self.store.list(), self.original)
        self.assertIsNone(self.profiles.active_id())
        self.assertEqual(self.profiles.history(p, self.startup), [])

    def test_profile_isolation_and_persistence(self):
        a = self.profiles.save('Lens A', [criterion()])
        b = self.profiles.save('Lens B', [criterion()])
        self.profiles.assess(a, self.startup, 1, {'sector': response('Meets')})
        self.assertEqual(self.profiles.state(b, self.startup), 'Not evaluated')
        self.profiles.assess(b, self.startup, 1, {'sector': response('Does not meet')})
        reopened = Profiles(Store(self.path))
        self.assertEqual(reopened.state(a, self.startup), 'Meets required criteria')
        self.assertEqual(reopened.state(b, self.startup), 'Does not meet required criteria')
        self.assertEqual(self.store.list(), self.original)

    def test_required_unknown_preferred_and_revision_history(self):
        p = self.profiles.save('Research lens', [criterion(), criterion('model', 'B2B', 'Preferred')])
        self.profiles.assess(p, self.startup, 1, {'sector': response(), 'model': response('Does not meet')})
        self.assertEqual(self.profiles.state(p, self.startup), 'Needs research')
        self.profiles.assess(p, self.startup, 1, {'sector': response('Meets'), 'model': response('Does not meet')})
        self.assertEqual(self.profiles.state(p, self.startup), 'Meets required criteria')
        criteria = self.profiles.get(p)['criteria']
        self.profiles.save('Renamed lens', criteria, p)
        self.assertEqual(self.profiles.get(p)['revision'], 1)
        self.profiles.save('Renamed lens', [criterion(value='Health')], p)
        self.assertEqual(self.profiles.state(p, self.startup), 'Review needed')
        self.assertEqual(self.profiles.history(p, self.startup)[0]['criteria'], criteria)
        with self.assertRaises(ValueError):
            self.profiles.assess(p, self.startup, 1, {'sector': response('Meets')})
        self.profiles.assess(p, self.startup, 2, {'sector': response('Meets')})
        self.assertEqual(len(self.profiles.history(p, self.startup)), 2)
        self.profiles.save('Renamed lens', [], p)
        self.assertEqual(self.profiles.state(p, self.startup), 'Review needed')

    def test_blank_no_defaults_and_preferred_only(self):
        p = self.profiles.save('Empty', [criterion(value=' ')])
        self.assertEqual(self.profiles.get(p)['criteria'], [])
        self.assertEqual(self.profiles.state(p, self.startup), 'No criteria configured')
        self.profiles.save('Empty', [criterion(priority='Preferred')], p)
        self.profiles.assess(p, self.startup, 2, {'sector': response('Does not meet')})
        self.assertEqual(self.profiles.state(p, self.startup), 'Reviewed (no required criteria)')

    def test_validation_and_company_delete_cleanup(self):
        with self.assertRaises(ValueError):
            self.profiles.save('', [])
        p = self.profiles.save('Valid', [criterion()])
        for payload in ({}, {'sector': response('Invalid')}, {'sector': {**response(), 'source': 'javascript:test'}}):
            with self.assertRaises(ValueError):
                self.profiles.assess(p, self.startup, 1, payload)
        self.profiles.assess(p, self.startup, 1, {'sector': response()})
        self.store.delete(self.startup)
        self.assertEqual(self.profiles.history(p, self.startup), [])
        self.assertIsNotNone(self.profiles.get(p))

    def test_priority_custom_criteria_addition_and_removal_invalidate(self):
        p = self.profiles.save('Lens', [criterion(priority='Preferred')])
        self.profiles.assess(p, self.startup, 1, {'sector': response('Meets')})
        self.profiles.save('Lens', [criterion(priority='Required')], p)
        self.assertEqual(self.profiles.state(p, self.startup), 'Review needed')
        self.profiles.assess(p, self.startup, 2, {'sector': response('Meets')})
        custom = criterion('custom_team', 'Team has shipping experience', 'Preferred')
        self.profiles.save('Lens', [criterion(), custom], p)
        self.assertEqual(self.profiles.state(p, self.startup), 'Review needed')
        self.profiles.assess(p, self.startup, 3, {'sector': response('Meets'), 'custom_team': response()})
        self.assertEqual(self.profiles.state(p, self.startup), 'Meets required criteria')
        self.profiles.save('Lens', [custom], p)
        self.assertEqual(self.profiles.state(p, self.startup), 'Review needed')
        self.assertEqual(len(self.profiles.history(p, self.startup)), 3)
