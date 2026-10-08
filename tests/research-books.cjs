// Integration checks against a disposable database, on desktop and mobile.
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
      const context=await browser.newContext({viewport:{width,height:900},hasTouch:true});
      const page=await context.newPage(),errors=[],failed=[];page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>failed.push({url:r.url(),error:r.failure()?.errorText}));
      const nav=v=>page.locator(width<760?`[data-mobile-nav="${v}"]`:`[data-nav="${v}"]`).click();
      await page.goto(base);try{await page.locator('#createResearchBook').waitFor()}catch(e){console.error('Startup failed:',width,errors,failed,await page.locator('#app').innerText(),await page.evaluate(()=>({view,ready:document.readyState,scriptUrls:[...document.scripts].map(s=>s.src)})));throw e};assert.equal(await page.locator('.project-book').first().evaluate(e=>getComputedStyle(e).display),'flex');
      await page.locator('#createResearchBook').click();await page.locator('#newBookForm [name=title]').fill('Livre A '+width);
      await page.locator('#newBookForm [name=description]').fill('Une recherche sur les relations.');
      await page.locator('#newBookForm button[type=submit]').click();await page.locator('#overviewSources').waitFor();
      const aid=await page.locator('#researchBookSelect').inputValue();
      await page.locator('#overviewCover').click();await page.locator('#coverFile').setInputFiles({name:'couverture.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64')});
      await page.locator('#coverUploadForm button[type=submit]').click();await page.locator('.cover-variant.selected').waitFor();await page.locator('#modal [data-close]').click();await page.locator('#overviewCoverPreview img').waitFor();
      const withCover=await (await context.request.get(base+'/api/book?book_id='+aid)).json();assert(withCover.covers.front);
      await page.locator('#overviewDownload').click();assert.equal(await page.locator('[data-export]').count(),3);const downloaded=page.waitForEvent('download');await page.locator('[data-export="pdf"]').click();assert.equal((await downloaded).suggestedFilename(),'mon-livre-A5.pdf');await page.locator('#modal').waitFor({state:'hidden'});
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-book-actions-${width}.png`),fullPage:true});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));

      await page.locator('#overviewSources').click();assert.equal(await page.locator('.source-card').count(),0);
      await page.locator('#pickResearch').click();await page.locator('#researchPickerQuery').fill('Source de vérification');
      await page.locator('[data-research-pick]').check();const sid=await page.locator('[data-research-pick]').getAttribute('data-research-pick');
      await page.locator('#researchPickerSave').click();await page.locator('[data-research-source]').waitFor();
      for(const name of ['Peur','Relations']){await nav('folders');await page.locator('#newResearchFolder').click();await page.locator('#researchFolderForm [name=name]').fill(name);await page.locator('#researchFolderForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'})}
      await nav('library');await page.locator('[data-research-source]').click();
      for(const input of await page.locator('[name=folder_ids]').all())await input.check();
      await page.locator('#researchNote').fill('Une note réservée au livre A.');await page.locator('#researchClassifyForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      let book=await (await context.request.get(base+'/api/book?book_id='+aid)).json();
      assert.equal(book.research.folders.length,2);assert(book.research.folders.every(f=>f.source_ids.includes(sid)));
      assert.equal(book.research.source_notes[sid],'Une note réservée au livre A.');
      await page.locator('#researchFolderFilter').selectOption('unfiled');assert.equal(await page.locator('.source-card').count(),0);
      await nav('books');await page.locator('#createResearchBook').click();await page.locator('#newBookForm [name=title]').fill('Livre B '+width);await page.locator('#newBookForm button[type=submit]').click();await page.locator('#overviewSources').waitFor();
      const bid=await page.locator('#researchBookSelect').inputValue();await page.locator('#overviewSources').click();
      await page.locator('#pickResearch').click();await page.locator('#researchPickerQuery').fill('Source de vérification');await page.locator('[data-research-pick]').check();await page.locator('#researchPickerSave').click();await page.locator('[data-research-source]').waitFor();
      await page.locator('[data-research-source]').click();assert.equal(await page.locator('#researchNote').inputValue(),'');await page.locator('[data-close]').click();
      await page.locator('.card-title[data-open]').click();if(width<760)await page.locator('.mobile-reader-notes summary').click();await page.locator('#notes').fill('Note de lecture du livre B');await page.locator('#saveAnnotation').click();await page.getByText('Note enregistrée pour ce livre.',{exact:true}).waitFor();
      book=await (await context.request.get(base+'/api/book?book_id='+bid)).json();assert.equal(book.research.source_notes[sid],'Note de lecture du livre B');
      const shared=await (await context.request.get(base+'/api/source?id='+sid)).json();assert.equal(shared.annotation.notes,'');

      await page.locator('#researchBookSelect').selectOption(aid);await page.locator('#overviewSources').waitFor();await page.locator('#overviewSources').click();await page.locator('[data-research-source]').click();await page.locator('#removeResearchItems').click();await page.locator('#modal').waitFor({state:'hidden'});
      assert.equal(await page.locator('.source-card').count(),0);
      book=await (await context.request.get(base+'/api/book?book_id='+bid)).json();assert(book.research.source_ids.includes(sid));
      assert.equal((await context.request.get(base+'/api/source?id='+sid)).status(),200);
      // Sources imported from a project join that project automatically.
      await page.locator('#import').click();await page.locator('[data-import-tab="text"]').click();
      await page.locator('#sourceTextForm [name=title]').fill('Source ajoutée '+width);await page.locator('#sourceTextForm [name=author]').fill('Auteur');await page.locator('#sourceTextForm [name=text]').fill('Le texte propre à ce nouveau document.');
      await page.locator('#sourceTextForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});await page.getByRole('button',{name:'Source ajoutée '+width,exact:true}).waitFor();
      // Idea membership and contextual notes share the same folder mechanisms.
      const lib=await (await context.request.get(base+'/api/library?book_id='+aid)).json();const imported=lib.sources.find(s=>s.title==='Source ajoutée '+width);
      const idea=await (await context.request.post(base+'/api/idea',{data:{title:'Idée '+width,refs:[{source_id:imported.id,start:0,end:0}]}})).json();
      await page.reload();await page.locator('[data-open-book="'+aid+'"]').first().click();await page.locator('#overviewIdeas').click();await page.locator('#pickResearch').click();await page.locator('#researchPickerQuery').fill('Idée '+width);await page.locator('[data-research-pick]').check();await page.locator('#researchPickerSave').click();await page.locator('#modal').waitFor({state:'hidden'});await page.getByRole('heading',{name:'Idée '+width,exact:true}).waitFor();
      await page.getByRole('button',{name:'Classer / notes',exact:true}).click();await page.locator('[name=folder_ids]').first().check();await page.locator('#researchNote').fill('Mon angle pour cette idée');await page.locator('#researchClassifyForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      book=await (await context.request.get(base+'/api/book?book_id='+aid)).json();assert(book.research.idea_ids.includes(idea.id));assert.equal(book.research.idea_notes[idea.id],'Mon angle pour cette idée');
      await nav('book');await page.locator('#exportOptions').waitFor();assert(await page.locator('#bookCovers').isVisible());assert(await page.locator('#mediaLibrary').isVisible());assert.equal(await page.locator('.book-secondary-actions #exportOptions').count(),0);
      await nav('books');await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-books-${width}.png`),fullPage:true});
      assert.deepEqual(errors,[]);await context.close();
    }
    console.log('Book research workflow passed on desktop and mobile.');
  }finally{await browser?.close();fixture.kill()}
})().catch(error=>{console.error(error);process.exitCode=1});
