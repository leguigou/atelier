// A remembered book must not filter Sources when browsing outside its workspace.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const fixture=spawn(process.env.PYTHON||'python',[path.join(__dirname,'reader_fixture.py')],{stdio:['ignore','pipe','pipe']});
  fixture.stderr.on('data',s=>process.stderr.write(s));let browser;
  try{
    const base=await new Promise((resolve,reject)=>{fixture.stdout.once('data',s=>resolve(s.toString().trim()));fixture.once('exit',code=>reject(Error('Fixture exited '+code)))});
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
    for(const width of [1280,390]){
      const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      const response=await context.request.post(base+'/api/book-create',{data:{title:'Livre sans sources '+width}});
      assert.equal(response.status(),200);const book=await response.json();
      await page.goto(base);await page.locator('#createResearchBook').waitFor();
      await page.evaluate(id=>localStorage.setItem('atelier-last-book',id),book._book_id);
      await page.reload();await page.locator('#browseCommonResources').waitFor();
      const sources=()=>page.locator(width<760?'[data-mobile-nav=library]':'[data-nav=library]');
      const books=()=>page.locator(width<760?'[data-mobile-nav=books]':'[data-nav=books]');
      await sources().click();
      await page.locator('.shared-source-grid').waitFor();
      assert(await page.evaluate(()=>commonResearch&&filtered().length===state.sources.filter(s=>!s.archived).length));
      assert.equal(await page.locator('#researchBookSelect').count(),0);
      await page.locator('[data-common-section=ideas]').click();
      await sources().click();await page.locator('.shared-source-grid').waitFor();
      assert(await page.evaluate(()=>commonResearch));
      await books().click();await page.locator('[data-open-book="'+book._book_id+'"]').first().click();
      await page.locator('#overviewNext').waitFor();
      await sources().click();await page.locator('#researchBookSelect').waitFor();
      assert(await page.evaluate(()=>!commonResearch&&filtered().length===0));
      assert.equal(await page.locator('#researchBookSelect').inputValue(),book._book_id);
      await page.locator('[data-research-collection=common]').click();await page.locator('.shared-source-grid').waitFor();
      await sources().click();assert(await page.evaluate(()=>commonResearch));
      await books().click();await page.locator('#browseCommonResources').click();
      await page.locator('.shared-source-grid').waitFor();
      assert(await page.evaluate(()=>commonResearch&&filtered().length>0));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('Global resource navigation passed on desktop and mobile with a remembered empty book.');
  }finally{await browser?.close();fixture.kill()}
})().catch(error=>{console.error(error);process.exitCode=1});
