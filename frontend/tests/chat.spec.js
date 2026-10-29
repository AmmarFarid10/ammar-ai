import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
const python=new URL('../../.venv/bin/python',import.meta.url).pathname;
const root=new URL('../../',import.meta.url).pathname;
test('invitation, login, live progressive response, second turn, logout',async({page})=>{
 test.setTimeout(300000);
 const username='browser_'+Date.now();
 const code=execFileSync(python,['-c',"import secrets,time; from app.main import db,digest; token=secrets.token_urlsafe(24); con=db(); con.execute('INSERT INTO invites VALUES(?,?)',(digest(token),time.time()+600)); con.commit(); print(token)"],{cwd:root,encoding:'utf8'}).trim();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto('/');
 await page.getByRole('button',{name:'Have an invitation? Join here'}).click();
 await page.getByLabel('Username',{exact:true}).fill(username);
 await page.getByLabel('Password',{exact:true}).fill('browser-test-password-123');
 await page.getByLabel('Shared invitation code').fill(code);
 await page.getByRole('button',{name:'Create account'}).click();
 await expect(page.getByRole('heading',{name:'What’s on your mind?'})).toBeVisible();
 await expect(page.getByRole('checkbox',{name:/thinking/i})).not.toBeChecked();
 await page.getByLabel('Output tokens').selectOption('1024');
 await page.getByLabel('Message',{exact:true}).fill('My name is Mira. Say hello.');
 await page.getByRole('button',{name:'Send'}).click();
 await expect(page.locator('article.assistant')).toContainText(/Mira|user|Hello|name/,{timeout:60000});
 // Observe content while Stop is still available: actual progressive rendering.
 await expect(page.getByRole('button',{name:'Stop'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Send'})).toBeVisible({timeout:120000});
 await page.getByLabel('Message',{exact:true}).fill('What name did I give you?');
 await page.getByRole('button',{name:'Send'}).click();
 await expect(page.locator('article.assistant').last()).toContainText('Mira',{timeout:60000});
 await expect(page.getByRole('button',{name:'Send'})).toBeVisible({timeout:120000});
 await page.screenshot({path:new URL('../../test-results/chat-desktop.png',import.meta.url).pathname,fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:new URL('../../test-results/chat-mobile.png',import.meta.url).pathname,fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.getByRole('button',{name:'Sign out'}).click();
 await expect(page.getByRole('heading',{name:'Welcome back'})).toBeVisible({timeout:60000});
 expect(errors).toEqual([]);
 }finally{
 execFileSync(python,['-c',"from app.main import db; import sys; c=db(); uid=c.execute('SELECT id FROM users WHERE username=?',(sys.argv[1],)).fetchone(); c.execute('DELETE FROM sessions WHERE user_id=?',(uid['id'] if uid else -1,)); c.execute('DELETE FROM users WHERE username=?',(sys.argv[1],)); c.execute('DELETE FROM attempts WHERE key=?',(sys.argv[1],)); c.commit()",username],{cwd:root});
 }
});
