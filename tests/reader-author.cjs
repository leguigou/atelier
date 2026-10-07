// Run with Playwright installed: node tests/reader-author.cjs
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const fixture=spawn(process.env.PYTHON||'python',[path.join(__dirname,'reader_fixture.py')],{stdio:['ignore','pipe','pipe']});
  fixture.stderr.on('data',s=>process.stderr.write(s));
  let browser;
  try{
    const base=await new Promise((resolve,reject)=>{fixture.stdout.once('data',s=>resolve(s.toString().trim()));fixture.once('exit',code=>reject(Error('Fixture exited '+code)))});
    browser=await chromium.launch({headless:true});
    for(const width of [1280,390]){
      const context=await browser.newContext({viewport:{width,height:900},hasTouch:true});
      const page=await context.newPage(),errors=[],failedRequests=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
      page.on('requestfailed',r=>failedRequests.push({url:r.url(),error:r.failure()?.errorText}));
      await page.goto(base);await page.locator(width<760?'[data-mobile-nav="book"]':'[data-nav="book"]').click();
      try{await page.locator('#modeRead').click()}catch(error){console.error('Reader startup:',errors,failedRequests,await page.locator('#app').innerText());throw error}
      await page.locator('#readerReviews').waitFor();
      await page.locator('#readerToc').click();await page.locator('[data-toc-page]').first().click();
      await page.locator('#pageContent [data-read-block]').first().click();
      await page.locator('#readerSources').click();await page.locator('[data-reading-source]').first().click();
      await page.locator('#readerSourceContent').getByText('Le passage original de la source.').waitFor();
      await page.keyboard.press('Escape');assert.equal(await page.locator('#readingOverlay').count(),1);
      await page.locator('#pageContent [data-read-block]').first().click();await page.locator('#readerNote').click();
      await page.locator('#readerNoteText').fill('Clarifier cette introduction');await page.locator('#readerAddNote').click();
      await page.locator('#readerPanel').waitFor({state:'detached'});
      await page.locator('#readerReviews').click();await page.locator('[data-review-jump]').first().click();
      await page.locator('#pageContent [data-read-block]').first().click();await page.locator('#readerEdit').click();
      const original=await page.locator('#readerEditText').inputValue();assert.match(original,/Introduction/);
      await page.locator('#readerEditText').fill('Introduction corrigée depuis la lecture.');
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-edit-${width}.png`)});
      await page.locator('#readerSaveResume').click();await page.locator('#readerPanel').waitFor({state:'detached'});
      await page.locator('#pageContent').getByText('Introduction corrigée depuis la lecture.',{exact:true}).waitFor();
      const saved=await (await context.request.get(base+'/api/book')).json();
      assert.match(saved.chapters[0].blocks[0].text,/^Introduction corrigée depuis la lecture\.\n\nLe passage/);
      assert.match(saved.chapters[0].blocks[0].text,/Conclusion conservée\.$/);
      assert.equal(saved.chapters[0].status,'review');assert.equal(saved.review_notes.at(-1).text,'Clarifier cette introduction');
      await page.locator('#readerToc').click();await page.locator('[data-toc-page]').nth(1).click();
      const anchor=await page.evaluate(()=>JSON.parse(localStorage.getItem('atelier-reading:book-main')));assert.equal(anchor.chapter_id,'chapter-two');
      await page.locator('#largerFont').click();await page.waitForFunction(()=>document.querySelector('#pageContent').textContent.includes('Le second chapitre'));
      await page.locator('#closeReading').click();await page.locator('#modeRead').click();
      await page.locator('#pageContent').getByText(/Le second chapitre/).waitFor();
      await page.locator('#closeReading').click();await page.reload();
      await page.locator(width<760?'[data-mobile-nav="book"]':'[data-nav="book"]').click();await page.locator('#modeRead').click();
      await page.locator('#pageContent').getByText(/Le second chapitre/).waitFor();
      await page.locator('#readerToc').click();await page.locator('[data-edit-chapter="chapter-two"]').click();
      assert.equal(await page.locator('#chapterTitle').inputValue(),'Deuxième chapitre');
      await page.locator('#chapterReviewStatus').selectOption('done');await page.locator('#saveNow').click();
      await page.locator('#modeReview').click();await page.locator('.reader-review-list').waitFor();
      await page.locator('[data-review-done]').last().click();await page.getByRole('button',{name:'✓ Terminé · rouvrir'}).last().waitFor();
      await page.keyboard.press('Escape');await page.locator('#closeReading').click();
      await page.locator('#modeRead').click();await page.locator('#readerToc').click();await page.locator('[data-toc-page]').first().click();
      await page.locator('#pageContent [data-read-block]').first().click();await page.locator('#readerEdit').click();
      await page.route('**/api/book',route=>route.request().method()==='POST'?route.abort():route.continue());
      await page.locator('#readerEditText').fill('Brouillon protégé pendant la lecture.');await page.locator('#readerSaveResume').click();
      await page.waitForFunction(()=>document.querySelector('#readerPanelStatus')?.textContent.includes('Brouillon conservé'));
      assert.equal(await page.locator('#readerEditText').inputValue(),'Brouillon protégé pendant la lecture.');
      assert.match(await page.locator('#readerPanelStatus').innerText(),/Brouillon conservé/);
      assert.match(await page.evaluate(async()=>(await AtelierDrafts.get('book-main')).book.chapters[0].blocks[0].text),/^Brouillon protégé/);
      // A concurrent server edit must show the existing conflict recovery UI.
      const concurrent=await (await context.request.get(base+'/api/book')).json();concurrent.chapters[0].blocks[0].text=concurrent.chapters[0].blocks[0].text.replace(/^[\s\S]*?\n\n/,'Introduction depuis une autre session.\n\n');
      await context.request.post(base+'/api/book',{data:concurrent});await page.unroute('**/api/book');
      await page.locator('#readerSaveResume').click();await page.locator('#reloadBook').waitFor();
      assert.equal(await page.locator('#readingOverlay').count(),0);
      assert.match(await page.evaluate(async()=>(await AtelierDrafts.get('book-main')).book.chapters[0].blocks[0].text),/^Brouillon protégé/);
      await page.locator('#reloadBook').click();await page.waitForFunction(()=>!bookDirty);
      // Restore the first paragraph for the mobile run, keeping notes and versions.
      const book=await (await context.request.get(base+'/api/book')).json();book.chapters[0].blocks[0].text=book.chapters[0].blocks[0].text.replace(/^[\s\S]*?\n\n/,'Introduction conservée.\n\n');
      await context.request.post(base+'/api/book',{data:book});
      assert.deepEqual(errors,[]);await context.close();console.log(`${width}px: edit, sources, notes, resume, repagination, chapter status and review OK`);
    }
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
