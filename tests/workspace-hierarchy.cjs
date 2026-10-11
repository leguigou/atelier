// Follow the suggested next action from a new project through the first chapter.
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
    for(const width of [1280,390]){
      const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.goto(base);await page.locator('#createResearchBook').click();
      await page.locator('#newBookForm [name=title]').fill('Parcours guidé '+width);
      await page.locator('#newBookForm button[type=submit]').click();
      await page.locator('#overviewNext[data-next-step=intention]').waitFor();
      assert(await page.locator('.book-next-step').evaluate(e=>e.getBoundingClientRect().top<document.querySelector('.book-presentation').getBoundingClientRect().top));
      await page.screenshot({path:path.join(process.env.TEMP,`atelier-hierarchy-overview-${width}.png`),fullPage:true});
      await page.locator('#overviewNext').click();await page.locator('#briefForm [name=intention]').fill('Comprendre les idées et leurs sources.');
      await page.locator('#briefForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      const nav=v=>page.locator(width<760?`[data-project-section="${v}"]`:`[data-nav="${v}"]`).click();
      await nav('overview');await page.locator('#overviewNext[data-next-step=sources]').waitFor();
      await page.locator('#overviewNext').click();await page.locator('#researchPickerQuery').fill('Source de vérification');
      await page.locator('[data-research-pick]').check();await page.locator('#researchPickerSave').click();await page.locator('#modal').waitFor({state:'hidden'});
      assert.equal(await page.locator('.workspace-guide').count(),1);
      await nav('overview');await page.locator('#overviewNext[data-next-step=plan]').click();
      await page.locator('#newChapterForm [name=title]').fill('Mon premier chapitre');
      await page.locator('#newChapterForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      await page.locator('#saveNow').click();await nav('overview');await page.locator('#overviewNext[data-next-step=write]').click();
      assert.equal(await page.locator('#chapterTitle').inputValue(),'Mon premier chapitre');
      assert(await page.locator('[data-block-text]').first().evaluate(e=>e===document.activeElement));
      assert.equal(await page.locator('.writer-preparation').getAttribute('open'),null);
      assert(await page.locator('.writer-layout').evaluate(e=>e.getBoundingClientRect().top<document.querySelector('.book-access-actions').getBoundingClientRect().top));
      await page.screenshot({path:path.join(process.env.TEMP,`atelier-hierarchy-writer-${width}.png`),fullPage:true});
      await nav('ideas');
      assert((await page.locator('.crumb').innerText()).includes('Parcours guidé '+width));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      const common=page.locator(width<760?'[data-mobile-nav=common]':'[data-nav=common]');await common.click();
      await page.locator('.workspace-scope').waitFor();assert(!(await page.locator('.crumb').innerText()).includes('Parcours guidé'));
      if(width===1280){await page.locator('[data-nav=settings]').click();assert.equal(await page.locator('[data-nav=settings]').getAttribute('aria-current'),'page');assert.equal(await page.locator('.crumb').innerText(),'Votre espace / Réglages')}
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('Workspace hierarchy passed on desktop and mobile: intention, sources, plan, resume writing and clear scope.');
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
