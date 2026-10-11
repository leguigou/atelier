// Reproduce tall video cards with long tags and several folder memberships.
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
    for(const width of [320,390,430,600]){
      const context=await browser.newContext({viewport:{width,height:844},hasTouch:true,isMobile:true}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      const post=async(route,data)=>{const res=await context.request.post(base+route,{data});assert(res.ok(),await res.text());return res.json()};
      const library=await (await context.request.get(base+'/api/library')).json();
      const source=library.sources.find(s=>s.kind==='Vidéo'&&s.segment_count>0);
      assert(source,'A seeded video is required');
      await post('/api/annotation',{id:source.id,tags:['MATIERE_TON_IDEE_VAUT_OR_ET_SE_TRANSFORME_EN_PROJET','Entrepreneuriat']});
      let book=await post('/api/v1/books',{title:'Cartes mobiles '+width});
      const change=async data=>{book=await post('/api/v1/books/'+book._book_id+'/research',{revision:book._revision,...data})};
      await change({action:'add',source_ids:[source.id]});
      for(const name of ['01. Entrepreneuriat & création d’entreprise','04. Psychologie & comportement','06. Productivité & développement personnel'])await change({action:'folder-create',name});
      await change({action:'classify',source_ids:[source.id],folder_ids:book.research.folders.map(f=>f.id)});
      await page.goto(base);await page.locator('[data-open-book="'+book._book_id+'"]').first().click();await page.locator('#overviewNext').waitFor();
      await page.locator('[data-mobile-nav=folders]').click();await page.locator('[data-folder-open]').first().click();
      const card=page.locator('.source-card').first();await card.scrollIntoViewIfNeeded();
      const geometry=await card.evaluate(e=>{
        const rect=s=>e.querySelector(s).getBoundingClientRect(),outer=e.getBoundingClientRect(),cover=rect('.cover'),tools=rect('.research-item-tools'),title=rect('.card-title'),footer=rect('.card-footer');
        return {width:outer.width,height:outer.height,cover:{width:cover.width,height:cover.height},tools:{width:tools.width,left:tools.left-outer.left},titleWidth:title.width,footerWidth:footer.width};
      });
      assert.equal(geometry.cover.width,88);assert.equal(geometry.cover.height,66);
      assert(geometry.tools.width>geometry.width-4,'Folder actions must span the card');
      assert(geometry.footerWidth>geometry.width-4,'Reading status and actions must span the card');
      assert(geometry.height<440,'A source card must not become a tall empty column');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      for(const selector of ['[data-like]','[data-archive]','[data-research-source]']){
        assert(await card.locator(selector).evaluate(e=>{const r=e.getBoundingClientRect();return r.width>=44&&r.height>=44}));
      }
      await page.screenshot({path:path.join(process.env.TEMP,`atelier-source-mobile-${width}.png`)});
      await card.locator('[data-research-source]').click();await page.locator('#researchClassifyForm').waitFor();
      await page.locator('#modal [data-close]').click();
      const liked=await card.locator('[data-like]').evaluate(e=>e.classList.contains('liked'));
      await card.locator('[data-like]').click();await page.waitForFunction(before=>document.querySelector('[data-like]')?.classList.contains('liked')!==before,liked);
      await card.locator('[data-open]').first().click();await page.locator('#back').filter({hasText:'Retour au dossier'}).click();
      await page.locator('#backToFolders').click();await page.locator('[data-mobile-nav=library]').click();
      await page.locator('.source-card').waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.equal(await page.evaluate(()=>innerWidth),width,'Long folder labels must not expand the mobile viewport');await page.locator('[data-mobile-nav=common]').click();await page.locator('#search').fill(source.title);
      await page.locator('.source-card').first().waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('Mobile video cards passed at 320, 390, 430 and 600 px: geometry, touch actions, classification and return to dossier.');
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
