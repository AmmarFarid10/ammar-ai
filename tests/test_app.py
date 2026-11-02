import importlib
import json
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('APP_ORIGIN', 'http://localhost:8000')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    monkeypatch.setenv('OUTPUT_TOKENS', '1024')
    import app.main as main
    importlib.reload(main)
    main._thinking_only = False
    main._thinking_checked_at = main.time.monotonic()
    client = TestClient(main.app, base_url='http://localhost:8000', headers={'origin': 'http://localhost:8000'})
    return main, client


def signup(main, client):
    with main.db() as con:
        con.execute('INSERT INTO invites VALUES(?,?)', (main.digest('invite'), 9999999999))
    body = {'username':'friend','password':'a-long-test-password','invite':'invite'}
    assert client.post('/api/register', json=body).status_code == 200
    assert client.post('/api/register', json={**body, 'username':'friend2'}).status_code == 403
    assert client.post('/api/login', json=body).status_code == 200
    return body


def test_auth_and_security(env):
    main, client = env
    assert client.get('/api/me').status_code == 401
    body = signup(main, client)
    assert client.get('/api/me').json()['username'] == 'friend'
    assert client.cookies.get('session')
    assert client.post('/api/logout', json={}).status_code == 200
    assert client.get('/api/me').status_code == 401
    assert client.post('/api/login',json={**body,'password':'wrong-password'}).status_code == 401
    assert client.post('/api/login',json=body,headers={'origin':'https://evil.example'}).status_code == 403
    assert client.get('/api/me',headers={'host':'evil.example'}).status_code == 400
    assert client.post('/api/login',content='x'*65537).status_code == 413


def test_validation_and_throttle(env):
    main, client = env
    signup(main,client)
    assert client.post('/api/chat',json={'messages':[{'role':'system','content':'bad'}]}).status_code == 422
    assert client.post('/api/chat',json={'messages':[{'role':'user','content':'x'*5000}]}).status_code == 422
    for _ in range(10):
        result=client.post('/api/login',json={'username':'missing','password':'wrong-password'})
    assert result.status_code == 401
    assert client.post('/api/login',json={'username':'missing','password':'wrong-password'}).status_code == 429


def test_stream_payload_and_history(env, monkeypatch):
    main, client = env
    signup(main,client)
    real_client=main.httpx.AsyncClient
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return main.httpx.Response(200,content='{"message":{"content":"Hello"},"done":false}\n{"message":{"content":" friend"},"done":false}\n{"done":true,"done_reason":"stop"}\n')
    monkeypatch.setattr(main.httpx,'AsyncClient',lambda **kw:real_client(transport=main.httpx.MockTransport(handler)))
    history=[{'role':'user','content':'My name is Sam'},{'role':'assistant','content':'Hello Sam'},{'role':'user','content':'What is my name?'}]
    result=client.post('/api/chat',json={'messages':history})
    assert result.status_code==200
    events=[json.loads(x) for x in result.text.splitlines()]
    assert ''.join(e.get('content','') for e in events)=='Hello friend'
    assert events[-1]['done']
    assert captured[0]['messages'][0]=={'role':'system','content':main.SYSTEM_PROMPT}
    assert captured[0]['messages'][1:]==history
    assert captured[0]['model']=='qwen3:4b'
    assert captured[0]['think'] is False
    assert captured[0]['stream'] is True
    assert captured[0]['options']=={'num_ctx':4096,'num_predict':1024}
    assert not main.slot.locked()


def test_stream_error_releases_capacity(env, monkeypatch):
    main, client=env
    signup(main, client)
    real_client=main.httpx.AsyncClient
    def handler(request):
        return main.httpx.Response(200,content='not json\n')
    monkeypatch.setattr(main.httpx,'AsyncClient',lambda **kw:real_client(transport=main.httpx.MockTransport(handler)))
    response=client.post('/api/chat',json={'messages':[{'role':'user','content':'Hi'}]})
    assert 'Generation interrupted' in response.text
    assert not main.slot.locked()


def test_secure_cookie(env, monkeypatch):
    main, client=env
    monkeypatch.setattr(main,'SECURE',True)
    with main.db() as con:
        con.execute('INSERT INTO users(username,password) VALUES(?,?)',('friend',main.ph.hash('a-long-test-password')))
    response=client.post('/api/login',json={'username':'friend','password':'a-long-test-password'})
    cookie=response.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie


def test_thinking_and_history_budget(env, monkeypatch):
    main, client=env
    signup(main,client)
    real=main.httpx.AsyncClient
    captured=[]
    def handler(req):
        captured.append(json.loads(req.content))
        return main.httpx.Response(200,content='{"message":{"thinking":"Reason","content":"Yes"},"done":true}\n')
    monkeypatch.setattr(main.httpx,'AsyncClient',lambda **kw:real(transport=main.httpx.MockTransport(handler)))
    messages=[{'role':'user','content':'x'*2000},{'role':'assistant','content':'y'*2000},{'role':'user','content':'Now?'}]
    r=client.post('/api/chat',json={'messages':messages,'think':True})
    assert r.status_code==200
    assert captured[0]['messages'][1:]==messages[-1:]
    assert captured[0]['think'] is True
    assert json.loads(r.text)['thinking']=='Reason'


def test_shared_code_reusable_and_ten_account_cap(env):
    main, client = env
    with main.db() as con:
        con.execute('INSERT INTO registration_codes VALUES(1,?)', (main.digest('shared-group-code'),))
    def body(i, code='shared-group-code'):
        return {'username': f'person{i}', 'password': 'a-long-test-password', 'invite': code}
    assert client.post('/api/register', json=body(99, 'wrong')).status_code == 403
    for i in range(10):
        assert client.post('/api/register', json=body(i)).status_code == 200
    assert client.post('/api/register', json=body(10)).status_code == 403
    with main.db() as con:
        assert con.execute('SELECT count(*) FROM users').fetchone()[0] == 10
        assert con.execute('SELECT count(*) FROM registration_codes').fetchone()[0] == 1
        # Even a legacy invitation cannot bypass the global cap.
        con.execute('INSERT INTO invites VALUES(?,?)', (main.digest('legacy'), 9999999999))
    assert client.post('/api/register', json=body(11, 'legacy')).status_code == 403
    assert client.post('/api/login', json=body(0)).status_code == 200
    assert client.get('/api/me').json()['username'] == 'person0'


def test_final_place_is_atomic(env):
    from concurrent.futures import ThreadPoolExecutor
    main, _ = env
    password = main.ph.hash('a-long-test-password')
    with main.db() as con:
        con.execute('INSERT INTO registration_codes VALUES(1,?)', (main.digest('shared'),))
        con.executemany('INSERT INTO users(username,password) VALUES(?,?)', [(f'existing{i}', password) for i in range(9)])
    def register(i):
        with TestClient(main.app, base_url='http://localhost:8000', headers={'origin':'http://localhost:8000'}) as client:
            return client.post('/api/register', json={'username':f'last{i}','password':'a-long-test-password','invite':'shared'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(register, [1,2]))
    assert sorted(results) == [200,403]
    with main.db() as con:
        assert con.execute('SELECT count(*) FROM users').fetchone()[0] == 10


def test_rotating_shared_code_preserves_accounts(env, monkeypatch, capsys):
    main, client = env
    import scripts.invite as invite
    monkeypatch.setattr(invite, 'db', main.db)
    invite.main()
    first = capsys.readouterr().out.splitlines()[0]
    credentials={'username':'member','password':'a-long-test-password','invite':first}
    assert client.post('/api/register',json=credentials).status_code == 200
    invite.main()
    second = capsys.readouterr().out.splitlines()[0]
    assert first != second
    assert client.post('/api/register',json={**credentials,'username':'another'}).status_code == 403
    assert client.post('/api/register',json={**credentials,'username':'another','invite':second}).status_code == 200
    assert client.post('/api/login',json=credentials).status_code == 200


def test_client_error_reporting(env, caplog):
    main, client = env
    payload={'name':'TypeError','message':'scrollIntoView is not a function','stack':'at App','build':'scroll-recovery-2'}
    assert client.post('/api/client-error',json=payload).status_code == 401
    signup(main,client)
    assert client.post('/api/client-error',json=payload).status_code == 200
    assert 'scrollIntoView is not a function' in caplog.text
    assert client.post('/api/client-error',json={**payload,'message':'x'*501}).status_code == 422


@pytest.mark.parametrize('show_thinking', [False, True])
def test_thinking_only_model_separates_reasoning(env, monkeypatch, show_thinking):
    main, client=env
    signup(main,client)
    main._thinking_only=True
    real=main.httpx.AsyncClient
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return main.httpx.Response(200,content='{"message":{"thinking":"PRIVATE REASONING"},"done":false}\n{"message":{"content":"FastAPI builds Python APIs."},"done":false}\n{"done":true,"done_reason":"stop"}\n')
    monkeypatch.setattr(main.httpx,'AsyncClient',lambda **kw:real(transport=main.httpx.MockTransport(handler)))
    result=client.post('/api/chat',json={'messages':[{'role':'user','content':'What is FastAPI?'}],'think':show_thinking})
    assert result.status_code==200
    events=[json.loads(line) for line in result.text.splitlines()]
    assert captured[0]['think'] is True
    assert ''.join(e['content'] for e in events)=='FastAPI builds Python APIs.'
    assert events[0]['phase']=='thinking'
    assert ('PRIVATE REASONING' in result.text) is show_thinking
    assert events[-1]['done']

@pytest.mark.parametrize('value', ['invalid', '-1'])
def test_invalid_content_length_is_rejected(env, value):
    _, client = env
    response = client.post('/api/login', content='{}', headers={'content-length': value})
    assert response.status_code == 400
