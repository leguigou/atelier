// Visual common library, details, bulk and multiple-book links, with isolated data.
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
      const post=async(route,data)=>{const r=await context.request.post(base+'/api/'+route,{data});assert.equal(r.status(),200);return r.json()};
      const a=await post('book-create',{title:'Livre visuel A '+width}),b=await post('book-create',{title:'Livre visuel B '+width});
      const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
      const upload=await context.request.post(base+`/api/upload?name=photo.png&title=Photo%20${width}`,{data:png,headers:{'Content-Type':'image/png'}});assert.equal(upload.status(),200);const uploaded=await upload.json(),photo=uploaded.source||uploaded;
      const library=await (await context.request.get(base+'/api/library?compact=1')).json();assert.equal(library.sources.find(s=>s.id===photo.id).preview_id,photo.preview_id);
      const idea=await post('idea',{title:'Une idée visuelle '+width,notes:'Le contexte complet de cette idée.',refs:[{source_id:photo.id,start:0,end:0,quote:'Le passage conservé.'}]});
      const other=await post('idea',{title:'Une seconde idée '+width,refs:[{source_id:photo.id,start:0,end:0}]});
      await page.goto(base);await page.locator('#createResearchBook').waitFor();
      await page.locator(width<760?'[data-mobile-nav=common]':'[data-nav=common]').click();
      await page.locator('#sort').selectOption('added');
      const card=page.locator('.source-card').filter({has:page.locator('[data-link-source="'+photo.id+'"]')});
      await card.locator('.cover img').waitFor();await page.waitForFunction(id=>{const im=document.querySelector(`[data-link-source="${id}"]`)?.closest('.source-card').querySelector('.cover img');return im?.complete&&im.naturalWidth>0},photo.id);
      await card.locator('[data-link-source]').click();
      for(const id of [a._book_id,b._book_id])await page.locator('[name=book_ids][value="'+id+'"]').check();
      await page.locator('#linkBooksForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      for(const title of [a.title,b.title])await card.locator('.linked-book-badges').getByText(title,{exact:true}).waitFor();
      for(const id of [a._book_id,b._book_id])assert((await (await context.request.get(base+'/api/book?book_id='+id)).json()).research.source_ids.includes(photo.id));
      // Reader exposes the same multi-book action.
      await card.getByRole('button',{name:'Ouvrir la source',exact:true}).click();await page.locator('#readerLinkBooks').click();await page.locator('#linkBooksForm').waitFor();
      assert(await page.locator('[name=book_ids][value="'+a._book_id+'"]').isChecked());await page.locator('#modal [data-close]').click();
      await page.locator('#back').click();await page.locator('[data-common-section=ideas]').click();
      const icard=page.locator('.idea-card').filter({has:page.locator('[data-link-idea="'+idea.id+'"]')});
      await icard.locator('.shared-idea-preview img').waitFor();await icard.getByRole('button',{name:'Ouvrir l’idée',exact:true}).click();
      await page.locator('#modal').getByText('Le contexte complet de cette idée.',{exact:true}).waitFor();await page.locator('#modal').getByText('Le passage conservé.',{exact:true}).waitFor();
      await page.locator('#modal [data-close]').click();
      // Bulk association preserves partial links unless the user changes that book.
      await icard.locator('[data-link-idea]').click();await page.locator('[name=book_ids][value="'+a._book_id+'"]').check();await page.locator('#linkBooksForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      for(const id of [idea.id,other.id])await page.locator('[data-select-shared-idea="'+id+'"]').check();
      await page.locator('#linkSharedSelection').click();await page.locator('#linkBooksForm').waitFor();assert(await page.locator('[name=book_ids][value="'+a._book_id+'"]').evaluate(e=>e.indeterminate));
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-book-links-${width}.png`)});
      await page.locator('[name=book_ids][value="'+b._book_id+'"]').check();await page.locator('#linkBooksForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      const ar=(await (await context.request.get(base+'/api/book?book_id='+a._book_id)).json()).research;
      assert(ar.idea_ids.includes(idea.id));assert(!ar.idea_ids.includes(other.id));
      const br=(await (await context.request.get(base+'/api/book?book_id='+b._book_id)).json()).research;assert(br.idea_ids.includes(idea.id)&&br.idea_ids.includes(other.id));
      await page.locator('#sharedBookFilter').selectOption(b._book_id);assert.equal(await page.locator('.idea-card').count(),2);
      await page.locator('#sharedBookFilter').selectOption('unlinked');assert.equal(await page.locator('[data-link-idea="'+idea.id+'"]').count(),0);
      await page.locator('#resetCollectionFilters').click();await icard.locator('[data-link-idea]').click();
      await page.locator('[name=book_ids][value="'+a._book_id+'"]').uncheck();await page.locator('#linkBooksForm button[type=submit]').click();await page.locator('#modal').waitFor({state:'hidden'});
      assert.equal((await context.request.get(base+'/api/idea?id='+idea.id)).status(),200);
      assert((await (await context.request.get(base+'/api/book?book_id='+b._book_id)).json()).research.idea_ids.includes(idea.id));
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-shared-ideas-${width}.png`),fullPage:true});
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-shared-ideas-screen-${width}.png`)});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);
      await page.locator('[data-common-section=library]').click();await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-shared-sources-${width}.png`),fullPage:true});
      await page.screenshot({path:path.join(process.env.TEMP||'/tmp',`atelier-shared-sources-screen-${width}.png`)});
      await context.close();
    }
    console.log('Visual shared library and multi-book links passed on desktop and mobile.');
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
