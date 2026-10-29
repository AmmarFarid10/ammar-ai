import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
const root=new URL('../../',import.meta.url).pathname;
const python=new URL('../../.venv/bin/python',import.meta.url).pathname;
test('actual public chat separates FastAPI final answer from reasoning',async({page})=>{
 test.setTimeout(300000);
 const fixture=JSON.parse(execFileSync(python,['-c',`import json,secrets,time
from app.main import db,digest,ph,ORIGIN,MAX_USERS
name='answercheck_'+secrets.token_hex(5)
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
  await page.addInitScript(()=>{const original=window.fetch;window.fetch=async(...args)=>{const response=await original(...args);if(String(args[0]).includes('/api/chat'))response.clone().text().then(text=>{window.__chatNDJSON=text});return response}});
  await page.context().addCookies([{name:'session',value:fixture.token,url:fixture.origin,httpOnly:true,secure:true,sameSite:'Strict'}]);
  await page.goto(fixture.origin,{timeout:90000});
  await expect(page.getByLabel('Message',{exact:true})).toBeVisible({timeout:90000});
  await page.getByLabel('Message',{exact:true}).fill('whta is fast api');
  const responsePromise=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/chat');
  await page.getByRole('button',{name:'Send'}).click();
  const response=await responsePromise;
  await expect(page.locator('article.assistant')).toContainText(/Fast\s*API/i,{timeout:120000});
  await expect(page.getByRole('button',{name:'Send'})).toBeVisible({timeout:150000});
  await expect(page.getByRole('heading',{name:'The chat display stopped.'})).toHaveCount(0);
  await expect(page.getByLabel('Message',{exact:true})).toBeVisible();
  expect(errors).toEqual([]);
  await expect(page.getByLabel('Output tokens')).toHaveValue('1024');
  await expect(page.locator('article.assistant details')).toHaveCount(0);
  await expect.poll(()=>page.evaluate(()=>Boolean(window.__chatNDJSON)),{timeout:10000}).toBeTruthy();
  const events=(await page.evaluate(()=>window.__chatNDJSON)).trim().split('\n').map(line=>JSON.parse(line));
  expect(events.every(event=>!event.thinking)).toBeTruthy();
  expect(events[events.length-1].reason).toBe('stop');
  const answer=events.map(event=>event.content||'').join('');
  expect(answer).toMatch(/Fast\s*API/i);
  expect(answer).not.toContain('</think>');
  console.log('Final answer preview:',answer.slice(0,300));
  await page.screenshot({path:new URL('../../test-results/fastapi-public.png',import.meta.url).pathname,fullPage:true});
 }finally{
  execFileSync(python,['-c',`import sys
from app.main import db
with db() as con:
 row=con.execute('SELECT id FROM users WHERE username=?',(sys.argv[1],)).fetchone()
 if row:con.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
 con.execute('DELETE FROM users WHERE username=?',(sys.argv[1],))`,fixture.username],{cwd:root});
 }
});
