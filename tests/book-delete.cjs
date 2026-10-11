// Deletion confirmation and preservation checks against a disposable database.
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
      await page.goto(base);await page.locator('#createResearchBook').waitFor();
      await page.locator('[data-open-book="book-main"]').first().click();
      assert(await page.locator('#deleteResearchBook').isEnabled());
      await page.locator('#researchAllBooks').click();
      await page.locator('#createResearchBook').click();
      await page.locator('#newBookForm [name=title]').fill('Livre à supprimer '+width);
      await page.locator('#newBookForm button[type=submit]').click();
      await page.locator('#deleteResearchBook').waitFor();
      const id=await page.locator('#researchBookSelect').inputValue();
      assert.equal(await page.locator('#overviewCommon').evaluate(e=>e.closest('.panel').querySelector('#deleteResearchBook')),null);
      assert(await page.locator('.book-delete-panel').evaluate(e=>e===e.parentElement.lastElementChild));
      assert(await page.locator('.book-presentation').evaluate(e=>e.getBoundingClientRect().top<document.querySelector('.stats').getBoundingClientRect().top));
      assert.equal(await page.locator('#deleteResearchBook').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(180, 35, 24)');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.locator('#deleteResearchBook').click();
      assert(await page.locator('#confirmBookDelete').isDisabled());
      for(const value of ['supp','Supprimer','supprimer ']){
        await page.locator('#deleteBookConfirmation').fill(value);
        assert(await page.locator('#confirmBookDelete').isDisabled());
      }
      await page.locator('#deleteBookConfirmation').fill('supprimer');
      assert(await page.locator('#confirmBookDelete').isEnabled());
      await page.locator('#modal [data-close]').click();
      assert.equal((await context.request.get(base+'/api/v1/books/'+id)).status(),200);
      const before=await (await context.request.get(base+'/api/library?compact=1')).json();
      // A failed request keeps the confirmation open and allows a retry.
      await page.route('**/api/v1/books/'+id,route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'Échec de vérification'})}));
      await page.locator('#deleteResearchBook').click();
      await page.locator('#deleteBookConfirmation').fill('supprimer');
      await page.locator('#confirmBookDelete').click();
      await page.locator('#deleteBookError').filter({hasText:'Échec de vérification'}).waitFor();
      assert(await page.locator('#confirmBookDelete').isEnabled());
      await page.unroute('**/api/v1/books/'+id);
      await page.locator('#confirmBookDelete').click();
      await page.locator('#createResearchBook').waitFor();
      assert.equal(await page.locator('[data-open-book="'+id+'"]').count(),0);
      const after=await (await context.request.get(base+'/api/library?compact=1')).json();
      assert.deepEqual(after.sources,before.sources);assert.deepEqual(after.ideas,before.ideas);
      const mainBefore=await (await context.request.get(base+'/api/v1/books/book-main')).json();
      assert.equal(mainBefore._book_id,'book-main');
      assert.equal(await page.evaluate(()=>localStorage.getItem('atelier-last-book')),'book-main');
      assert.equal(await page.evaluate(id=>AtelierDrafts.get(id),id),undefined);
      assert.deepEqual(errors,[]);await context.close();
    }
    const context=await browser.newContext(),page=await context.newPage();
    await page.goto(base);await page.locator('[data-open-book="book-main"]').first().click();
    const before=await (await context.request.get(base+'/api/library?compact=1')).json();
    await page.locator('#deleteResearchBook').click();await page.locator('#deleteBookConfirmation').fill('supprimer');
    await page.locator('#confirmBookDelete').click();await page.locator('#createResearchBook').waitFor();
    assert.equal(await page.locator('.project-book').count(),0);
    await page.reload();await page.locator('#createResearchBook').waitFor();
    await page.locator('[data-nav="common"]').click();await page.locator('#search').waitFor();
    const after=await (await context.request.get(base+'/api/library?compact=1')).json();
    assert.deepEqual(after.sources,before.sources);assert.deepEqual(after.ideas,before.ideas);
    await page.locator('[data-nav="books"]').click();await page.locator('#createResearchBook').click();
    await page.locator('#newBookForm [name=title]').fill('Nouveau départ');
    await page.locator('#newBookForm button[type=submit]').click();await page.locator('#deleteResearchBook').waitFor();
    await context.close();
    console.log('Book deletion passed on desktop and mobile, including main and last book deletion and recreation.');
  }finally{await browser?.close();fixture.kill()}
})().catch(error=>{console.error(error);process.exitCode=1});
