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
      const page=await browser.newPage({viewport:{width,height:844},reducedMotion:'reduce'}),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('https://www.youtube.com/**',route=>route.fulfill({contentType:'text/html',body:'<p>Lecteur de test</p>'}));
      await page.goto(base);
      await page.waitForFunction(()=>state.sources.length>0);
      await page.evaluate(async()=>{
        current={...await api('source?id='+state.sources[0].id),kind:'Vidéo',youtube_id:'test-video',chapters:[],segments:[
          {start:0,duration:10,text:'Premier passage.'},
          {start:42.8,duration:10,text:'Le passage recherché à retrouver dans la vidéo.'}
        ]};
        current.annotation={...current.annotation,rewritten_transcript:[{start:42.8,segment_start:1,segment_end:1,text:'Le passage éditorial.'}]};
        view='reader';readerTab='text';renderReader();
      });
      const assertSeek=async start=>{
        const src=new URL(await page.locator('#video').getAttribute('src'));
        assert.equal(src.searchParams.get('start'),start===0?null:String(Math.floor(start)));
        assert.equal(src.searchParams.get('autoplay'),'1');
        await page.waitForFunction(()=>{const r=document.querySelector('#video').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight});
      };
      // Grouped transcript paragraphs use their first source timestamp.
      await page.locator('.transcript-playback').first().click();await assertSeek(0);
      await page.locator('#transcriptSearch').fill('recherché');
      const original=await page.locator('#video').getAttribute('src');
      await page.locator('.capture').click();
      assert.equal(await page.locator('#video').getAttribute('src'),original,'capture must not start playback');
      assert.equal(await page.evaluate(()=>selectedSegments.size),2);
      await page.evaluate(()=>{
        const p=document.querySelector('.transcript-playback'),range=document.createRange();
        range.selectNodeContents(p);getSelection().removeAllRanges();getSelection().addRange(range);p.click();
      });
      assert.equal(await page.locator('#video').getAttribute('src'),original,'selecting text must not start playback');
      await page.evaluate(()=>getSelection().removeAllRanges());
      await page.locator('[data-reader="rewrite"]').click();
      await page.locator('#transcriptSearch').fill('');
      await page.locator('.transcript-playback').click();await assertSeek(42.8);
      for(const key of ['Enter','Space']){
        await page.evaluate(()=>document.querySelector('#video').src=youtubeEmbed(current));
        await page.locator('.transcript-playback').focus();await page.keyboard.press(key);await assertSeek(42.8);
      }
      await page.locator('.time').click();await assertSeek(42.8);
      await page.evaluate(()=>{current.youtube_id=null;current.url='';current.kind='Document';readerTab='text';renderReader()});
      assert.equal(await page.locator('.transcript-playback').count(),0,'documents remain plain text');
      assert.deepEqual(errors,[]);
      console.log(`${width}px: passage click, timestamp, autoplay request, video visibility, keyboard, capture, selection and documents OK`);
      await page.close();
    }
  }finally{if(browser)await browser.close();fixture.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
