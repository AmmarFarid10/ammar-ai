"""Run LocalAI through a temporary Cloudflare Quick Tunnel."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dotenv import set_key

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime'
PID = STATE / 'share.pid'
URL = STATE / 'public-url.txt'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--docker', action='store_true', help='Run the web application using Docker Compose')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--curl-provision', action='store_true', help='Use curl for provisioning if cloudflared API requests time out')
    args = parser.parse_args()
    STATE.mkdir(exist_ok=True, mode=0o700)
    if PID.exists():
        pid = int(PID.read_text())
        proc = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
        running = proc.returncode == 0 and 'scripts.share' in proc.stdout
        if running:
            if args.stop:
                os.kill(pid, signal.SIGTERM)
                print('Stopping public sharing. The temporary URL will stop working.')
                return
            raise SystemExit('Sharing is already running. URL: ' + (URL.read_text().strip() if URL.exists() else 'starting; see .runtime/share.log'))
    if args.stop:
        print('Sharing is not running.')
        return
    if not shutil.which('cloudflared'):
        raise SystemExit('Install cloudflared first: brew install cloudflared')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 8000)) == 0:
            raise SystemExit('Port 8000 is in use. Stop the existing FastAPI server with Ctrl+C first.')
    if args.background:
        with (STATE / 'share.log').open('a') as log:
            proc = subprocess.Popen([sys.executable, '-u', '-m', 'scripts.share'] + (['--curl-provision'] if args.curl_provision else []) + (['--docker'] if args.docker else []), cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
        print(f'Sharing is starting (PID {proc.pid}). Read .runtime/share.log for the public URL.')
        return
    PID.write_text(str(os.getpid()))
    URL.unlink(missing_ok=True)
    children = []
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    public_url = []
    bridge = None
    docker_started = False
    server = None
    try:
        extra = []
        if args.curl_provision:
            print('Provisioning a temporary Cloudflare tunnel using curl…', flush=True)
            payload = subprocess.check_output(['curl', '-4', '-f', '-sS', '--max-time', '60', '-X', 'POST', '-H', 'Content-Type: application/json', 'https://api.trycloudflare.com/tunnel'])
            data = json.loads(payload)
            if not data.get('success'):
                raise RuntimeError('Cloudflare rejected tunnel provisioning')
            # Deliver the original API response once over loopback; credentials stay in memory.
            class Provisioning(BaseHTTPRequestHandler):
                served = False
                def do_POST(self):
                    if self.path != '/tunnel' or Provisioning.served:
                        self.send_error(404)
                        return
                    Provisioning.served = True
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                def log_message(self, *_):
                    pass
            bridge = HTTPServer(('127.0.0.1', 0), Provisioning)
            threading.Thread(target=bridge.serve_forever, daemon=True).start()
            extra = ['--quick-service', f'http://127.0.0.1:{bridge.server_port}', '--protocol', 'http2', '--edge-ip-version', '4']
        tunnel = subprocess.Popen(['cloudflared', 'tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8000'] + extra, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        children.append(tunnel)
        def logs():
            for line in tunnel.stdout:
                print(line.rstrip(), flush=True)
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                if match and not public_url:
                    public_url.append(match.group())
        threading.Thread(target=logs, daemon=True).start()
        deadline = time.monotonic() + 90
        while not public_url and not stop.wait(.2):
            if tunnel.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Cloudflare failed to provide a URL; see logs')
        if stop.is_set():
            return
        origin = public_url[0]
        env_file = ROOT / '.env'
        if not env_file.exists():
            shutil.copyfile(ROOT / '.env.example', env_file)
        set_key(str(env_file), 'APP_ORIGIN', origin)
        set_key(str(env_file), 'COOKIE_SECURE', 'true')
        env = {**os.environ, 'APP_ORIGIN': origin, 'COOKIE_SECURE': 'true'}
        if args.docker:
            subprocess.run(['docker', 'compose', 'up', '-d', '--no-build'], cwd=ROOT, env=env, check=True)
            docker_started = True
        else:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--workers', '1', '--no-proxy-headers'], cwd=ROOT, env=env)
            children.append(server)
        if shutil.which('caffeinate'):
            children.append(subprocess.Popen(['caffeinate', '-i', '-w', str(os.getpid())]))
        URL.write_text(origin + '\n')
        print('\nPUBLIC URL: ' + origin, flush=True)
        print('Keep the Mac connected with the lid open. Stop: .venv/bin/python -m scripts.share --stop', flush=True)
        while not stop.wait(1):
            if (server is not None and server.poll() is not None) or tunnel.poll() is not None:
                raise RuntimeError('Server or tunnel stopped; stopping public sharing')
    finally:
        if docker_started:
            subprocess.run(['docker', 'compose', 'stop'], cwd=ROOT, timeout=40)
        if bridge:
            bridge.shutdown()
            bridge.server_close()
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        PID.unlink(missing_ok=True)
        URL.unlink(missing_ok=True)
        print('Public sharing stopped. Ollama was left running.', flush=True)

if __name__ == '__main__':
    main()
