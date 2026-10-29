import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const dist=new URL('../dist/',import.meta.url).pathname;
async function app(page,chat){
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/api/me')return route.fulfill({json:{username:'testuser'}});
  if(url.pathname==='/api/config')return route.fulfill({json:{model:'qwen3:4b',output_tokens:1024,thinking_only:true}});
  if(url.pathname==='/api/chat')return chat(route);
  if(url.pathname==='/api/client-error')return route.fulfill({json:{ok:true}});
  const file=path.join(dist,url.pathname==='/'?'index.html':url.pathname);
  const type=file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html';
  return route.fulfill({body:fs.readFileSync(file),contentType:type});
 });
 await page.goto('http://localhost:8000/');
 await expect(page.getByLabel('Message',{exact:true})).toBeVisible();
 await expect(page).toHaveTitle('Ammar AI · Your private workspace');
 await expect(page.locator('.brand')).toContainText('Ammar AI');
}
for(const scenario of ['busy','empty','broken','invalid']){
 test(`keeps chat visible after ${scenario} response`,async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await app(page,route=>scenario==='busy'?route.fulfill({status:429,json:{detail:'Model is busy; retry after the current response'}}):route.fulfill({contentType:'application/x-ndjson',body:scenario==='empty'?' {"done":true}\n':scenario==='invalid'?' {"content":{"text":"invalid"},"done":true}\n':'invalid json\n'}));
  await page.getByLabel('Message',{exact:true}).fill('what is python language');
  await page.getByRole('button',{name:'Send'}).click();
  await expect(page.getByLabel('Message',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Message',{exact:true})).toHaveValue('what is python language');
  expect(errors).toEqual([]);
 });
}

test('chat works when browser lacks Array.at',async({page})=>{
 await page.addInitScript(()=>{Array.prototype.at=undefined});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await app(page,route=>route.fulfill({contentType:'application/x-ndjson',body:'{"content":"Python is a programming language.","done":false}\n{"done":true}\n'}));
 await page.getByLabel('Message',{exact:true}).fill('what is python language');
 await page.getByRole('button',{name:'Send'}).click();
 await expect(page.locator('article.assistant')).toContainText('Python is a programming language.');
 await expect(page.getByLabel('Message',{exact:true})).toBeVisible();
 expect(errors).toEqual([]);
});

for(const mode of ['throws','promise','missing']){
 test(`scrollIntoView ${mode} cannot crash token rendering`,async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(mode=>{Element.prototype.scrollIntoView=mode==='missing'?undefined:mode==='promise'?()=>Promise.resolve():()=>{throw new TypeError('scroll failure')}},mode);
  await app(page,route=>route.fulfill({contentType:'application/x-ndjson',body:'{"content":"Python is a programming language.","done":false}\n{"done":true}\n'}));
  await page.getByLabel('Message',{exact:true}).fill('what is python language');
  await page.getByRole('button',{name:'Send'}).click();
  await expect(page.locator('article.assistant')).toContainText('Python is a programming language.');
  await expect(page.getByRole('heading',{name:'The chat display stopped.'})).toHaveCount(0);
  expect(errors).toEqual([]);
 });
}

test('recovery includes and reports the actual display error',async({page})=>{
 const reports=[];
 await app(page,route=>route.fulfill({contentType:'application/x-ndjson',body:'{"content":"Hello","done":true}\n'}));
 await page.route('**/api/client-error',route=>{reports.push(route.request().postDataJSON());return route.fulfill({json:{ok:true}})});
 await page.evaluate(()=>{const Original=window.Number;function NumberWithFault(value){if(value===1024)throw new TypeError('Diagnostic regression error');return Original(value)}Object.setPrototypeOf(NumberWithFault,Original);window.Number=NumberWithFault});
 await page.getByLabel('Message',{exact:true}).fill('what is python language');
 await expect(page.getByRole('heading',{name:'The chat display stopped.'})).toBeVisible();
 await expect(page.locator('.recovery .fine')).toContainText('TypeError: Diagnostic regression error');
 await expect(page.getByRole('button',{name:'Reload chat'})).toBeVisible();
 await expect.poll(()=>reports.length).toBeGreaterThan(0);
 expect(reports[0].message).toBe('Diagnostic regression error');
});

for(const show of [false,true]){
 test(`reasoning is separate from final answer with visibility ${show}`,async({page})=>{
  await app(page,route=>{
   expect(route.request().postDataJSON().think).toBe(show);
   const first=show?{thinking:'Separate reasoning text',phase:'thinking',done:false}:{phase:'thinking',done:false};
   return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify(first)+'\n'+JSON.stringify({content:'FastAPI builds Python APIs.',phase:'answer',done:true})+'\n'});
  });
  await expect(page.getByLabel('Output tokens')).toHaveValue('1024');
  const toggle=page.getByRole('checkbox',{name:'Show thinking'});
  await expect(toggle).not.toBeChecked();
  if(show)await toggle.check();
  await page.getByLabel('Message',{exact:true}).fill('What is FastAPI?');
  await page.getByRole('button',{name:'Send'}).click();
  await expect(page.locator('article.assistant > div')).toHaveText('FastAPI builds Python APIs.');
  if(show){
   await expect(page.getByText('Separate reasoning text')).not.toBeVisible();
   await page.locator('article.assistant summary').click();
   await expect(page.getByText('Separate reasoning text')).toBeVisible();
  }else{
   await expect(page.getByText('Separate reasoning text')).toHaveCount(0);
   await expect(page.locator('article.assistant details')).toHaveCount(0);
  }
 });
}
