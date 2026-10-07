/* Reading anchors refer to manuscript blocks, so repagination never changes their identity. */
const ReaderAuthor=(()=>{
  let pending=null,selected=null,panelFocus=null,sourceRequest=0;
  const statuses={draft:'Brouillon',review:'À revoir',done:'Terminé'};
  const key=()=>`atelier-reading:${reading?.book_id}`;
  const location=el=>el?{chapter_id:el.dataset.readChapter,block_id:el.dataset.readBlock,offset:Number(el.dataset.readStart),start:Number(el.dataset.paragraphStart),end:Number(el.dataset.paragraphEnd)}:null;
  function anchor(){return pending||location($('#pageContent [data-read-block]'))||{chapter_id:tocEntries.findLast(t=>t.page<=readingIndex)?.chapter_id,page:readingIndex}}
  function begin(data){pending=null;selected=null;if(data.book_id){try{pending=JSON.parse(localStorage.getItem(`atelier-reading:${data.book_id}`))}catch{}}}
  function restore(target){
    pending=null;if(!target)return;
    let chapterPage=-1,blockPage=-1;
    const template=document.createElement('template');
    for(let i=0;i<pageList.length;i++){
      template.innerHTML=pageList[i];
      for(const el of template.content.querySelectorAll('[data-read-block]')){
        if(el.dataset.readChapter!==target.chapter_id)continue;
        if(chapterPage<0)chapterPage=i;
        if(el.dataset.readBlock!==target.block_id)continue;
        blockPage=i;
        if(Number(el.dataset.readEnd)>target.offset){readingIndex=i;return}
      }
    }
    const chapter=tocEntries.find(t=>t.chapter_id===target.chapter_id);
    readingIndex=blockPage>=0?blockPage:chapter?.page??(chapterPage>=0?chapterPage:Math.max(0,Math.min(Number(target.page)||0,pageList.length-1)));
  }
  function pageShown(){
    if(!reading?.book_id)return;
    selected=null;
    try{localStorage.setItem(key(),JSON.stringify(anchor()))}catch{}
    $('#readerPassageHint').textContent='Touchez un passage ou sélectionnez du texte pour le modifier.';
    for(const id of ['readerEdit','readerNote','readerSources'])$('#'+id).disabled=true;
  }
  function choose(el){
    if(!el)return;selected=location(el);selected.excerpt=window.getSelection()?.toString().trim().slice(0,1000)||el.textContent.slice(0,1000);
    $$('#pageContent .reading-selected').forEach(x=>x.classList.remove('reading-selected'));el.classList.add('reading-selected');
    $('#readerPassageHint').textContent='Passage sélectionné';
    for(const id of ['readerEdit','readerNote','readerSources'])$('#'+id).disabled=false;
  }
  function install(signal){
    if(!reading?.book_id)return;
    $('#readingOverlay').classList.add('author-reader');
    $('.reading-header small').textContent='Lecture du livre · modifications et notes disponibles';
    $('.reading-controls').insertAdjacentHTML('beforebegin',`<div class="reader-author-tools"><span id="readerPassageHint" role="status"></span><button id="readerSelect" aria-pressed="false">Sélectionner du texte</button><button id="readerEdit" disabled>Modifier</button><button id="readerNote" disabled>À revoir / Note</button><button id="readerSources" disabled>Sources</button><button id="readerReviews">Relire</button></div>`);
    $('#readerEdit').onclick=edit;$('#readerNote').onclick=note;$('#readerSources').onclick=sources;$('#readerReviews').onclick=reviews;
    $('#readerSelect').onclick=e=>{const on=$('#readingOverlay').classList.toggle('reader-selecting');e.currentTarget.setAttribute('aria-pressed',String(on));e.currentTarget.textContent=on?'Reprendre les gestes':'Sélectionner du texte'};
    $('#pageContent').addEventListener('click',e=>choose(e.target.closest('[data-read-block]')),{signal});
    $('#pageContent').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-read-block]')){e.preventDefault();choose(e.target);$('#readerEdit').focus()}},{signal});
    document.addEventListener('selectionchange',()=>{const selection=window.getSelection();if(!selection?.isCollapsed){const node=selection.anchorNode?.parentElement,el=node?.closest('#pageContent [data-read-block]');if(el)choose(el)}},{signal});
  }
  function panel(title,html){
    sourceRequest++;panelFocus=document.activeElement;
    $('#readerPanel')?.remove();setReaderContents(false);
    $('#readingOverlay').classList.add('reader-panel-open');
    $('.page-stage').inert=true;$('.reading-controls').inert=true;$('.reader-author-tools').inert=true;$('.reading-header').inert=true;
    $('#readingOverlay').insertAdjacentHTML('beforeend',`<aside id="readerPanel" class="reader-author-panel" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2><button id="closeReaderPanel" aria-label="Revenir à la lecture">×</button></header>${html}<p id="readerPanelStatus" role="status" class="small"></p></aside>`);
    $('#closeReaderPanel').onclick=closePanel;$('#readerPanel textarea, #readerPanel button')?.focus();
  }
  function closePanel(repaginate=true){
    const edited=Boolean($('#readerEditText'));
    sourceRequest++;$('#readerPanel')?.remove();$('#readingOverlay')?.classList.remove('reader-panel-open');
    for(const selector of ['.page-stage','.reading-controls','.reader-author-tools','.reading-header']){const el=$(selector);if(el)el.inert=false}
    if(panelFocus?.isConnected&&!panelFocus.disabled)panelFocus.focus();else $('#readerReviews')?.focus();
    if(edited&&reading&&repaginate){updateReading();paginate()}
  }
  function escape(){if($('#readerPanel')){closePanel();return true}return false}
  function find(target=selected){const ch=bookDraft?.chapters.find(c=>c.id===target?.chapter_id);return {ch,block:ch?.blocks.find(b=>b.id===target?.block_id)}}
  async function save(){
    try{await cacheLocalDraft();await persistDraft();if($('#readerPanelStatus'))$('#readerPanelStatus').textContent='Enregistré dans le livre et son historique.';return true}
    catch(e){if($('#readerPanelStatus'))$('#readerPanelStatus').textContent='Brouillon conservé. '+e.message;return false}
  }
  function updateReading(){
    if(!reading?.book_id)return;
    for(const section of reading.sections){const ch=bookDraft.chapters.find(c=>c.id===section.chapter_id);if(!ch)continue;section.title=ch.title;section.status=ch.status;for(const b of section.blocks){const original=ch.blocks.find(x=>x.id===b.id);if(original){Object.assign(b,original);b.original_text=original.text||''}}}
  }
  function edit(){
    const target={...selected}, {ch,block}=find(target);if(!block)return;
    const original=block.text||'',start=target.start,end=target.end;let liveEnd=end;
    panel('Modifier le passage',`<p class="small">${esc(ch.title)} · le reste du chapitre reste visible dans le livre.</p>${start?`<blockquote class="reader-context">${esc(original.slice(Math.max(0,start-250),start))}</blockquote>`:''}<label>Texte du passage<textarea id="readerEditText" rows="10">${esc(original.slice(start,end))}</textarea></label>${end<original.length?`<blockquote class="reader-context">${esc(original.slice(end,end+250))}</blockquote>`:''}<p class="small">Vos modifications sont enregistrées automatiquement et protégées par une copie locale.</p><button id="readerSaveResume" class="primary">Enregistrer et reprendre la lecture</button>`);
    $('#readerEditText').oninput=e=>{
      const value=e.target.value,delta=value.length-(liveEnd-start);
      block.text=block.text.slice(0,start)+value+block.text.slice(liveEnd);liveEnd=start+value.length;
      for(const n of bookDraft.review_notes||[]){if(n.chapter_id===ch.id&&n.block_id===block.id&&n.offset>start)n.offset=n.offset>=liveEnd-delta?n.offset+delta:start}
      pending={...target,offset:start};changed('Passage modifié · '+ch.title);updateReading();
      $('#readerPanelStatus').textContent='Modifications en attente d’enregistrement…';
    };
    $('#readerSaveResume').onclick=()=>run(async()=>{if(await save()){pending={...target,offset:start};updateReading();closePanel(false);await paginate()}},$('#readerSaveResume'));
    $('#readerEditText').focus();
  }
  function note(){
    const target={...selected};if(!find(target).block)return;
    let draft=null;
    const keep=()=>{if(!draft){draft={id:newId(),chapter_id:target.chapter_id,block_id:target.block_id,offset:target.offset,excerpt:target.excerpt,text:'',done:false};(bookDraft.review_notes??=[]).push(draft)}draft.text=$('#readerNoteText').value;const {ch}=find(target);ch.status='review';changed('Note de relecture · '+ch.title)};
    panel('À revoir / Note',`<blockquote>${esc(target.excerpt)}</blockquote><label>Note de relecture<textarea id="readerNoteText" rows="5" placeholder="Ce passage est à revoir…"></textarea></label><p class="small">La note est sauvegardée automatiquement dès que vous écrivez.</p><button id="readerAddNote" class="primary">Ajouter à la relecture</button>`);
    $('#readerNoteText').oninput=keep;
    $('#readerAddNote').onclick=()=>run(async()=>{
      keep();if(await save()){if($('#readerPanel'))closePanel();decorateContents()}
    },$('#readerAddNote'));
  }
  function jump(target){pending=target;restore(target);closePanel();showPage()}
  function reviews(){
    panel('Relire le livre',`<p>Retrouvez les passages à retravailler. Les notes terminées restent conservées.</p><div class="reader-review-list">${(bookDraft.review_notes||[]).map(n=>{const {ch,block}=find(n);return `<article><strong>${esc(ch?.title||'Chapitre retiré')}</strong><p>${esc(n.excerpt)}</p><p>${esc(n.text||'À revoir')}</p><button data-review-jump="${esc(n.id)}" ${block?'':'disabled'}>Lire le passage</button><button data-review-done="${esc(n.id)}" aria-pressed="${n.done}">${n.done?'✓ Terminé · rouvrir':'Marquer comme terminé'}</button>${block?'':'<small>Le passage a été retiré ; la note est conservée.</small>'}</article>`}).join('')||'<p>Aucune note de relecture. Sélectionnez un passage puis « À revoir / Note ».</p>'}</div>`);
    $$('[data-review-jump]').forEach(b=>b.onclick=()=>jump(bookDraft.review_notes.find(n=>n.id===b.dataset.reviewJump)));
    $$('[data-review-done]').forEach(b=>b.onclick=()=>run(async()=>{const n=bookDraft.review_notes.find(n=>n.id===b.dataset.reviewDone);n.done=!n.done;changed('Note de relecture mise à jour');await save();if($('#readerPanel'))reviews()},b));
  }
  function sources(){
    const {ch,block}=find();if(!block)return;
    const ids=[...new Set([...(block.source_ids||[]),...(!block.source_ids?.length?(ch.ideas||[]).flatMap(id=>(state.ideas.find(i=>i.id===id)?.refs||[]).map(r=>r.source_id)):[])])].filter(Boolean);
    panel('Sources du passage',`<p class="small">${esc(ch.title)}</p><div id="readerSourceList">${ids.map(id=>`<button data-reading-source="${esc(id)}">${esc(state.sources.find(s=>s.id===id)?.title||id)}</button>`).join('')||'<p>Aucune source associée à ce passage.</p>'}</div><div id="readerSourceContent"></div>`);
    $$('[data-reading-source]').forEach(b=>b.onclick=()=>run(async()=>{
      const request=++sourceRequest,s=await api('source?id='+encodeURIComponent(b.dataset.readingSource));if(request!==sourceRequest||!$('#readerSourceContent'))return;
      const container=$('#readerSourceContent');container.innerHTML=`<h3>${esc(s.title)}</h3><p class="small">${esc(s.author||'')}</p><div id="readerSourceSegments"></div><button id="readerSourceMore">Afficher la suite</button>`;
      let count=0;const more=()=>{const batch=(s.segments||[]).slice(count,count+50);$('#readerSourceSegments').insertAdjacentHTML('beforeend',batch.map(seg=>`<p>${seg.page?`<small>Page ${Number(seg.page)}</small><br>`:''}${esc(seg.text)}</p>`).join(''));count+=batch.length;$('#readerSourceMore').hidden=count>=(s.segments||[]).length};$('#readerSourceMore').onclick=more;more();
    },b));
  }
  function decorateContents(){
    if(!reading?.book_id)return;
    $$('.reader-toc [data-edit-chapter]').forEach(el=>el.remove());
    $$('[data-toc-page]').forEach(btn=>{const t=tocEntries.find(t=>t.page===Number(btn.dataset.tocPage)),ch=bookDraft.chapters.find(c=>c.id===t?.chapter_id);if(!ch)return;
      const status=document.createElement('button');status.dataset.editChapter=ch.id;status.className='reader-chapter-edit';status.textContent=`${statuses[ch.status||'draft']} · Éditer le chapitre`;btn.after(status);
      status.onclick=()=>{chapterId=ch.id;closePages();$('#chapterTitle')?.focus()};
    });
  }
  function end(){sourceRequest++;closePanel(false);selected=null;pending=null}
  return {anchor,begin,restore,pageShown,install,escape,end,decorateContents,reviews,updateReading};
})();

const renderAuthorBook=renderBook;
renderBook=function(){
  renderAuthorBook();
  const commands=$('.book-command');if(!commands)return;
  commands.insertAdjacentHTML('afterend','<nav class="book-modes" aria-label="Modes du livre"><button aria-current="page" id="modeWrite">Écrire</button><button id="modeRead">Lire</button><button id="modeReview">Relire</button></nav>');
  $('#modeWrite').onclick=()=>$('#chapterTitle')?.focus();$('#modeRead').onclick=()=>$('#readBook').click();
  $('#modeReview').onclick=()=>run(async()=>{await $('#readBook').onclick();if(reading?.book_id)ReaderAuthor.reviews()});
  const details=document.createElement('details');details.className='book-secondary-actions';details.innerHTML='<summary>Outils du livre</summary><div></div>';commands.append(details);
  for(const id of ['bookCovers','mediaLibrary','exportOptions','bookLayout','bookHistory'])details.lastElementChild.append($('#'+id));
  const ch=currentChapter();if(ch){$('.chapter-toolbar').insertAdjacentHTML('afterend',`<label class="chapter-status">État du chapitre <select id="chapterReviewStatus"><option value="draft">Brouillon</option><option value="review">À revoir</option><option value="done">Terminé</option></select></label>`);$('#chapterReviewStatus').value=ch.status||'draft';$('#chapterReviewStatus').onchange=e=>{ch.status=e.target.value;changed('Statut du chapitre · '+ch.title)}}
  function outlineStatuses(){for(const btn of $$('[data-chapter-id]')){let label=btn.querySelector('.author-chapter-status');if(!label){label=document.createElement('small');label.className='author-chapter-status';btn.append(label)}const chapter=bookDraft.chapters.find(c=>c.id===btn.dataset.chapterId);label.textContent=({draft:'Brouillon',review:'À revoir',done:'Terminé'})[chapter?.status||'draft']}}
  outlineStatuses();$('#chapterReviewStatus')?.addEventListener('change',outlineStatuses);
};
const closeAuthorPages=closePages;
closePages=function(){closeAuthorPages();if(view==='book'&&bookDraft)renderBook()};
