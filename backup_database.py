"""Consistent SQLite-only transfer backup. Never packages local settings or env."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from local_config import ROOT, load_local_config


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist. No empty replacement will be created.')
    if source == destination:
        raise ValueError('Backup destination must differ from the source.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an existing backup or destination DB.
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(destination)) as target, target:
                original.backup(target)
                if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup consistency check failed.')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export a SQLite-only ScoutAI backup.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        load_local_config()
        source = Path(os.environ.get('SCOUTAI_DB_PATH') or ROOT / 'data' / 'scoutai.db')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        output = args.output or ROOT / 'data' / 'exports' / f'scoutai-transfer-{stamp}.db'
        result = backup_database(source, output)
        print(f'SQLite-only backup created: {result}')
        print('Transfer this private database securely. It is not included in GitHub downloads.')
        return 0
    except (OSError, ValueError, sqlite3.Error):
        print('Backup failed. Verify the source path, destination and file permissions. Existing files were not overwritten.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
