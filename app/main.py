import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
MODEL = 'qwen3:4b'
MAX_USERS = 10
SYSTEM_PROMPT = (
    'You are Ammar AI, a helpful assistant powered by Qwen. '
    'Answer directly and concisely by default. For simple questions, use one to three short paragraphs. '
    'Include code or a long tutorial only when requested. Do not comment on spelling unless asked. '
    'Avoid unsupported numerical comparisons or company-usage claims. Follow requests for more detail.'
)
OLLAMA = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
if OLLAMA not in ('http://127.0.0.1:11434', 'http://host.docker.internal:11434'):
    raise RuntimeError('OLLAMA_BASE_URL must point to the existing local Ollama instance')
ORIGIN = os.getenv('APP_ORIGIN', 'http://localhost:8000').rstrip('/')
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
if urlsplit(ORIGIN).hostname not in ('localhost', '127.0.0.1') and (not SECURE or urlsplit(ORIGIN).scheme != 'https'):
    raise RuntimeError('External APP_ORIGIN requires HTTPS and COOKIE_SECURE=true')
DB = os.getenv('DATABASE_PATH', 'localai.sqlite3')
DEFAULT_OUTPUT = max(64, min(2048, int(os.getenv('OUTPUT_TOKENS', '1024'))))
ph = PasswordHasher()
app = FastAPI(docs_url=None, redoc_url=None)
slot = asyncio.Semaphore(1)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS invites(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS registration_codes(id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER, expires REAL);
        ''')

init_db()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@app.middleware('http')
async def security(request: Request, call_next):
    if request.headers.get('host') != urlsplit(ORIGIN).netloc:
        return Response('Invalid host', status_code=400)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != ORIGIN:
        return Response('Invalid origin', status_code=403)
    if request.url.path.startswith('/api/'):
        length = request.headers.get('content-length')
        if length:
            try:
                declared_size = int(length)
            except ValueError:
                return Response('Invalid content length', status_code=400)
            if declared_size < 0:
                return Response('Invalid content length', status_code=400)
            if declared_size > 65536:
                return Response('Request too large', status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return Response('Request too large', status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"})
    return response


def user(request):
    token = request.cookies.get('session', '')
    with db() as con:
        row = con.execute('SELECT users.id, username FROM sessions JOIN users ON users.id=sessions.user_id WHERE hash=? AND expires>?', (digest(token), time.time())).fetchone()
    if not row:
        raise HTTPException(401, 'Sign in required')
    return dict(row)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=12, max_length=128)
    invite: str = Field(default='', max_length=128)


def throttle(username):
    # Global per-account limit also works behind the tunnel without trusting forwarded IPs.
    key = username.lower()
    now = time.time()
    with db() as con:
        row = con.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
        count = row['count'] if row and row['expires'] > now else 0
        if count >= 10:
            raise HTTPException(429, 'Too many attempts; wait 15 minutes')
        con.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (key, count + 1, row['expires'] if count else now + 900))


@app.post('/api/register')
def register(body: Credentials):
    throttle(body.username)
    password = ph.hash(body.password)
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM invites WHERE hash=? AND expires>?', (digest(body.invite), time.time())).fetchone()
        shared = con.execute('SELECT 1 FROM registration_codes WHERE id=1 AND hash=?', (digest(body.invite),)).fetchone()
        if not row and not shared:
            raise HTTPException(403, 'Invalid invitation code')
        if con.execute('SELECT count(*) FROM users').fetchone()[0] >= MAX_USERS:
            raise HTTPException(403, 'All 10 account places are filled. Existing users can still sign in.')
        try:
            con.execute('INSERT INTO users(username,password) VALUES(?,?)', (body.username.lower(), password))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Username unavailable')
        con.execute('DELETE FROM invites WHERE hash=?', (digest(body.invite),))
    return {'ok': True}


@app.post('/api/login')
def login(body: Credentials, response: Response):
    throttle(body.username)
    with db() as con:
        row = con.execute('SELECT * FROM users WHERE username=?', (body.username.lower(),)).fetchone()
    try:
        ph.verify(row['password'] if row else DUMMY_HASH, body.password)
        if not row:
            raise VerificationError()
    except VerificationError:
        raise HTTPException(401, 'Invalid credentials')
    token = secrets.token_urlsafe(32)
    with db() as con:
        con.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        con.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), row['id'], time.time() + 86400))
    response.set_cookie('session', token, httponly=True, secure=SECURE, samesite='strict', max_age=86400)
    return {'username': row['username']}


DUMMY_HASH = ph.hash(secrets.token_urlsafe(32))


@app.get('/api/me')
def me(request: Request):
    return user(request)


@app.post('/api/logout')
def logout(request: Request, response: Response):
    with db() as con:
        con.execute('DELETE FROM sessions WHERE hash=?', (digest(request.cookies.get('session', '')),))
    response.delete_cookie('session', secure=SECURE, httponly=True, samesite='strict')
    return {'ok': True}


class ClientError(BaseModel):
    name: str = Field(max_length=80)
    message: str = Field(max_length=500)
    stack: str = Field(default='', max_length=1500)
    build: str = Field(max_length=80)


@app.post('/api/client-error')
def client_error(body: ClientError, request: Request):
    user(request)
    logging.getLogger('uvicorn.error').error('Client display error: %s', json.dumps(body.model_dump()))
    return {'ok': True}


_thinking_only = None
_thinking_checked_at = 0.0


async def model_thinking_only(client):
    global _thinking_only, _thinking_checked_at
    if _thinking_only is not None and time.monotonic() - _thinking_checked_at < 60:
        return _thinking_only
    result = await client.post(OLLAMA + '/api/show', json={'model': MODEL}, timeout=10)
    result.raise_for_status()
    info = result.json()
    _thinking_only = info.get('thinking', {}).get('values') == [True] or info.get('model_info', {}).get('general.finetune') == 'Thinking'
    _thinking_checked_at = time.monotonic()
    return _thinking_only


@app.get('/api/config')
async def config(request: Request):
    user(request)
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            thinking_only = await model_thinking_only(client)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Existing Ollama server or qwen3:4b is unavailable')
    return {'model': MODEL, 'context': 4096, 'output_tokens': DEFAULT_OUTPUT, 'thinking_only': thinking_only}


class Message(BaseModel):
    role: str = Field(pattern='^(user|assistant)$')
    content: str = Field(min_length=1, max_length=16000)


class Chat(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=100)
    think: bool = False
    output_tokens: int = Field(default=DEFAULT_OUTPUT, ge=64, le=2048)


@app.post('/api/chat')
async def chat(body: Chat, request: Request):
    user(request)
    if body.messages[-1].role != 'user' or any(m.role != ('user' if i % 2 == 0 else 'assistant') for i, m in enumerate(body.messages)):
        raise HTTPException(422, 'Messages must alternate user and assistant, ending with user')
    # Conservative UTF-8 byte upper bound, including room for formatting and output.
    budget = 4096 - body.output_tokens - 256 - len(SYSTEM_PROMPT.encode()) - 16
    messages = [m.model_dump() for m in body.messages]
    def size():
        return sum(len(m['content'].encode()) + 16 for m in messages)
    while len(messages) > 1 and size() > budget:
        messages = messages[2:]
    if size() > budget:
        raise HTTPException(422, 'Message too long for the 4096-token context; shorten it or reduce the output limit')
    if slot.locked():
        raise HTTPException(429, 'Model is busy; retry after the current response')
    await slot.acquire()
    client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5), trust_env=False)
    try:
        # Thinking-only weights require true for Ollama to separate reasoning from answers.
        only_thinking = await model_thinking_only(client)
        upstream = await client.send(client.build_request('POST', OLLAMA + '/api/chat', json={
            'model': MODEL, 'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}] + messages, 'think': True if only_thinking else body.think, 'stream': True,
            'keep_alive': '5m', 'options': {'num_ctx': 4096, 'num_predict': body.output_tokens}}), stream=True)
        upstream.raise_for_status()
    except (httpx.HTTPError, ValueError):
        await client.aclose()
        slot.release()
        raise HTTPException(503, 'Cannot connect to the existing Ollama model')

    async def stream():
        done = False
        try:
            async for line in upstream.aiter_lines():
                if await request.is_disconnected():
                    break
                if not line:
                    continue
                event = json.loads(line)
                if 'error' in event:
                    yield json.dumps({'error': 'Ollama generation failed'}) + '\n'
                    break
                message = event.get('message', {})
                yield json.dumps({'content': message.get('content', ''), 'thinking': message.get('thinking', '') if body.think else '',
                    'phase': 'thinking' if message.get('thinking') else 'answer',
                    'done': event.get('done', False), 'reason': event.get('done_reason')}) + '\n'
                if event.get('done'):
                    done = True
                    break
            if not done and not await request.is_disconnected():
                yield json.dumps({'error': 'Generation ended before completion'}) + '\n'
        except (httpx.HTTPError, ValueError):
            yield json.dumps({'error': 'Generation interrupted; retry'}) + '\n'
        finally:
            await upstream.aclose()
            await client.aclose()
            slot.release()
    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={'X-Accel-Buffering': 'no'})


static = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if static.exists():
    app.mount('/', StaticFiles(directory=static, html=True), name='frontend')
