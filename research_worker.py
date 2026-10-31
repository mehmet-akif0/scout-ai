"""One sequential worker per SQLite file. UI refresh never submits API calls."""
import argparse
import errno
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None
import os
import subprocess
import sys
from pathlib import Path
from contextlib import contextmanager
from local_config import load_local_config
load_local_config()

from storage import Store
from research import ResearchQueue
from research_provider import OpenAIResearch, api_key

def acquire_file_lock(lock):
    if msvcrt is not None:
        # Windows locks one byte; always lock byte zero, including on a new file.
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b'\0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    elif fcntl is not None:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        raise RuntimeError('File locking requires Windows, Linux or macOS.')


def release_file_lock(lock):
    if msvcrt is not None:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def worker_lock(path):
    lock_path = Path(str(Path(path).resolve()) + '.research.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as lock:
        try:
            acquire_file_lock(lock)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                yield False
                return
            raise
        try:
            yield True
        finally:
            release_file_lock(lock)


def recover_if_idle(queue):
    with worker_lock(queue.store.path) as acquired:
        if acquired:
            queue.recover_interrupted()
        return acquired


def start_worker(queue):
    if not api_key():
        return False
    process_options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--db',str(queue.store.path.resolve())],
        cwd=Path(__file__).parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, **process_options)
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
