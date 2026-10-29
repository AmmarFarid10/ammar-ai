import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
const root=new URL('../../',import.meta.url).pathname;
const python=new URL('../../.venv/bin/python',import.meta.url).pathname;
test('actual public Docker chat answers the Python question without a display crash',async({page})=>{
 test.setTimeout(300000);
 const fixture=JSON.parse(execFileSync(python,['-c',`import json,secrets,time
from app.main import db,digest,ph,ORIGIN,MAX_USERS
name='pythoncheck_'+secrets.token_hex(5)
token=secrets.token_urlsafe(32)
with db() as con:
 con.execute('BEGIN IMMEDIATE')
 assert con.execute('SELECT count(*) FROM users').fetchone()[0]<MAX_USERS,'No free test account place'
 cursor=con.execute('INSERT INTO users(username,password) VALUES(?,?)',(name,ph.hash(secrets.token_urlsafe(32))))
 con.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),cursor.lastrowid,time.time()+600))
print(json.dumps({'username':name,'token':token,'origin':ORIGIN}))`],{cwd:root,encoding:'utf8'}));
 const errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.context().addCookies([{name:'session',value:fixture.token,url:fixture.origin,httpOnly:true,secure:true,sameSite:'Strict'}]);
  await page.goto(fixture.origin,{timeout:90000});
  await expect(page.getByLabel('Message',{exact:true})).toBeVisible({timeout:90000});
  await page.getByLabel('Message',{exact:true}).fill('What is Python language?');
  await page.getByRole('button',{name:'Send'}).click();
  await expect(page.locator('article.assistant')).toContainText(/Python|programming|language/,{timeout:120000});
  await expect(page.getByRole('button',{name:'Send'})).toBeVisible({timeout:150000});
  await expect(page.getByRole('heading',{name:'The chat display stopped.'})).toHaveCount(0);
  await expect(page.getByLabel('Message',{exact:true})).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({path:new URL('../../test-results/python-public.png',import.meta.url).pathname,fullPage:true});
 }finally{
  execFileSync(python,['-c',`import sys
from app.main import db
with db() as con:
 row=con.execute('SELECT id FROM users WHERE username=?',(sys.argv[1],)).fetchone()
 if row:con.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
 con.execute('DELETE FROM users WHERE username=?',(sys.argv[1],))`,fixture.username],{cwd:root});
 }
});
