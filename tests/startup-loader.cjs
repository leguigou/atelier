// Check the first paint under a delayed response, then success, login and failure.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const fixture=spawn(process.env.PYTHON||'python',[path.join(__dirname,'reader_fixture.py')],{stdio:['ignore','pipe','pipe']});
  fixture.stderr.on('data',s=>process.stderr.write(s));let browser;
  try{
    const base=await new Promise((resolve,reject)=>{fixture.stdout.once('data',s=>resolve(s.toString().trim()));fixture.once('exit',code=>reject(Error('Fixture exited '+code)))});
    browser=await chromium.launch({headless:true});
    for(const width of [390,1280]){
      for(const outcome of ['ready','login','error']){
        const context=await browser.newContext({viewport:{width,height:844},reducedMotion:outcome==='login'?'reduce':'no-preference'}),page=await context.newPage(),errors=[];
        page.on('pageerror',e=>errors.push(e.message));
        let release;const gate=new Promise(resolve=>release=resolve);
        await page.route('**/api/library?*',async route=>{await gate;if(outcome==='ready')await route.continue();else await route.fulfill({status:outcome==='login'?401:503,contentType:'application/json',body:JSON.stringify({error:outcome==='login'?'Connexion requise':'Chargement indisponible'})})});
        await page.goto(base,{waitUntil:'domcontentloaded'});
        await page.locator('.startup-loader').waitFor();
        assert.equal(await page.locator('.startup-loader').getAttribute('aria-busy'),'true');
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        if(outcome==='login')assert.equal(await page.locator('.startup-cloud i').first().evaluate(e=>getComputedStyle(e).animationName),'startup-breathe');
        await page.locator('.startup-content').evaluate(async e=>{await Promise.all(e.getAnimations().map(a=>a.finished))});
        if(outcome==='login'){
          const read=()=>page.locator('.startup-cloud i').evaluateAll(nodes=>nodes.map(e=>({opacity:Number(getComputedStyle(e).opacity),transform:getComputedStyle(e).transform})));
          const before=await read();await page.waitForTimeout(350);const after=await read();
          assert(after.every(p=>p.transform==='none'),'Reduced motion keeps the particles in place');
          assert(before.some((p,i)=>Math.abs(p.opacity-after[i].opacity)>.03),'Reduced motion keeps a visible loading pulse');
        }
        if(outcome==='ready'){
          const positions=()=>page.locator('.startup-cloud i').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y}}));
          const before=await positions();await page.waitForTimeout(350);const after=await positions();
          assert(before.filter((p,i)=>Math.hypot(p.x-after[i].x,p.y-after[i].y)>3).length>=6,'The particle cloud must visibly move, not just declare an animation');
        }
        await page.screenshot({path:path.join(process.env.TEMP,`atelier-loader-${width}-${outcome}.png`)});
        release();
        await page.locator(outcome==='ready'?'#createResearchBook':outcome==='login'?'#loginForm':'.empty').waitFor();
        assert.equal(await page.locator('.startup-loader').count(),0);
        assert.deepEqual(errors,[]);await context.close();
      }
    }
    console.log('Startup loader passed on mobile and desktop: delayed loading, ready, login, failure and reduced motion.');
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
