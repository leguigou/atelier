// Mobile layout checks against disposable data, including long project titles.
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
    for(const width of [320,360,390,430]){
      const context=await browser.newContext({viewport:{width,height:844},hasTouch:true,isMobile:true}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      const library=await (await context.request.get(base+'/api/library?compact=1')).json(),source=library.sources.find(s=>s.title==='Source de vérification');
      const book=await (await context.request.get(base+'/api/book?book_id=book-main')).json();
      await context.request.post(base+'/api/book-research',{data:{book_id:'book-main',revision:book._revision,action:'add',source_ids:[source.id]}});
      await context.request.post(base+'/api/idea',{data:{title:'Une idée avec un titre assez long pour vérifier la disposition sur téléphone',notes:'Une note courte qui accompagne cette idée.',tags:['Recherche','Écriture','Sources'],refs:[{source_id:source.id,start:0,end:0}]}});
      const check=async name=>{
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width} ${name}: page overflow`);
        assert.equal(await page.locator('.main').evaluate(e=>getComputedStyle(e).paddingLeft),'12px',`${width} ${name}: consistent left gutter`);
        assert.equal(await page.locator('.main').evaluate(e=>getComputedStyle(e).paddingRight),'12px',`${width} ${name}: consistent right gutter`);
        if(name==='overview'){
          const cards=await page.locator('.main>.book-next-step,.main>.book-presentation,.main>.stats,.research-start>.panel,.main>.panel').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,padding:s.paddingLeft}}));
          for(let i=1;i<cards.length;i++)assert(Math.abs(cards[i].top-cards[i-1].bottom-12)<1,`${width}: overview card ${i} gap must be 12 px, got ${cards[i].top-cards[i-1].bottom}`);
          assert(cards.every(c=>Math.abs(c.left-12)<1&&Math.abs(c.right-(width-12))<1),`${width}: overview cards must align`);
        }
        const selectors={sources:'.common-collection [data-common-section],.common-collection [data-research-collection]',ideas:'.common-collection [data-common-section],.common-collection [data-research-collection]','idea-row':'.shared-idea-card:first-child .idea-row-actions button','chapter-actions':'.chapter-ai-actions button',reader:'.reader-author-tools button'};
        if(selectors[name]){
          const rects=await page.locator(selectors[name]).evaluateAll(buttons=>buttons.map(b=>{const r=b.getBoundingClientRect();return {top:r.top,height:r.height,left:r.left,right:r.right}}));
          assert(rects.length>1,`${width} ${name}: action group missing`);
          assert(rects.every(r=>Math.abs(r.top-rects[0].top)<2),`${width} ${name}: unnecessary action wrap`);
          assert(rects.every(r=>r.height>=44),`${width} ${name}: touch target under 44 px`);
          assert(rects.every(r=>r.left>=0&&r.right<=width),`${width} ${name}: action outside viewport`);
        }
        if(name==='insert')assert.equal(await page.locator('.insert-bar button').evaluateAll(buttons=>buttons.some(b=>{const walker=document.createTreeWalker(b,NodeFilter.SHOW_TEXT),tops=[];while(walker.nextNode()){if(!walker.currentNode.textContent.trim())continue;const range=document.createRange();range.selectNodeContents(walker.currentNode);for(const r of range.getClientRects())tops.push(Math.round(r.top))}return new Set(tops).size>1})),false,`${width}: insertion button text wraps`);
        const groups=await page.evaluate(()=>[...document.querySelectorAll('.research-context,.common-collection>.row,.research-collection>.row,.idea-row-heading,.research-item-tools,.book-command,.book-modes,.chapter-ai-actions,.insert-bar,.reading-header,.reader-author-tools,.reading-controls')].filter(e=>e.getBoundingClientRect().height).slice(0,8).map(e=>({group:e.className,width:Math.round(e.clientWidth),buttons:[...e.querySelectorAll(':scope>button')].filter(b=>b.getBoundingClientRect().height).map(b=>({text:b.textContent.trim(),x:Math.round(b.getBoundingClientRect().x),y:Math.round(b.getBoundingClientRect().y),width:Math.round(b.getBoundingClientRect().width),height:Math.round(b.getBoundingClientRect().height)}))})));
        if(process.env.LAYOUT_AUDIT)console.log(width,name,JSON.stringify(groups));
        await page.screenshot({path:path.join(process.env.TEMP,`atelier-mobile-${name}-${width}.png`)});
      };
      await page.goto(base);await page.locator('[data-open-book="book-main"]').first().click();await page.locator('#overviewNext').waitFor();await check('overview');
      await page.locator('#overviewCommon').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(process.env.TEMP,`atelier-mobile-overview-spacing-${width}.png`)});
      await page.locator('[data-mobile-nav=common]').click();await check('sources');
      await page.locator('[data-common-section=ideas]').click();await check('ideas');
      await page.locator('.shared-idea-card').first().scrollIntoViewIfNeeded();await check('idea-row');
      await page.locator('[data-research-collection=book]').click();await check('project-ideas');
      await page.locator('[data-mobile-nav=library]').click();await check('project-sources');
      await page.locator('#import').click();await page.locator('.import-tabs').waitFor();await check('import');
      await page.locator('#modal [data-close]').click();
      await page.locator('#search').fill('Source de vérification');
      await page.locator('.card-title').filter({hasText:'Source de vérification'}).click();await page.locator('#back').waitFor();await check('source-reader');
      await page.locator('[data-mobile-nav=book]').click();await check('writer');
      await page.locator('.chapter-ai-actions').scrollIntoViewIfNeeded();await check('chapter-actions');
      await page.locator('.insert-bar').scrollIntoViewIfNeeded();await check('insert');
      await page.locator('#modeRead').click();await page.locator('#readerReviews').waitFor();await check('reader');
      await page.locator('#readerSelect').click();await check('reader');
      assert.equal(await page.locator('#readerSelect').getAttribute('aria-pressed'),'true');
      await page.locator('#readerSelect').click();
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('Mobile layout passed at 320, 360, 390 and 430 px.');
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
