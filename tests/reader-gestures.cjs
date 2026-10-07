const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    for (const viewport of [{width:390,height:844},{width:1280,height:900}]) {
      const page = await browser.newPage({viewport, hasTouch:true});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.setContent('<div id="app"></div><style>'+fs.readFileSync(path.join(__dirname,'../public/style.css'),'utf8')+fs.readFileSync(path.join(__dirname,'../public/mobile.css'),'utf8')+'</style>');
      const source=fs.readFileSync(path.join(__dirname,'../public/studio.js'),'utf8');
      await page.addScriptTag({content: `
        const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
        const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const assetUrl=id=>id;
        let reading=null,readingIndex=0,readingFont=17,readingAbort=null,readingResize=null;
        ${source.slice(source.indexOf('async function openPages('),source.indexOf('\naddToBookModal='))}
        window.testReader={open:()=>openPages({title:'Livre test',book:true,sections:[{title:'Second chapitre',blocks:[{type:'text',text:'Introduction du second chapitre. '.repeat(20)}]},{title:'Dernier chapitre',blocks:[{type:'text',text:'Un texte suffisamment long pour vérifier la pagination et les gestes. '.repeat(250)}]}]}), index:()=>readingIndex, count:()=>pageList.length};
      `});
      await page.evaluate(()=>testReader.open());
      assert.ok(await page.evaluate(()=>testReader.count()>3));
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`reader-${viewport.width}.png`)});
      const touch=await page.context().newCDPSession(page);
      const frame=await page.locator('#pageFrame').boundingBox();
      const x=frame.x+frame.width/2,y=frame.y+frame.height/2;
      await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
      for(let step=1;step<=6;step++){await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y-step*20}]});await page.waitForTimeout(30)}
      await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(100);
      assert.equal(await page.locator('#readerContents').isVisible(),true,'native upward swipe opens chapters');
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`reader-toc-${viewport.width}.png`)});
      const chapters=page.locator('[data-toc-page]');
      assert.equal(await chapters.count(),2);
      assert.match(await chapters.nth(1).innerText(),/p\. \d+/,'chapter page numbers');
      const target=Number(await chapters.nth(1).getAttribute('data-toc-page'));
      await chapters.nth(1).click();
      assert.equal(await page.evaluate(()=>testReader.index()),target,'chapter click jumps to exact page');
      assert.equal(await page.locator('#readerContents').isVisible(),false,'chapter click closes list');
      await page.locator('.page-stage').hover();await page.mouse.wheel(0,-100);
      assert.equal(await page.locator('#readerContents').isVisible(),true,'upward wheel opens list');
      assert.equal(await chapters.nth(1).getAttribute('aria-current'),'location','current chapter highlighted');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#readerContents').isVisible(),false,'Escape closes list');
      assert.equal(await page.locator('#readingOverlay').count(),1,'Escape preserves reader');
      await page.evaluate(()=>{readingIndex=0;showPage()});
      const gesture=async(dx,dy=0,cancel=false)=>{
        await page.evaluate(({dx,dy,cancel})=>{
          const stage=document.querySelector('.page-stage');
          stage.setPointerCapture=()=>{};stage.hasPointerCapture=()=>false;
          const event=(type,x,y)=>stage.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerId:1,pointerType:'touch',isPrimary:true,clientX:x,clientY:y}));
          event('pointerdown',180,250);event('pointermove',180+dx,250+dy);
          event(cancel?'pointercancel':'pointerup',180+dx,250+dy);
        },{dx,dy,cancel});
        await page.waitForTimeout(320);
      };
      await gesture(-130);assert.equal(await page.evaluate(()=>testReader.index()),1,'swipe left advances');
      await gesture(130);assert.equal(await page.evaluate(()=>testReader.index()),0,'swipe right returns');
      await gesture(130);assert.equal(await page.evaluate(()=>testReader.index()),0,'first page boundary');
      await gesture(-6);assert.equal(await page.evaluate(()=>testReader.index()),1,'small swipe finishes advancing');
      await gesture(6);assert.equal(await page.evaluate(()=>testReader.index()),0,'small swipe finishes returning');
      await gesture(-2);assert.equal(await page.evaluate(()=>testReader.index()),0,'tap jitter ignored');
      await gesture(-130,0,true);assert.equal(await page.evaluate(()=>testReader.index()),0,'cancel returns');
      await gesture(0,-20);assert.equal(await page.locator('#readerContents').isVisible(),false,'short upward swipe ignored');
      await gesture(0,-130,true);assert.equal(await page.locator('#readerContents').isVisible(),false,'cancelled upward swipe ignored');
      await gesture(-20,130);assert.equal(await page.evaluate(()=>testReader.index()),0,'vertical gesture ignored');
      await page.locator('.page-stage').hover();await page.mouse.wheel(2,0);await page.waitForTimeout(320);
      assert.equal(await page.evaluate(()=>testReader.index()),1,'small horizontal trackpad scroll advances');
      await page.mouse.wheel(2,0);assert.equal(await page.evaluate(()=>testReader.index()),1,'scroll tail does not turn a second page');
      await page.waitForTimeout(500);await page.mouse.wheel(-2,0);await page.waitForTimeout(320);
      assert.equal(await page.evaluate(()=>testReader.index()),0,'small horizontal trackpad scroll returns');
      await page.mouse.wheel(0,150);assert.equal(await page.evaluate(()=>testReader.index()),0,'vertical wheel ignored');
      await page.locator('#nextPage').click();await page.waitForTimeout(320);
      await page.keyboard.press('ArrowRight');await page.waitForTimeout(320);
      assert.equal(await page.evaluate(()=>testReader.index()),2,'button and keyboard advance');
      await page.evaluate(()=>{readingIndex=pageList.length-1;showPage()});
      await gesture(-130);assert.equal(await page.evaluate(()=>testReader.index()),await page.evaluate(()=>testReader.count()-1),'last page boundary');
      await page.emulateMedia({reducedMotion:'reduce'});await gesture(130);
      assert.equal(await page.evaluate(()=>testReader.index()),await page.evaluate(()=>testReader.count()-2),'reduced motion');
      assert.equal(await page.locator('.page-preview').count(),0,'previews cleaned');
      assert.equal(await page.locator('#pageTrack').evaluate(e=>e.style.transform),'','transform reset');
      await page.emulateMedia({reducedMotion:'no-preference'});
      await page.evaluate(()=>{turnPage(-1);closePages()});await page.waitForTimeout(320);
      assert.equal(await page.locator('#readingOverlay').count(),0,'close during animation');
      assert.deepEqual(errors,[]);
      console.log(`${viewport.width}px: pagination, gestures, wheel, buttons, keyboard, boundaries, cancellation, reduced motion, upward swipe and clickable chapters OK`);
      await page.close();
    }
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
