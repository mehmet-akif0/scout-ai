"""One sequential worker per SQLite file. UI refresh never submits API calls."""
import argparse
import fcntl
import os
import subprocess
import sys
from pathlib import Path
from contextlib import contextmanager
from storage import Store
from research import ResearchQueue
from research_provider import OpenAIResearch, api_key

@contextmanager
def worker_lock(path):
    lock_path = Path(str(Path(path).resolve()) + '.research.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def recover_if_idle(queue):
    with worker_lock(queue.store.path) as acquired:
        if acquired:
            queue.recover_interrupted()
        return acquired


def start_worker(queue):
    if not api_key():
        return False
    subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--db',str(queue.store.path.resolve())],
        cwd=Path(__file__).parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return True


def run(path):
    with worker_lock(path) as acquired:
        if not acquired:
            return
        queue = ResearchQueue(Store(path))
        queue.recover_interrupted()
        if not api_key():
            return
        while queue.process_one(OpenAIResearch):
            pass

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    run(parser.parse_args().db)
