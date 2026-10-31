"""Offline local setup checks; Windows API calls are mocked on Linux."""
import errno
from contextlib import closing
import json
import importlib.util
import sys
import os
from pathlib import Path
import sqlite3
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch
from backup_database import backup_database
from catalog import Catalog
from local_config import load_local_config
from run_local import server_command
from storage import Store
import research_worker

class LocalConfigTests(unittest.TestCase):
    def test_blank_example_and_injected_binding_precedence(self):
        example=Path('scoutai.local.example.toml')
        self.assertTrue(all(value == '' for value in tomllib.loads(example.read_text())['environment'].values()))
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(load_local_config(example),[])
            self.assertNotIn('SCOUTAI_AI_API_KEY',os.environ)
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'config.toml'
            config.write_text('[environment]\nSCOUTAI_AI_API_KEY = "synthetic-file-value"\nSCOUTAI_AI_MODEL = "test-model"\n')
            with patch.dict(os.environ,{'SCOUTAI_AI_API_KEY':'synthetic-injected-value'},clear=True):
                self.assertEqual(load_local_config(config),['SCOUTAI_AI_MODEL'])
                self.assertEqual(os.environ['SCOUTAI_AI_API_KEY'],'synthetic-injected-value')
                self.assertEqual(os.environ['SCOUTAI_AI_MODEL'],'test-model')
            with patch.dict(os.environ,{},clear=True):
                load_local_config(config)
                self.assertEqual(os.environ['SCOUTAI_AI_API_KEY'],'synthetic-file-value')

    def test_invalid_file_is_atomic_and_does_not_print_content(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{},clear=True):
            config=Path(temp)/'config.toml'
            config.write_text('[environment]\nSCOUTAI_AI_API_KEY = "synthetic-sensitive-value"\nPATH = "unsupported"\n')
            with self.assertRaises(ValueError) as error:load_local_config(config)
            self.assertNotIn('synthetic-sensitive-value',str(error.exception))
            self.assertNotIn('SCOUTAI_AI_API_KEY',os.environ)
            config.write_text('[environment]\nSCOUTAI_AI_API_KEY = "synthetic-sensitive-value\n')
            with self.assertRaises(ValueError) as error:load_local_config(config)
            self.assertNotIn('synthetic-sensitive-value',str(error.exception))

    def test_launcher_binds_only_loopback_and_disables_telemetry(self):
        command=server_command()
        self.assertEqual(command[command.index('--server.address')+1],'127.0.0.1')
        self.assertEqual(command[command.index('--browser.serverAddress')+1],'127.0.0.1')
        self.assertEqual(command[command.index('--server.port')+1],'8501')
        self.assertEqual(command[command.index('--browser.gatherUsageStats')+1],'false')
        self.assertFalse(any('key' in arg.casefold() for arg in command))

class PortableLockTests(unittest.TestCase):
    def test_windows_import_without_fcntl_mock(self):
        fake=Mock(LK_NBLCK=1,LK_UNLCK=2)
        spec=importlib.util.spec_from_file_location('portable_worker_probe',Path('research_worker.py'))
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'fcntl':None,'msvcrt':fake}):
            spec.loader.exec_module(module)
        self.assertIsNone(module.fcntl)
        self.assertIs(module.msvcrt,fake)

    def test_windows_byte_lock_and_release_mock(self):
        api=Mock(LK_NBLCK=1,LK_UNLCK=2)
        with tempfile.TemporaryDirectory() as temp,patch.object(research_worker,'msvcrt',api):
            database=Path(temp)/'example.db'
            with research_worker.worker_lock(database) as acquired:self.assertTrue(acquired)
            calls=api.locking.call_args_list
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0].args[1:],(1,1))
            self.assertEqual(calls[1].args[1:],(2,1))
            self.assertGreaterEqual(Path(str(database.resolve())+'.research.lock').stat().st_size,1)

    def test_windows_contention_mock_does_not_unlock_another_worker(self):
        api=Mock(LK_NBLCK=1,LK_UNLCK=2)
        api.locking.side_effect=OSError(errno.EACCES,'Synthetic lock contention')
        with tempfile.TemporaryDirectory() as temp,patch.object(research_worker,'msvcrt',api):
            with research_worker.worker_lock(Path(temp)/'example.db') as acquired:self.assertFalse(acquired)
            api.locking.assert_called_once()

class BackupTests(unittest.TestCase):
    def test_online_wal_backup_preserves_all_committed_records_and_source(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'SCOUTAI_AI_API_KEY':'synthetic-env-secret-never-export'}):
            root=Path(temp);source=root/'source.db';output=root/'transfer.db'
            store=Store(source);Catalog(store)
            sid=store.save(dict(name='Synthetic existing record',status='New',stage='Unknown',notes='Keep this note'))
            from profiles import Profiles
            profiles=Profiles(store)
            pid=profiles.save('Synthetic profile',[dict(key='criterion',label='Criterion',value='Synthetic target',priority='Required')])
            profiles.assess(pid,sid,1,{'criterion':dict(result='Unknown',rationale='Synthetic evidence',source='',date='2026-10-31')})
            from metrics import Metrics
            Metrics(store).add(sid,dict(metric_key='paying_customers',value='3',period_start='2026-01-31',period_end='2026-01-31',scope='Synthetic paid accounts',source_ref='Synthetic worksheet',accessed_on='2026-10-31'))
            with closing(sqlite3.connect(source)) as original:
                original.execute('PRAGMA journal_mode=WAL')
                original.execute('CREATE TABLE transfer_fixture (value TEXT)')
                original.execute('INSERT INTO transfer_fixture VALUES (?)',('Committed while connection open',))
                original.commit()
                backup_database(source,output)
                with closing(sqlite3.connect(output)) as restored:
                    self.assertEqual(restored.execute('SELECT name,notes FROM startups WHERE id=?',(sid,)).fetchone(),('Synthetic existing record','Keep this note'))
                    self.assertEqual(restored.execute('SELECT value FROM transfer_fixture').fetchone()[0],'Committed while connection open')
                    self.assertEqual(restored.execute('PRAGMA quick_check').fetchone()[0],'ok')
                    self.assertEqual(restored.execute('SELECT COUNT(*) FROM scouting_profiles').fetchone()[0],1)
                    self.assertEqual(restored.execute('SELECT COUNT(*) FROM assessments').fetchone()[0],1)
                    self.assertEqual(restored.execute('SELECT COUNT(*) FROM metric_observations').fetchone()[0],1)
                    self.assertEqual(list(restored.iterdump()),list(original.iterdump()))
                self.assertEqual(original.execute('SELECT COUNT(*) FROM startups').fetchone()[0],1)
            self.assertNotIn(b'synthetic-env-secret-never-export',output.read_bytes())
            before=output.read_bytes()
            with self.assertRaises(FileExistsError):backup_database(source,output)
            self.assertEqual(output.read_bytes(),before)
            with self.assertRaises(ValueError):backup_database(source,source)
            with self.assertRaises(ValueError):backup_database(root/'missing.db',root/'bad.db')
            self.assertFalse((root/'bad.db').exists())
