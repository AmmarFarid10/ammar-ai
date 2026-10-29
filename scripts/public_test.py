"""Check public HTTPS auth and incremental NDJSON via curl."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from app.main import ORIGIN, db, digest


def main():
    username='public_'+secrets.token_hex(5)
    code=secrets.token_urlsafe(32)
    with db() as con:
        con.execute('INSERT INTO invites VALUES(?,?)',(digest(code),time.time()+600))
    with tempfile.TemporaryDirectory() as directory:
        cookies=str(Path(directory)/'cookies')
        base=['curl','-4','--fail-with-body','-sS','--max-time','120','-b',cookies,'-c',cookies,'-H','Origin: '+ORIGIN,'-H','Content-Type: application/json']
        def post(path,payload):
            return subprocess.check_output(base+['--data-binary','@-',ORIGIN+'/api/'+path],input=json.dumps(payload).encode())
        try:
            creds={'username':username,'password':secrets.token_urlsafe(24),'invite':code}
            print('Register:',post('register',creds).decode(),flush=True)
            print('Login:',post('login',creds).decode(),flush=True)
            history=[]
            for prompt in ['My name is Mira. Say hello.', 'What name did I give you?']:
                history.append({'role':'user','content':prompt})
                started=time.monotonic();first=None;last=None;answer='';thinking='';done=False;count=0
                proc=subprocess.Popen(base+['-N','--data-binary','@-',ORIGIN+'/api/chat'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
                proc.stdin.write(json.dumps({'messages':history,'think':False,'output_tokens':1024}))
                proc.stdin.close()
                for line in proc.stdout:
                    if not line.strip():continue
                    event=json.loads(line)
                    assert 'error' not in event,event
                    if event.get('content') or event.get('thinking'):
                        now=time.monotonic()
                        if first is None:
                            first=now
                            print('First streamed chunk after',round(now-started,2),'seconds',flush=True)
                        last=now;count+=1
                        answer+=event.get('content','');thinking+=event.get('thinking','')
                    done=event.get('done',False)
                assert proc.wait()==0
                print('Chunks:',count,'delivery span:',round((last or started)-(first or started),2),'seconds; done:',done,flush=True)
                assert done and count>1
                assert last-first>0.5,'Response appears buffered'
                history.append({'role':'assistant','content':answer or '[Thinking without final answer] '+thinking})
            assert 'Mira' in answer+thinking
            print('Logout:',post('logout',{}).decode(),flush=True)
            print('PASS: public HTTPS authentication, progressive streaming, multi-turn recall, logout',flush=True)
        finally:
            with db() as con:
                row=con.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
                if row:con.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
                con.execute('DELETE FROM users WHERE username=?',(username,))
                con.execute('DELETE FROM attempts WHERE key=?',(username,))
                con.execute('DELETE FROM invites WHERE hash=?',(digest(code),))

if __name__=='__main__':
    main()
