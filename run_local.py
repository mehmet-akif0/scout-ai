"""Local launcher: fixed loopback binding, health wait, optional browser opening."""
import argparse
import http.client
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from local_config import load_local_config

ROOT = Path(__file__).resolve().parent


def server_command(port=8501):
    return [sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
            '--server.address', '127.0.0.1', '--server.port', str(port),
            '--server.headless', 'true', '--browser.serverAddress', '127.0.0.1',
            '--browser.serverPort', str(port), '--browser.gatherUsageStats', 'false']


def healthy(port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', '/_stcore/health')
        response = connection.getresponse()
        return response.status == 200 and response.read(64).strip() == b'ok'
    except OSError:
        return False
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Start ScoutAI on localhost only.')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    try:
        load_local_config()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', args.port))
    except (OSError, ValueError):
        print('Cannot start: check scoutai.local.toml and close any app already using the port.')
        return 1
    child = subprocess.Popen(server_command(args.port), cwd=ROOT)
    try:
        for _ in range(120):
            if child.poll() is not None:
                return child.returncode or 1
            if healthy(args.port):
                address = f'http://127.0.0.1:{args.port}'
                print(f'ScoutAI is ready: {address}', flush=True)
                print('Keep this window open. Press Ctrl+C here to stop.', flush=True)
                if not args.no_browser:
                    webbrowser.open(address)
                break
            time.sleep(0.5)
        else:
            print('Startup timed out. Read the server messages above; no API calls were started.')
            return 1
        return child.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
