"""Runs against the actual FastAPI server and existing Ollama, never a mock."""
import json
import argparse
from urllib.parse import urlsplit
import os
import secrets
import httpx
from app.main import db, digest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--loopback',action='store_true',help='Test the Docker origin locally, with its configured public Host/Origin headers')
    args=parser.parse_args()
    origin = os.getenv('APP_ORIGIN','http://localhost:8000')
    code=secrets.token_urlsafe(32)
    username='test_'+secrets.token_hex(5)
    with db() as con:
        con.execute('INSERT INTO invites VALUES(?,?)',(digest(code),9999999999))
    try:
        with httpx.Client(base_url='http://127.0.0.1:8000' if args.loopback else origin,headers={'Origin':origin,'Host':urlsplit(origin).netloc},timeout=180,trust_env=False) as client:
            credentials={'username':username,'password':secrets.token_urlsafe(24),'invite':code}
            client.post('/api/register',json=credentials).raise_for_status()
            client.post('/api/login',json=credentials).raise_for_status()
            if args.loopback:
                client.headers['Cookie']='session='+client.cookies.get('session')
            cfg=client.get('/api/config');cfg.raise_for_status()
            print('Model configuration:',cfg.json())
            history=[]
            for prompt in ['My name is Mira. Say hello.', 'What name did I give you?']:
                history.append({'role':'user','content':prompt})
                chunks=[];done=False
                with client.stream('POST','/api/chat',json={'messages':history,'think':False,'output_tokens':1024}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        event=json.loads(line)
                        assert 'error' not in event,event
                        if event.get('content'):chunks.append(event['content'])
                        done=event.get('done',False)
                assert done and len(chunks)>1, 'Expected multiple streamed content chunks and a final event'
                answer=''.join(chunks)
                print(f'Streamed {len(chunks)} chunks; response tail: {answer[-240:]}')
                history.append({'role':'assistant','content':answer})
            assert 'Mira' in answer, 'Multi-turn name recall failed'
            client.post('/api/logout',json={}).raise_for_status()
            assert client.get('/api/me').status_code==401
            print('PASS: real authentication, configuration, streaming, multi-turn recall, logout')
    finally:
        with db() as con:
            row=con.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
            if row:con.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
            con.execute('DELETE FROM users WHERE username=?',(username,))
            con.execute('DELETE FROM attempts WHERE key=?',(username,))
            con.execute('DELETE FROM invites WHERE hash=?',(digest(code),))

if __name__ == '__main__':
    main()
