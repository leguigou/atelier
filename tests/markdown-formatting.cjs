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
      page.on('pageerror',e=>errors.push(e.message));await page.goto(base);
      await page.locator(width<760?'[data-mobile-nav="book"]':'[data-nav="book"]').click();
      const editor=page.locator('[data-block-text]').first(),toolbar=page.locator('.markdown-toolbar').first();
      await editor.fill('Sélection à formater');await editor.evaluate(el=>{el.focus();el.setSelectionRange(0,9)});
      await toolbar.locator('[data-format="bold"]').click();assert.equal(await editor.inputValue(),'**Sélection** à formater');
      await toolbar.locator('[data-markdown-guide]').click();
      await page.locator('#markdownExample').selectOption({label:'Tableaux · Tableau aligné'});
      assert.equal(await page.locator('#markdownResult table').count(),1);await page.locator('#insertMarkdownExample').click();assert.match(await editor.inputValue(),/\| Élément/);
      await editor.fill('## Un titre\n\n**Gras**, *italique*, ~~barré~~, ++souligné++, ==surligné==, m^2^ et H~2~O.\n\nLigne A\\\nLigne B\n\n> Citation en retrait\n\n- Premier élément\n- Second élément\n  - Sous-élément\n\n| Nom | Valeur |\n| :--- | ---: |\n| Mesure | 42 |\n\n```text\nCode préservé\n```\n\n[Un lien](https://example.org)');
      await toolbar.locator('[data-markdown-preview]').click();
      const preview=page.locator('.markdown-preview').first();
      for(const tag of ['strong','em','s','u','mark','sup','sub','blockquote','table','pre','br','a'])assert(await preview.locator(tag).count(),tag);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'editor fits viewport');
      await editor.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(__dirname,'../qa',`markdown-editor-${width}.png`),fullPage:false});
      await page.locator('.book-secondary-actions summary').click();await page.locator('#bookLayout').click();
      await page.locator('[name="alignment"]').selectOption('left');await page.locator('[name="paragraph_indent"]').selectOption('5');await page.locator('[name="paragraph_spacing"]').selectOption('12');
      await page.screenshot({path:path.join(__dirname,'../qa',`markdown-layout-${width}.png`)});
      await page.locator('#layoutForm button[type="submit"]').click();await page.locator('#modeRead').click();
      await page.waitForFunction(()=>pageList.some(html=>html.includes('<table')));
      const html=await page.evaluate(()=>pageList.join(''));
      for(const tag of ['strong','em','s','u','mark','sup','sub','blockquote','table','pre','br','a'])assert(html.includes('<'+tag),tag+' in reading');
      assert.equal(await page.locator('#pageContent').evaluate(el=>el.style.getPropertyValue('--paragraph-indent')),'5mm');
      await page.screenshot({path:path.join(__dirname,'../qa',`markdown-reader-${width}.png`)});
      // Rich paragraphs span pages without losing marks or source references.
      await page.locator('#closeReading').click();await page.locator('[data-block-text]').first().fill(('**Texte gras** et *italique* conservé. ').repeat(300));await page.locator('#modeRead').click();
      await page.waitForFunction(()=>pageList.length>3);
      assert(await page.evaluate(()=>pageList.filter(html=>html.includes('data-read-block="block-test"')).every(html=>html.includes('<strong>')&&html.includes('<em>'))));
      assert.deepEqual(errors,[]);await context.close();console.log(width+'px: formatting, guide, preview, layout, reading and rich pagination OK');
    }
  }finally{await browser?.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
