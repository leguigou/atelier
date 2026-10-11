/* Books are the entry point; shared research is linked into independent workspaces. */
let commonResearch=false, researchFolder='', researchIdeaSort='recent', folderReaderOrigin='';
view='books';
const researchOf=()=>state.book.research||{source_ids:state.book.source_ids||[],idea_ids:[],folders:[],source_notes:{},idea_notes:{}};
const projectContext=()=>!commonResearch&&!['books','settings'].includes(view);
const researchOriginal={shell,render,navigate,filtered,renderLibrary,renderIdeas,renderFolders,renderReader,ideaModal,ideaCard,card,api,uploadFile,addArchiveTab};
let commonAssignmentFilter='', sharedIdeaSelection=new Set(), libraryIdeaStatus='';

async function changeResearch(data){
  await persistDraft();
  const b=await researchOriginal.api('book-research',{book_id:activeBookId,revision:state.book._revision,...data});
  state.book=b;if(bookDraft&&!bookDirty)bookDraft=structuredClone(b);
  state.books=await api('books');return b;
}
async function openResearchBook(id,destination='overview'){
  await persistDraft();if(bookDirty)return;
  rememberBook(id);bookDraft=null;chapterId=null;commonResearch=false;researchFolder='';resetResearchFilters();
  await reload();view=destination;render();
}
function resetResearchFilters(){query='';author='';status='';kind='';folder='';scope='all';tagsSel=[];page=1;selected.clear();sharedIdeaSelection.clear();commonAssignmentFilter='';libraryIdeaStatus='';sourceSearchIds=null;sourceSearchPassages=null;clearTimeout(sourceSearchTimer);ideaQuery='';ideaMode='all';ideaFolder='';ideaTags=[];ideaVisibleLimit=60}
navigate=function(v){
  if(v==='library'&&!projectContext())v='common';
  if(v==='ideas'&&['books','settings'].includes(view)){commonResearch=true;resetResearchFilters()}
  folderReaderOrigin='';
  if(view==='folders'&&v!=='folders')researchFolder='';
  if(!state.books?.length&&(['overview','book','folders'].includes(v)||(!['books','settings','common'].includes(v)&&!commonResearch)))v='books';
  if(v==='common'){commonResearch=true;researchFolder='';resetResearchFilters();v='library'}
  else if(['books','overview','folders','book'].includes(v)&&commonResearch){commonResearch=false;researchFolder='';resetResearchFilters()}
  if(['books','overview','folders'].includes(v))researchFolder='';
  researchOriginal.navigate(v);
};
render=function(){
  if(view==='books')return renderBooks();
  if(view==='overview')return renderResearchOverview();
  researchOriginal.render();
};
shell=function(content){
  researchOriginal.shell(content);
  $('.main').classList.toggle('shared-library',commonResearch&&['library','ideas'].includes(view));
  $('.project-switcher')?.remove();
  const nav=[['books','▤','Mes livres'],['overview','▤','Vue d’ensemble'],['folders','▱','Dossiers'],['library','sources','Sources'],['ideas','✧','Idées'],['book','▤','Manuscrit'],['common','▦','Bibliothèque commune'],['settings','⚙','Réglages']];
  const navButton=([v,i,l])=>{const active=v==='common'?commonResearch&&['library','ideas','reader'].includes(view):(!commonResearch||['books','settings'].includes(v))&&(v===view||(v==='library'&&view==='reader'));return `<button data-nav="${v}" class="${active?'active':''}" ${active?'aria-current="page"':''}><span class="icon">${uiIcon(i)}</span>${l}</button>`};
  $('.nav').innerHTML=`<div class="nav-group" aria-label="Espace personnel"><span class="nav-group-label">Votre espace</span>${nav.filter(n=>['books','common'].includes(n[0])).map(navButton).join('')}</div><div class="nav-group" aria-label="Navigation du livre"><span class="nav-group-label">${projectContext()?'Livre ouvert':'Accès rapides'}</span>${projectContext()?`<strong class="nav-book-title">${esc(state.book.title)}</strong>`:''}${nav.filter(n=>['overview','library','ideas','folders','book'].includes(n[0])).sort((a,b)=>['overview','library','ideas','folders','book'].indexOf(a[0])-['overview','library','ideas','folders','book'].indexOf(b[0])).map(navButton).join('')}</div><div class="nav-group nav-settings">${nav.filter(n=>n[0]==='settings').map(navButton).join('')}</div>`;
  $$('[data-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.nav));
  $('.mobile-nav').innerHTML=[['books','▤','Livres'],['common','▦','Bibliothèque'],['library','sources','Sources'],['folders','▱','Dossiers'],['book','▤','Écrire']].map(([v,i,l])=>`<button data-mobile-nav="${v}" class="${(v==='common'?commonResearch&&['library','ideas','reader'].includes(view):view===v&&!commonResearch)?'active':''}">${uiIcon(i)}<small>${l}</small></button>`).join('');
  $$('[data-mobile-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.mobileNav));
  const crumb=$('.crumb');if(crumb)crumb.textContent=view==='books'?'Votre espace / Mes livres':view==='settings'?'Votre espace / Réglages':commonResearch?'Bibliothèque commune / '+(view==='ideas'?'Idées':view==='reader'?'Lecture':'Sources'):state.book.title+' / '+(nav.find(n=>n[0]===view)?.[2]||'Lecture');
  $('.main').classList.toggle('book-workspace',projectContext());
  $('.top-actions .small')?.remove();
  if($('#agentLauncher'))$('.top-actions').append($('#agentLauncher'));
  if(commonResearch&&view!=='settings'&&view!=='books')$('.topbar').insertAdjacentHTML('afterend','<div class="workspace-scope">Bibliothèque commune <span>Sources et idées réutilisables dans tous vos livres</span></div>');
  if(view!=='books'&&view!=='settings'&&!commonResearch){
    $('.main').insertAdjacentHTML('afterbegin',`<div class="research-context"><label>Livre ouvert <select id="researchBookSelect">${(state.books||[]).map(b=>`<option value="${esc(b.id)}" ${b.id===activeBookId?'selected':''}>${esc(b.title)}</option>`).join('')}</select></label><button id="researchAllBooks">Mes livres</button>${commonResearch?'<span class="small">Documents partagés entre tous les livres</span>':`<span class="workspace-scope-label">Vous travaillez dans ce livre</span>`}</div>`);
    $('#researchBookSelect').onchange=e=>run(()=>openResearchBook(e.target.value));$('#researchAllBooks').onclick=()=>navigate('books');
    $('.research-context').insertAdjacentHTML('afterend',`<nav class="project-section-nav" aria-label="Sections du livre">${nav.filter(n=>['overview','library','ideas','folders','book'].includes(n[0])).sort((a,b)=>['overview','library','ideas','folders','book'].indexOf(a[0])-['overview','library','ideas','folders','book'].indexOf(b[0])).map(([v,i,l])=>`<button data-project-section="${v}" ${view===v||(v==='library'&&view==='reader')?'aria-current="page"':''}>${l}</button>`).join('')}</nav>`);
    $$('[data-project-section]').forEach(button=>button.onclick=()=>navigate(button.dataset.projectSection));
    if(!['overview','book'].includes(view))installWorkspaceGuide();
  }
};
function renderBooks(){
  shell(header('Votre bibliothèque personnelle','Mes livres','Choisissez un livre pour retrouver sa matière et son manuscrit.','<button id="browseCommonResources">Toutes les ressources</button><button id="createResearchBook" class="primary">Créer un livre</button>')+`<div class="books-grid">${(state.books||[]).map(b=>`<article class="project-book"><button data-open-book="${esc(b.id)}" class="project-book-cover" aria-label="Ouvrir ${esc(b.title)}">${b.cover?`<img src="${assetUrl(b.cover)}" alt="">`:`<span>${uiIcon('▤')}</span>`}</button><div class="project-book-content"><div class="project-book-header"><h2>${esc(b.title)}</h2><details class="project-book-menu"><summary aria-label="Actions pour ${esc(b.title)}" title="Actions du livre"><span aria-hidden="true">⋮</span></summary><div class="project-book-menu-panel"><button data-book-action="details" data-book-id="${esc(b.id)}">Modifier les informations</button><button data-book-action="download" data-book-id="${esc(b.id)}">Télécharger le livre</button><button data-duplicate-book="${esc(b.id)}">Dupliquer le livre</button><button data-book-action="delete" data-book-id="${esc(b.id)}" class="project-book-menu-delete">Supprimer le livre</button></div></details></div><p>${esc(b.description||b.author||'Un projet à faire grandir')}</p><span class="small">${({preparation:'En préparation',writing:'En écriture',done:'Terminé'})[b.project_status]||'En préparation'} · ${b.chapters} chapitres · ${b.sources||0} sources · ${b.ideas||0} idées retenues</span></div><div class="project-book-actions"><button data-read-book="${esc(b.id)}" class="primary">Lire le livre</button><button data-open-book="${esc(b.id)}">Ouvrir le livre</button></div></article>`).join('')}</div>`);
  $('#browseCommonResources').onclick=()=>navigate('common');
  const menus=$$('.project-book-menu');
  menus.forEach(menu=>menu.ontoggle=()=>{if(menu.open)menus.forEach(other=>{if(other!==menu)other.open=false})});
  $('.main').addEventListener('click',event=>menus.forEach(menu=>{if(!menu.contains(event.target))menu.open=false}));
  $('.main').addEventListener('keydown',event=>{if(event.key==='Escape')menus.forEach(menu=>{if(menu.open){menu.open=false;menu.querySelector('summary').focus();event.preventDefault()}})});
  $$('[data-book-action]').forEach(button=>button.onclick=()=>run(async()=>{
    const action=button.dataset.bookAction;
    await openResearchBook(button.dataset.bookId,'books');if(bookDirty)return;
    if(action==='delete')deleteResearchBookModal(state.book);
    else if(action==='details')researchDetailsModal(state.book);
    else if(action==='download'){ensureDraft();exportModal()}
  },button));
  $$('[data-read-book]').forEach(button=>button.onclick=()=>run(async()=>{
    await openResearchBook(button.dataset.readBook,'books');if(bookDirty)return;
    await readCurrentBook();
  },button));
  $$('[data-duplicate-book]').forEach(button=>button.onclick=()=>run(async()=>{
    await persistDraft();if(bookDirty)return;
    const copy=await api('book-duplicate',{book_id:button.dataset.duplicateBook});
    state.books=await api('books');renderBooks();
    toast('Le livre a été dupliqué.');
    const card=$$('[data-duplicate-book]').find(b=>b.dataset.duplicateBook===copy._book_id);
    card?.closest('.project-book')?.scrollIntoView({block:'nearest'});card?.closest('details')?.querySelector('summary').focus();
  },button));
  $('#createResearchBook').onclick=newBookModal;$$('[data-open-book]').forEach(b=>b.onclick=()=>run(()=>openResearchBook(b.dataset.openBook),b));
}
newBookModal=function(){
  showModal(`<h2>Créer un livre</h2><p>Commencez par votre projet. Vous pourrez ajouter sa matière et son plan ensuite.</p><form id="newBookForm"><label>Titre<input name="title" required maxlength="300"></label><label>Quelques mots sur ce projet<textarea name="description" maxlength="6000" rows="3"></textarea></label><label>Auteur<input name="author" maxlength="300"></label>${formActions('Créer le livre')}</form>`);
  $('#newBookForm').onsubmit=e=>{e.preventDefault();run(async()=>{await persistDraft();const b=await api('book-create',Object.fromEntries(new FormData(e.target)));await openResearchBook(b._book_id);$('#modal').close()},e.submitter)};
};
function bookNextStep(b=state.book){
  const r=b.research||{source_ids:b.source_ids||[]},chapters=b.chapters||[],proposal=b.editorial_proposal;
  if(proposal&&!proposal.applied_at)return {key:'proposal',title:'Une proposition attend votre relecture',description:'Retrouvez le plan ou les paragraphes proposés et choisissez ce que vous voulez garder.',label:'Relire la proposition'};
  if(b.project_status==='done')return {key:'read',title:'Relire votre livre',description:'Parcourez le manuscrit avant de télécharger la version à partager.',label:'Lire le livre'};
  if(!b.brief?.intention)return {key:'intention',title:'Donner une direction à votre livre',description:'Précisez le sujet, le lecteur et ce que vous souhaitez lui transmettre.',label:'Définir mon intention'};
  if(!r.source_ids.length)return {key:'sources',title:'Rassembler vos premières sources',description:'Choisissez dans la bibliothèque commune les documents qui nourriront ce livre, ou ajoutez une source.',label:'Choisir mes sources'};
  if(!chapters.length)return {key:'plan',title:'Construire le plan du livre',description:'Créez votre premier chapitre ou préparez un plan accompagné à partir de vos sources.',label:'Construire mon plan'};
  const chapter=chapters.find(c=>c.id===chapterId)||chapters.find(c=>c.status!=='done')||chapters[0];
  return {key:'write',chapter:chapter.id,title:'Reprendre votre manuscrit',description:'Poursuivez « '+chapter.title+' ». Vos sources et vos idées restent accessibles pendant l’écriture.',label:'Continuer à écrire'};
}
async function advanceBook(step){
  if(step.key==='sources'){navigate('library');$('#pickResearch')?.click();return}
  if(step.chapter)chapterId=step.chapter;
  navigate('book');
  if(view!=='book')return;
  if(step.key==='intention')briefModal();
  else if(step.key==='proposal')proposalModal(bookDraft.editorial_proposal);
  else if(step.key==='read')await $('#readBook').onclick();
  else if(step.key==='plan')$('#addBookChapter')?.click();
  else {const editor=$('[data-block-text]')||$('#chapterTitle');editor?.focus();editor?.scrollIntoView({block:'center'})}
}
function installWorkspaceGuide(){
  if(view==='folders'&&researchOf().folders.some(f=>f.id===researchFolder))return;
  const guides={library:['Rassembler la matière','Ajoutez des sources à ce livre, puis ouvrez un document pour en retenir les passages utiles.','Voir les idées du livre','ideas'],ideas:['Choisir ce qui nourrira le texte','Retenez et classez les idées utiles. Vous pourrez les rattacher à vos chapitres dans le manuscrit.','Ouvrir le manuscrit','book'],folders:['Organiser la matière du livre','Regroupez les sources et les idées par thème pour préparer vos chapitres.','Retrouver les sources','library'],reader:['Lire et retenir un passage','Sélectionnez un passage pour en garder une idée, avec sa référence source.','Voir les idées du livre','ideas']};
  const g=guides[view];if(!g)return;
  const anchor=$('.heading')||$('.reader-head');if(!anchor)return;
  anchor.insertAdjacentHTML('afterend',`<section class="workspace-guide" aria-label="Faire avancer ce livre"><div><strong>${g[0]}</strong><p>${g[1]}</p></div><button id="workspaceNext">${g[2]}</button></section>`);
  $('#workspaceNext').onclick=()=>navigate(g[3]);
}
function nextStepCard(step){return `<section class="book-next-step" aria-label="Prochaine étape du livre"><div><div class="eyebrow">Votre prochaine étape</div><h2>${esc(step.title)}</h2><p>${esc(step.description)}</p></div><button id="overviewNext" class="primary" data-next-step="${step.key}">${esc(step.label)}</button></section>`}
function renderResearchOverview(){
  const r=researchOf(),b=state.book,step=bookNextStep(b);
  shell(header('Votre projet',esc(b.title),esc(b.description)||'Organisez la matière de ce livre, puis avancez dans le manuscrit.','<button id="researchDetails">Décrire le projet</button>')+nextStepCard(step)+bookPresentationCard(b)+`<div class="stats"><div class="stat"><strong>${r.source_ids.length}</strong><span>sources du livre</span></div><div class="stat"><strong>${bookIdeaPool().length}</strong><span>idées disponibles</span></div><div class="stat"><strong>${r.folders.length}</strong><span>dossiers</span></div><div class="stat"><strong>${b.chapters.length}</strong><span>chapitres</span></div></div><div class="research-start"><section class="panel"><h2>Rassembler la matière</h2><p>Ajoutez vos documents, retrouvez des idées et classez-les dans un ou plusieurs dossiers.</p><div class="row"><button id="overviewSources">Sources</button><button id="overviewIdeas">Idées</button><button id="overviewFolders">Dossiers</button></div></section><section class="panel"><h2>Faire avancer le livre</h2><p>${esc(b.brief?.intention||'Définissez votre intention, construisez un plan et commencez à écrire.')}</p><button id="overviewWrite">Ouvrir le manuscrit</button></section></div><section class="panel"><h2>Bibliothèque commune</h2><p>Réutilisez une source ou une idée dans plusieurs livres. Chaque projet conserve son propre classement et ses notes de travail.</p><button id="overviewCommon">Explorer les sources communes</button></section>`);
  $('#overviewNext').onclick=e=>run(()=>advanceBook(step),e.currentTarget);
  const commonPanel=$('#overviewCommon').closest('.panel');
  commonPanel.insertAdjacentHTML('afterend',`<section class="panel book-delete-panel"><h2>Supprimer ce livre</h2><p>Le livre et son historique seront supprimés. Les sources et les idées restent dans la bibliothèque commune.</p><button id="deleteResearchBook" class="book-delete-button">Supprimer</button></section>`);
  $('#deleteResearchBook').onclick=()=>deleteResearchBookModal(b);
  bindBookPresentation();
  for(const [id,v] of [['overviewSources','library'],['overviewIdeas','ideas'],['overviewFolders','folders'],['overviewWrite','book'],['overviewCommon','common']])$('#'+id).onclick=()=>navigate(v);
  $('#researchDetails').onclick=()=>researchDetailsModal(b);
}
function researchDetailsModal(b){showModal(`<h2>Décrire le projet</h2><form id="researchDetailsForm"><label>Titre<input name="title" required maxlength="300" value="${esc(b.title)}"></label><label>Description<textarea name="description" maxlength="6000">${esc(b.description||'')}</textarea></label><label>État du livre<select name="project_status">${[['preparation','En préparation'],['writing','En écriture'],['done','Terminé']].map(([v,l])=>`<option value="${v}" ${b.project_status===v?'selected':''}>${l}</option>`).join('')}</select></label>${formActions('Enregistrer')}</form>`);$('#researchDetailsForm').onsubmit=e=>{e.preventDefault();run(async()=>{await persistDraft();await saveBook({...state.book,...Object.fromEntries(new FormData(e.target))});state.books=await api('books');$('#modal').close();render()},e.submitter)}
}

function deleteResearchBookModal(book){
  const id=book._book_id;
  showModal(`<h2>Supprimer ce livre ?</h2><p>Le livre « ${esc(book.title)} », son manuscrit, ses dossiers, ses notes de travail et son historique seront définitivement supprimés.</p><p><strong>Les sources et les idées restent dans la bibliothèque commune et les autres livres.</strong></p><form id="deleteResearchBookForm"><label for="deleteBookConfirmation">Écrivez <strong>supprimer</strong> pour confirmer.</label><input id="deleteBookConfirmation" autocomplete="off" spellcheck="false" required autofocus><div class="modal-actions"><button type="button" data-close>Annuler</button><button id="confirmBookDelete" type="submit" class="book-delete-button" disabled>Supprimer le livre</button></div><p id="deleteBookError" class="error" role="alert"></p></form>`);
  const input=$('#deleteBookConfirmation'),button=$('#confirmBookDelete'),error=$('#deleteBookError');
  let deleting=false;
  input.oninput=()=>{button.disabled=deleting||input.value!=='supprimer';error.textContent=''};
  $('#deleteResearchBookForm').onsubmit=async e=>{
    e.preventDefault();
    if(deleting||input.value!=='supprimer')return;
    deleting=true;button.disabled=true;input.disabled=true;error.textContent='';
    try{
      await persistDraft();
      const response=await fetch('/api/v1/books/'+encodeURIComponent(id),{method:'DELETE'});
      const result=await response.json();
      if(!response.ok)throw Error(result.error||'Suppression impossible.');
      clearTimeout(saveTimer);bookDraft=null;bookDirty=false;bookConflict=false;chapterId=null;
      rememberBook(state.books.find(b=>b.id!==id)?.id||'');commonResearch=false;researchFolder='';resetResearchFilters();view='books';
      await AtelierDrafts.remove(id).catch(localDraftError);
      $('#modal').close();
      await reload();render();toast('Livre supprimé. Les sources et les idées sont conservées.');
    }catch(err){error.textContent=err.message;toast(err.message)}
    finally{deleting=false;input.disabled=false;button.disabled=input.value!=='supprimer'}
  };
}
function researchMatches(item,key){const r=researchOf();if(!r[key].includes(item.id))return false;if(researchFolder==='unfiled')return !r.folders.some(f=>f[key].includes(item.id));return !researchFolder||r.folders.find(f=>f.id===researchFolder)?.[key].includes(item.id)}
filtered=function(){const list=researchOriginal.filtered();return commonResearch?list.filter(s=>matchesBookAssignment('source_ids',s.id)):list.filter(s=>researchMatches(s,'source_ids'))};
function researchControls(key){return `<div class="row research-controls"><label>Dossier <select id="researchFolderFilter"><option value="">Tous les dossiers</option><option value="unfiled" ${researchFolder==='unfiled'?'selected':''}>À classer</option>${researchOf().folders.map(f=>`<option value="${esc(f.id)}" ${researchFolder===f.id?'selected':''}>${esc(f.name)}</option>`).join('')}</select></label><button id="pickResearch">Choisir dans la bibliothèque commune</button>${key==='source_ids'&&selected.size?'<button id="classifySelection">Classer la sélection</button>':''}</div>`}
function bindResearchControls(key){$('#researchFolderFilter').onchange=e=>{researchFolder=e.target.value;page=1;render()};$('#pickResearch').onclick=()=>researchPicker(key);$('#classifySelection')?.addEventListener('click',()=>classifyResearch('source_ids',[...selected].filter(id=>researchOf().source_ids.includes(id))))}
card=function(s){let html=researchOriginal.card(s);if(projectContext())html=html.replace('</article>',`<div class="research-item-tools"><span class="small">${researchOf().folders.filter(f=>f.source_ids.includes(s.id)).map(f=>esc(f.name)).join(' · ')||'À classer'}</span><button data-research-source="${esc(s.id)}">Classer / notes</button></div></article>`);else if(commonResearch){html=html.replace('</article>',`<div class="shared-card-books">${bookAssignmentBadges('source_ids',s.id)}</div><div class="research-item-tools"><button data-open="${esc(s.id)}">Ouvrir la source</button><button class="primary" data-link-source="${esc(s.id)}">Lier à des livres</button></div></article>`);if(!yt(s)&&!s.preview_id)html=html.replace('<div class="document-cover">Aa</div>',sourceThumbnail(s))}return html};
renderLibrary=function(){
  if(!commonResearch)folder='';researchOriginal.renderLibrary();
  if(!commonResearch){$('.heading h1').textContent='Sources du livre';$('#folder')?.parentElement.querySelector('#folder')?.remove();$('#clearFolder')?.remove();$('#sync')?.remove();$('.stats').remove();$('.resultbar').before(document.createRange().createContextualFragment(researchControls('source_ids')));bindResearchControls('source_ids')}
  if(filtered().some(s=>yt(s))){
    $('.library-display')?.remove();
    $('.source-grid').classList.remove('library-list');
    $('.source-grid').classList.add('shared-source-grid','library-cards','video-source-grid');
  }
  installResearchCollectionBar('library');
  if(commonResearch){$('.heading h1').textContent='Bibliothèque commune';$('.heading .sub').textContent='Ouvrez vos documents, explorez leurs idées et répartissez-les entre vos livres.';$('.stats')?.remove();$('#sync')?.remove();$('.library-display')?.remove();$('.source-grid').classList.remove('library-list');$('.source-grid').classList.add('shared-source-grid','library-cards');installSharedLibraryTools('source_ids');collapseSharedSourceFilters()}
  if(!commonResearch&&scope==='archived'&&!filtered().length){
    const count=state.sources.filter(s=>s.annotation.archived).length;
    $('.source-grid').after(document.createRange().createContextualFragment(`<div class="notice">Ce livre n’a aucune archive correspondant aux filtres. La bibliothèque commune contient ${count} source(s) archivée(s). <button id="showCommonArchives">Voir toutes les archives</button></div>`));
    $('#showCommonArchives').onclick=()=>openResearchCollection('library',true,true);
  }
  $$('[data-research-source]').forEach(b=>b.onclick=()=>classifyResearch('source_ids',[b.dataset.researchSource]));
  $$('[data-link-source]').forEach(b=>b.onclick=()=>run(()=>linkResearchBooks('source_ids',[b.dataset.linkSource])));
};
function bookIdeaPool(){
  const r=researchOf(),sources=new Set(r.source_ids),retained=new Set(r.idea_ids);
  return state.ideas.filter(i=>retained.has(i.id)||(i.refs||[]).some(ref=>sources.has(ref.source_id)));
}
function linkedResearchBooks(key,id){return (state.books||[]).filter(b=>(b.id===activeBookId?researchOf():b.research)?.[key]?.includes(id))}
function matchesBookAssignment(key,id){const books=linkedResearchBooks(key,id);return !commonAssignmentFilter||(commonAssignmentFilter==='unlinked'?!books.length:books.some(b=>b.id===commonAssignmentFilter))}
function bookAssignmentBadges(key,id,textOnly=false){
  const books=linkedResearchBooks(key,id);
  return books.length?`<span class="small">Lié à ${books.length} livre${books.length>1?'s':''}</span><div class="linked-book-badges">${books.map(b=>`<span>${textOnly?'':b.cover?`<img src="${assetUrl(b.cover)}" alt="">`:uiIcon('▤')}${esc(b.title)}</span>`).join('')}</div>`:'<span class="small">À répartir · aucun livre lié</span>';
}
function sourceThumbnail(s){
  if(!s)return `<span class="source-thumbnail document-thumbnail">${uiIcon('✧')}<small>Idée personnelle</small></span>`;
  if(yt(s))return `<img class="source-thumbnail" src="https://i.ytimg.com/vi/${encodeURIComponent(yt(s))}/hqdefault.jpg" alt="" loading="lazy" referrerpolicy="no-referrer">`;
  if(s.preview_id)return `<img class="source-thumbnail" src="${assetUrl(s.preview_id)}" alt="" loading="lazy">`;
  if(s.kind==='PDF'&&s.asset_id)return `<img class="source-thumbnail" src="/api/pdf-page?id=${encodeURIComponent(s.asset_id)}&page=1" alt="" loading="lazy">`;
  return `<span class="source-thumbnail document-thumbnail"><small>${esc(s.kind||'Document')}</small>${uiIcon('▤')}<strong>${esc(s.title)}</strong><small>${esc(s.author||'')}</small></span>`;
}
function installSharedLibraryTools(key){
  const ids=key==='source_ids'?selected:sharedIdeaSelection;
  const count=ids.size;
  $('.research-collection').insertAdjacentHTML('beforeend',`<div class="shared-library-toolbar"><label>Livres liés<select id="sharedBookFilter"><option value="">Tous les éléments</option><option value="unlinked" ${commonAssignmentFilter==='unlinked'?'selected':''}>À répartir · aucun livre</option>${(state.books||[]).map(b=>`<option value="${esc(b.id)}" ${commonAssignmentFilter===b.id?'selected':''}>${esc(b.title)}</option>`).join('')}</select></label>${count?`<div class="shared-selection-actions"><span>${count} sélectionné(s)</span><button id="linkSharedSelection" class="primary">Lier la sélection à des livres</button><button id="clearSharedSelection">Annuler la sélection</button></div>`:''}</div>`);
  $('#sharedBookFilter').onchange=e=>{commonAssignmentFilter=e.target.value;page=1;ideaVisibleLimit=60;render()};
  $('#linkSharedSelection')?.addEventListener('click',()=>run(()=>linkResearchBooks(key,[...ids])));
  $('#clearSharedSelection')?.addEventListener('click',()=>{ids.clear();render()});
  installSavedLibraryViews(key);
}
function savedLibraryViews(){try{return JSON.parse(localStorage.getItem('atelier-library-views')||'[]').filter(v=>v&&v.id&&v.filters)}catch{return []}}
function libraryViewSnapshot(key){return key==='source_ids'?{query,author,status,kind,folder,scope,tags:tagsSel,sort,book:commonAssignmentFilter}:{query:ideaQuery,folder:ideaFolder,mode:ideaMode,tags:ideaTags,status:libraryIdeaStatus,book:commonAssignmentFilter}}
async function applyLibraryView(key,f){
  resetResearchFilters();libraryIdeaStatus='';
  if(key==='source_ids'){query=f.query||'';author=f.author||'';status=f.status||'';kind=f.kind||'';folder=f.folder||'';scope=f.scope||'all';tagsSel=f.tags||[];sort=f.sort||'recent'}
  else{ideaQuery=f.query||'';ideaFolder=f.folder||'';ideaMode=f.mode||'all';ideaTags=f.tags||[];libraryIdeaStatus=f.status||''}
  commonAssignmentFilter=f.book||'';
  if(key==='source_ids'&&query){const result=await api('source-search?q='+encodeURIComponent(query));sourceSearchIds=new Set(result.ids);sourceSearchPassages={...result.passages,query}}
  render();
}
function installSavedLibraryViews(key){
  const presets=key==='source_ids'?[['unlinked','À répartir',{book:'unlinked'}],['unread','Vidéos à lire',{kind:'Vidéo',status:'À lire'}],['missing','Sources sans texte',{status:'missing'}]]:[['unlinked','À répartir',{book:'unlinked'}],['verify','Idées à vérifier',{status:'À vérifier'}]];
  const saved=savedLibraryViews().filter(v=>v.key===key);
  $('.research-collection').insertAdjacentHTML('beforeend',`<div class="saved-library-views"><label>Vues de tri<select id="librarySavedView"><option value="">Choisir une vue…</option><optgroup label="Vues rapides">${presets.map(([id,title])=>`<option value="preset:${id}">${esc(title)}</option>`).join('')}</optgroup>${saved.length?`<optgroup label="Mes vues">${saved.map(v=>`<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('')}</optgroup>`:''}</select></label><button id="saveLibraryView">Enregistrer cette vue</button>${saved.length?'<button id="manageLibraryViews">Gérer mes vues</button>':''}</div>`);
  $('#librarySavedView').onchange=e=>{const id=e.target.value,f=id.startsWith('preset:')?presets.find(p=>'preset:'+p[0]===id)?.[2]:saved.find(v=>v.id===id)?.filters;if(f)run(async()=>{await applyLibraryView(key,f);$('#librarySavedView').value=id})};
  $('#saveLibraryView').onclick=()=>{const filters=libraryViewSnapshot(key);showModal(`<h2>Enregistrer cette vue de tri</h2><p>Retrouvez ces filtres dans ce navigateur.</p><form id="saveLibraryViewForm"><label>Nom de la vue<input name="name" required maxlength="100" placeholder="Mes recherches sur les relations"></label>${formActions('Enregistrer la vue')}</form>`);$('#saveLibraryViewForm').onsubmit=e=>{e.preventDefault();const name=new FormData(e.target).get('name').trim();if(!name)return;try{const list=savedLibraryViews();list.push({id:newId(),name,key,filters});localStorage.setItem('atelier-library-views',JSON.stringify(list));$('#modal').close();render();toast('Vue enregistrée.')}catch{toast('Impossible de conserver la vue dans ce navigateur.')}}};
  $('#manageLibraryViews')?.addEventListener('click',()=>{showModal(`<h2>Mes vues de tri</h2><div class="saved-views-manager">${saved.map(v=>`<div><span>${esc(v.name)}</span><button data-delete-library-view="${esc(v.id)}">Supprimer</button></div>`).join('')}</div><div class="modal-actions"><button data-close>Fermer</button></div>`);$$('[data-delete-library-view]').forEach(b=>b.onclick=()=>{try{localStorage.setItem('atelier-library-views',JSON.stringify(savedLibraryViews().filter(v=>v.id!==b.dataset.deleteLibraryView)));b.parentElement.remove();render()}catch{toast('Impossible de supprimer cette vue.')}})});
}
function collapseSharedSourceFilters(){
  const filters=$('.filters');if(!filters)return;
  const search=filters.querySelector('.search');if(search)filters.before(search);
  const details=document.createElement('details');details.className='shared-filter-details';details.innerHTML='<summary>Affiner : auteur, format, statut et dossier</summary>';
  filters.before(details);details.append(filters);
  const folderRow=$('#folder')?.closest('.row');if(folderRow)details.append(folderRow);
}
ideaCard=function(i){
  if(!commonResearch)return researchOriginal.ideaCard(i).replace('class="idea-card"','class="idea-card compact-idea-row"');
  const refs=i.refs||[];
  return `<article class="idea-card shared-idea-card compact-idea-row"><div class="shared-idea-content"><div class="idea-row-heading"><label class="shared-idea-check"><input type="checkbox" data-select-shared-idea="${esc(i.id)}" ${sharedIdeaSelection.has(i.id)?'checked':''} aria-label="Sélectionner ${esc(i.title)}"></label><h3><button data-open-shared-idea="${esc(i.id)}">${esc(i.title)}</button></h3><div class="idea-row-actions"><button data-idea-archive="${esc(i.id)}" aria-label="${i.archived?'Restaurer':'Archiver'} cette idée"><svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16v13H4zM3 3h18v4H3zM9 11h6"/></svg></button><button class="heart ${i.liked?'liked':''}" data-idea-like="${esc(i.id)}" aria-label="Aimer cette idée">${uiIcon('♡')}</button></div></div>${i.notes?`<p class="shared-idea-excerpt">${esc(i.notes)}</p>`:''}<div class="idea-row-meta"><span>${esc(i.nature||'Idée')} · ${esc(i.status||'À vérifier')} · ${refs.length} référence${refs.length>1?'s':''}</span><div class="tags">${(i.tags||[]).map(t=>`<button class="tag idea-tag ${ideaTags.includes(t)?'active':''}" data-idea-tag="${esc(t)}" aria-pressed="${ideaTags.includes(t)}" title="Filtrer les idées par ${esc(t)}">${esc(t)}</button>`).join('')}</div></div><div class="idea-row-footer"><div class="idea-row-books">${bookAssignmentBadges('idea_ids',i.id,true)}</div><div class="research-item-tools"><button data-open-shared-idea="${esc(i.id)}">Ouvrir l’idée</button><button data-link-idea="${esc(i.id)}">Lier à des livres</button></div></div></div></article>`;
};
function bindSharedIdeas(){
  $$('[data-open-shared-idea]').forEach(b=>b.onclick=()=>run(()=>openSharedIdea(b.dataset.openSharedIdea)));
  $$('[data-link-idea]').forEach(b=>b.onclick=()=>run(()=>linkResearchBooks('idea_ids',[b.dataset.linkIdea])));
  $$('[data-select-shared-idea]').forEach(b=>b.onchange=()=>{b.checked?sharedIdeaSelection.add(b.dataset.selectSharedIdea):sharedIdeaSelection.delete(b.dataset.selectSharedIdea);renderIdeas()});
}
async function openSharedIdea(id){
  const i=await api('idea?id='+encodeURIComponent(id));
  showModal(`<div class="eyebrow">Idée de la bibliothèque</div><h2>${esc(i.title)}</h2><p class="small">${esc(i.nature||'Idée')} · ${esc(i.status||'À vérifier')}</p><div class="idea-detail-notes">${esc(i.notes||'Aucune note ajoutée.')}</div><div>${bookAssignmentBadges('idea_ids',id)}</div><h3>Passages sources</h3><div class="idea-detail-refs">${(i.refs||[]).map((r,n)=>`<article><button data-idea-detail-source="${n}">${sourceThumbnail(source(r.source_id))}<span><strong>${esc(source(r.source_id)?.title||'Source')}</strong><small>${r.page?'Page '+esc(r.page):r.section?esc(r.section):time(r.start)+'–'+time(r.end)}</small></span></button>${r.quote?`<blockquote>${esc(r.quote)}</blockquote>`:''}</article>`).join('')||'<p>Cette idée ne contient pas de référence source.</p>'}</div><div class="modal-actions"><button data-close>Fermer</button><button id="editSharedIdea">Modifier l’idée</button><button id="detailLinkBooks" class="primary">Lier à des livres</button></div>`);
  $$('[data-idea-detail-source]').forEach(b=>b.onclick=()=>{$('#modal').close();const r=i.refs[Number(b.dataset.ideaDetailSource)];openSource(r.source_id,r.start)});
  $('#editSharedIdea').onclick=()=>ideaModal(i);
  $('#detailLinkBooks').onclick=()=>run(()=>linkResearchBooks('idea_ids',[id]));
}
async function linkResearchBooks(key,ids){
  if(!ids.length)return;
  if(ids.length>200){toast('Sélectionnez au maximum 200 éléments à la fois.');return}
  await persistDraft();if(bookDirty)return;
  const books=await api('books');
  // Read fresh revisions and memberships without switching the current project.
  const full=await Promise.all(books.map(b=>baseApi('book?book_id='+encodeURIComponent(b.id))));
  const originals=new Map(full.map(b=>[b._book_id,new Set(b.research?.[key]||[])])),touched=new Set();
  const folderTouched=new Map();
  const first=key==='source_ids'?source(ids[0]):state.ideas.find(i=>i.id===ids[0]);
  showModal(`<div class="eyebrow">Répartir votre bibliothèque</div><h2>Lier à des livres</h2><p>${ids.length===1?esc(first?.title||'Élément sélectionné'):ids.length+' éléments sélectionnés'}</p><p class="small">Cochez un ou plusieurs livres. Chaque livre garde ses dossiers et ses notes. Décocher retire le lien et son classement dans ce livre ; l’original reste dans la bibliothèque.</p><form id="linkBooksForm"><div class="link-books-grid">${books.map(b=>{const n=ids.filter(id=>originals.get(b.id).has(id)).length;return `<label class="link-book-choice"><input type="checkbox" name="book_ids" value="${esc(b.id)}" ${n===ids.length?'checked':''} data-partial="${n>0&&n<ids.length}"><span class="link-book-cover">${b.cover?`<img src="${assetUrl(b.cover)}" alt="">`:uiIcon('▤')}</span><span><strong>${esc(b.title)}</strong><small>${n===ids.length?'Déjà lié':n?n+' sur '+ids.length+' déjà liés':'Aucun lien avec cette sélection'}</small></span></label>`}).join('')}</div><p id="linkBooksStatus" role="status"></p>${formActions('Enregistrer les liens')}</form>`);
  $$('[name=book_ids]').forEach(input=>{input.indeterminate=input.dataset.partial==='true';input.onchange=()=>{input.indeterminate=false;touched.add(input.value);input.closest('label').classList.toggle('chosen',input.checked)}});
  $$('[name=book_ids]').forEach(input=>{
    const b=full.find(b=>b._book_id===input.value),wrapper=document.createElement('section');wrapper.className='link-book-group';input.closest('label').before(wrapper);wrapper.append(input.closest('label'));
    wrapper.insertAdjacentHTML('beforeend',`<div class="link-book-folders"><strong>Dossiers de ce livre</strong><p class="small">Cocher un dossier ajoute la sélection à ce livre. Les autres classements sont conservés.</p>${(b.research?.folders||[]).map(f=>{const n=ids.filter(id=>f[key].includes(id)).length;return `<label><input type="checkbox" data-link-folder="${esc(f.id)}" data-link-folder-book="${esc(b._book_id)}" ${n===ids.length?'checked':''} data-partial="${n>0&&n<ids.length}">${esc(f.name)}${n&&n<ids.length?` <small>(${n}/${ids.length})</small>`:''}</label>`}).join('')||'<p class="small">Aucun dossier pour le moment.</p>'}<label>Nouveau dossier<input data-new-link-folder="${esc(b._book_id)}" maxlength="150" placeholder="Nom du dossier à créer"></label></div>`);
    const enable=()=>{input.checked=true;input.indeterminate=false;touched.add(input.value)};
    wrapper.querySelectorAll('[data-link-folder]').forEach(c=>{c.indeterminate=c.dataset.partial==='true';c.onchange=()=>{enable();c.indeterminate=false;const changes=folderTouched.get(input.value)||new Map();changes.set(c.dataset.linkFolder,c.checked);folderTouched.set(input.value,changes)}});
    wrapper.querySelector('[data-new-link-folder]').oninput=e=>{if(e.target.value.trim())enable()};
  });
  $('#linkBooksForm').onsubmit=e=>{e.preventDefault();run(async()=>{
    const choices=new Set(new FormData(e.target).getAll('book_ids'));let saved=0;
    try{
      for(const b of books){
        if(!touched.has(b.id))continue;
        let fresh=await baseApi('book?book_id='+encodeURIComponent(b.id));const members=new Set(fresh.research?.[key]||[]),adding=choices.has(b.id);
        const changes=ids.filter(id=>adding?!members.has(id):members.has(id));
        if(changes.length)fresh=await baseApi('book-research',{book_id:b.id,revision:fresh._revision,action:adding?'add':'remove',[key]:changes});
        if(adding){
          const name=$$('[data-new-link-folder]').find(c=>c.dataset.newLinkFolder===b.id)?.value.trim();
          if(name){fresh=await baseApi('book-research',{book_id:b.id,revision:fresh._revision,action:'folder-create',name});const created=fresh.research.folders.at(-1),folders=folderTouched.get(b.id)||new Map();folders.set(created.id,true);folderTouched.set(b.id,folders);$$('[data-new-link-folder]').find(c=>c.dataset.newLinkFolder===b.id).value=''}
          for(const [fid,checked] of folderTouched.get(b.id)||[])fresh=await baseApi('book-research',{book_id:b.id,revision:fresh._revision,action:'classify',[key]:ids,folder_ids:[fid],mode:checked?'add':'remove'});
        }
        saved++;$('#linkBooksStatus').textContent=saved+' livre(s) enregistré(s)…';
      }
    }catch(error){$('#linkBooksStatus').textContent='Les liens déjà enregistrés sont conservés. '+error.message;throw error}
    await reload();bookDraft=null;$('#modal').close();selected.clear();sharedIdeaSelection.clear();render();toast('Liens aux livres enregistrés.');
  },e.submitter)};
}
function ideaInResearchFolder(i,f){return f.idea_ids.includes(i.id)||(i.refs||[]).some(ref=>f.source_ids.includes(ref.source_id))}
function bookIdeaMatches(i){
  if(!researchFolder)return true;
  const folders=researchOf().folders;
  if(researchFolder==='unfiled')return !folders.some(f=>ideaInResearchFolder(i,f));
  const f=folders.find(f=>f.id===researchFolder);return Boolean(f&&ideaInResearchFolder(i,f));
}
function openResearchCollection(v,common,archived=false){
  commonResearch=common;researchFolder='';resetResearchFilters();
  if(archived){if(v==='library')scope='archived';else ideaMode='archived'}
  researchOriginal.navigate(v);
}
function researchCollectionBar(v){
  const count=commonResearch?(v==='library'?state.sources.length:state.ideas.length):(v==='library'?state.sources.filter(s=>researchOf().source_ids.includes(s.id)).length:bookIdeaPool().length);
  const hasFilters=researchFolder||commonAssignmentFilter||libraryIdeaStatus||(v==='library'?(query||author||status||kind||folder||tagsSel.length||scope!=='all'):(ideaQuery||ideaFolder||ideaTags.length||ideaMode!=='all'));
  const selectedFolder=researchOf().folders.find(f=>f.id===researchFolder);
  const folderLabel=researchFolder==='unfiled'?'À classer':selectedFolder?`Dossier « ${esc(selectedFolder.name)} »`:'';
  const visibleSources=v==='library'&&!commonResearch?filtered().length:0;
  const summary=v==='library'&&!commonResearch?`${folderLabel?folderLabel+' · ':''}${visibleSources} source${visibleSources===1?' affichée':'s affichées'} sur ${count} sources du livre`:`${count} idées disponibles`;
  if(commonResearch){return `<section class="research-collection common-collection" aria-label="Bibliothèque commune"><div class="row"><button data-common-section="library" aria-pressed="${v==='library'}">Sources</button><button data-common-section="ideas" aria-pressed="${v==='ideas'}">Idées</button><button data-research-collection="book" aria-label="Revenir au livre ${esc(state.book.title)}" title="${esc(state.book.title)}">Ce livre</button><button id="resetCollectionFilters" ${hasFilters?'':'hidden'}>Effacer les filtres</button></div></section>`}
  return `<section class="research-collection" aria-label="Périmètre de la bibliothèque"><div class="row"><strong>Afficher</strong><button data-research-collection="book" aria-pressed="${!commonResearch}">Ce livre</button><button data-research-collection="common" aria-pressed="${commonResearch}" aria-label="Afficher la bibliothèque commune">Bibliothèque</button><button id="resetCollectionFilters" ${hasFilters?'':'hidden'}>Effacer les filtres</button></div><p class="small">Livre « ${esc(state.book.title)} » · ${summary}</p></section>`;
}
function installResearchCollectionBar(v){
  $('.heading').after(document.createRange().createContextualFragment(researchCollectionBar(v)));
  $$('[data-research-collection]').forEach(b=>b.onclick=()=>openResearchCollection(v,b.dataset.researchCollection==='common'));
  $$('[data-common-section]').forEach(b=>b.onclick=()=>openResearchCollection(b.dataset.commonSection,true));
  $('#resetCollectionFilters').onclick=()=>{researchFolder='';resetResearchFilters();render()};
}
addArchiveTab=function(){
  if(view!=='library'||!$('.tabs'))return;
  researchOriginal.addArchiveTab();
  const pool=commonResearch?state.sources:state.sources.filter(s=>researchOf().source_ids.includes(s.id));
  const b=$('[data-scope="archived"]');b.innerHTML=b.innerHTML.replace(/Archives \(\d+\)/,'Archives ('+pool.filter(s=>s.annotation.archived).length+')');
};
renderIdeas=function(){
  if(commonResearch){
    const all=state.ideas;state.ideas=all.filter(i=>matchesBookAssignment('idea_ids',i.id)&&(!libraryIdeaStatus||(i.status||'À vérifier')===libraryIdeaStatus));
    try{researchOriginal.renderIdeas()}finally{state.ideas=all}
    $('.heading h1').textContent='Idées de la bibliothèque commune';installResearchCollectionBar('ideas');
    $('.idea-list')?.classList.add('compact-idea-list');installSharedLibraryTools('idea_ids');bindSharedIdeas();return;
  }
  const r=researchOf(),retained=new Set(r.idea_ids),pool=bookIdeaPool();
  const archiveCount=pool.filter(i=>i.archived).length;
  const active=pool.filter(i=>!i.archived);
  let items=pool.filter(i=>bookIdeaMatches(i)&&(ideaMode==='archived'?i.archived:!i.archived)&&(ideaMode!=='liked'||i.liked)&&(ideaMode!=='retained'||retained.has(i.id))&&(!ideaTags.length||i.tags?.some(t=>ideaTags.includes(t)))&&(!ideaQuery||norm(i.title+' '+(i.notes||'')+' '+(i.tags||[]).join(' ')).includes(norm(ideaQuery))));
  items.sort((a,b)=>researchIdeaSort==='title'?a.title.localeCompare(b.title,'fr'):String(b.created||'').localeCompare(a.created||''));
  const shown=items.slice(0,ideaVisibleLimit);
  shell(header('La matière du projet','Idées du livre','Les idées des sources de ce livre sont disponibles ici. Retenez et classez celles que vous souhaitez travailler.')+researchControls('idea_ids')+`<div class="tabs"><button data-imode="all" class="${ideaMode==='all'?'active':''}">Toutes les idées (${active.length})</button><button data-imode="retained" class="${ideaMode==='retained'?'active':''}">Retenues (${active.filter(i=>retained.has(i.id)).length})</button><button data-imode="liked" class="${ideaMode==='liked'?'active':''}">Favoris</button></div><div class="row"><input id="researchIdeaSearch" type="search" value="${esc(ideaQuery)}" placeholder="Rechercher une idée"><select id="researchIdeaSort"><option value="recent">Derniers ajouts</option><option value="title" ${researchIdeaSort==='title'?'selected':''}>Titre A → Z</option></select><span>${items.length} idées</span></div>${ideaTags.length?`<div class="tagbar">${ideaTags.map(t=>`<button data-remove-project-idea-tag="${esc(t)}" class="tag active">${esc(t)} ×</button>`).join('')}</div>`:''}<div class="idea-list compact-idea-list">${shown.map(i=>ideaCard(i)).join('')||'<div class="empty">Aucune idée dans cette sélection. Effacez les filtres ou ouvrez la bibliothèque commune pour retrouver toutes les idées.</div>'}</div>${shown.length<items.length?'<button id="moreProjectIdeas">Afficher 60 idées supplémentaires</button>':''}`);
  ideaArchiveTotal=archiveCount;
  bindIdeas();$$('[data-idea-folder]').forEach(e=>{const id=e.dataset.ideaFolder,b=document.createElement('button');b.textContent=retained.has(id)?'Classer / notes':'Retenir pour ce livre';b.onclick=()=>classifyResearch('idea_ids',[id]);e.replaceWith(b)});
  installResearchCollectionBar('ideas');
  $$('[data-imode]').forEach(b=>b.onclick=()=>{ideaMode=b.dataset.imode;ideaVisibleLimit=60;renderIdeas()});
  $$('[data-remove-project-idea-tag]').forEach(b=>b.onclick=()=>{ideaTags=ideaTags.filter(t=>t!==b.dataset.removeProjectIdeaTag);ideaVisibleLimit=60;renderIdeas()});
  bindResearchControls('idea_ids');$('#researchIdeaSearch').oninput=e=>{ideaQuery=e.target.value;ideaVisibleLimit=60;preserveInput(renderIdeas,'researchIdeaSearch')};$('#researchIdeaSort').onchange=e=>{researchIdeaSort=e.target.value;renderIdeas()};
  $('#moreProjectIdeas')?.addEventListener('click',()=>{ideaVisibleLimit+=60;renderIdeas()});
};
function researchFolderModal(f){
  showModal(`<h2>${f?'Renommer le dossier':'Nouveau dossier du livre'}</h2><form id="researchFolderForm"><label>Nom<input name="name" required maxlength="150" value="${esc(f?.name||'')}"></label>${formActions('Enregistrer')}</form>`);
  $('#researchFolderForm').onsubmit=e=>{e.preventDefault();run(async()=>{const before=new Set(researchOf().folders.map(f=>f.id));await changeResearch({action:f?'folder-rename':'folder-create',folder_id:f?.id,name:new FormData(e.target).get('name')});if(!f)researchFolder=researchOf().folders.find(f=>!before.has(f.id))?.id||'';$('#modal').close();render();focusResearchFolder()},e.submitter)};
}
function focusResearchFolder(){
  window.scrollTo(0,0);const title=$('.heading h1');if(title){title.tabIndex=-1;title.focus({preventScroll:true})}
}
function openResearchFolder(id){
  researchFolder=id;folderReaderOrigin='';view='folders';renderFolders();focusResearchFolder();
}
renderFolders=function(){
  if(commonResearch)return researchOriginal.renderFolders();
  const r=researchOf(),f=r.folders.find(f=>f.id===researchFolder);
  const folderActions=f?`<button data-folder-rename="${esc(f.id)}">Renommer</button><button data-folder-remove="${esc(f.id)}">Retirer le dossier</button>`:'<button id="newResearchFolder" class="primary">Nouveau dossier</button>';
  const sources=f?state.sources.filter(s=>f.source_ids.includes(s.id)):[],ideas=f?state.ideas.filter(i=>f.idea_ids.includes(i.id)):[];
  const content=f?`<div class="folder-navigation"><button id="backToFolders">← Tous les dossiers</button><label>Changer de dossier<select id="openResearchFolder">${r.folders.map(item=>`<option value="${esc(item.id)}" ${item.id===f.id?'selected':''}>${esc(item.name)}</option>`).join('')}</select></label></div>
    ${!sources.length&&!ideas.length?'<section class="folder-empty-intro"><h2>Votre dossier est prêt à être rempli</h2><p>Choisissez des sources dans la bibliothèque, puis rassemblez ici les idées utiles pour votre livre.</p></section>':''}
    <section class="panel folder-content" aria-labelledby="folderSourcesTitle"><div class="folder-section-head"><div><h2 id="folderSourcesTitle">Sources (${sources.length})</h2><p>Ouvrez une source pour la lire et en retenir les passages utiles.</p></div><button id="folderAddSources" class="primary">Ajouter des sources</button></div><div class="source-grid">${sources.map(card).join('')||'<p class="folder-empty">Aucune source pour le moment. Ajoutez un document pour commencer.</p>'}</div></section>
    <section class="panel folder-content" aria-labelledby="folderIdeasTitle"><div class="folder-section-head"><div><h2 id="folderIdeasTitle">Idées (${ideas.length})</h2><p>Retrouvez vos idées et leurs références, puis préparez leur place dans le manuscrit.</p></div><button id="folderAddIdeas">Ajouter des idées</button></div><div class="idea-list">${ideas.map(i=>`<article class="folder-idea"><button data-folder-idea="${esc(i.id)}">${esc(i.title)}</button><div class="row"><button data-folder-classify-idea="${esc(i.id)}">Classer / notes</button><button data-book-add="${esc(i.id)}">Au manuscrit</button></div></article>`).join('')||'<p class="folder-empty">Aucune idée pour le moment. Retenez un passage dans une source ou ajoutez une idée existante.</p>'}</div></section>`:
    `<div class="research-folder-grid">${r.folders.map(item=>`<article class="panel"><h2>${esc(item.name)}</h2><p>${item.source_ids.length} sources · ${item.idea_ids.length} idées</p><div class="row"><button class="primary" data-folder-open="${esc(item.id)}" aria-label="Ouvrir le dossier ${esc(item.name)}">Ouvrir le dossier →</button><button data-folder-rename="${esc(item.id)}">Renommer</button><button data-folder-remove="${esc(item.id)}">Retirer le dossier</button></div></article>`).join('')||'<div class="empty"><h2>Un thème, un dossier</h2><p>Créez un dossier, puis ajoutez-y les sources et les idées qui nourriront votre livre.</p></div>'}</div>`;
  shell(header(f?'Dossier du livre':'Organiser la recherche',f?esc(f.name):'Dossiers du livre',f?`${sources.length} source${sources.length===1?'':'s'} · ${ideas.length} idée${ideas.length===1?'':'s'} · ${esc(state.book.title)}`:'Regroupez votre matière par thème. Ouvrez un dossier pour consulter et compléter son contenu.',folderActions)+content);
  if(f){const crumb=$('.crumb');if(crumb)crumb.textContent=state.book.title+' / Dossiers / '+f.name}
  $('#newResearchFolder')?.addEventListener('click',()=>researchFolderModal());
  $$('[data-folder-open]').forEach(b=>b.onclick=()=>openResearchFolder(b.dataset.folderOpen));
  $$('[data-folder-rename]').forEach(b=>b.onclick=()=>researchFolderModal(r.folders.find(f=>f.id===b.dataset.folderRename)));
  $$('[data-folder-remove]').forEach(b=>b.onclick=()=>{showModal(`<h2>Retirer ce dossier ?</h2><p>Ses sources et ses idées resteront dans le livre.</p><div class="modal-actions"><button data-close>Annuler</button><button id="confirmResearchFolderRemove">Retirer le dossier</button></div>`);$('#confirmResearchFolderRemove').onclick=e=>run(async()=>{await changeResearch({action:'folder-delete',folder_id:b.dataset.folderRemove});researchFolder='';$('#modal').close();render();focusResearchFolder()},e.currentTarget)});
  if(!f)return;
  $('#backToFolders').onclick=()=>openResearchFolder('');$('#openResearchFolder').onchange=e=>openResearchFolder(e.target.value);
  $('#folderAddSources').onclick=()=>researchPicker('source_ids',f.id);$('#folderAddIdeas').onclick=()=>researchPicker('idea_ids',f.id);
  // Keep card actions inside the open dossier instead of jumping to the source library.
  $$('[data-select]').forEach(input=>input.remove());
  $$('[data-open]').forEach(b=>b.onclick=()=>openSource(b.dataset.open));
  for(const attr of ['like','archive'])$$(`[data-${attr}]`).forEach(b=>b.onclick=()=>run(async()=>{const item=source(b.dataset[attr]),key=attr==='like'?'liked':'archived';const annotation=await api('annotation',{id:item.id,[key]:!item.annotation[key]});if(current?.id===item.id)current.annotation=annotation;await reload();render()},b));
  $$('[data-tag]').forEach(b=>b.onclick=()=>{resetResearchFilters();tagsSel=[b.dataset.tag];navigate('library')});
  $$('[data-research-source]').forEach(b=>b.onclick=()=>classifyResearch('source_ids',[b.dataset.researchSource]));
  $$('[data-folder-idea]').forEach(b=>b.onclick=()=>run(async()=>ideaModal(await api('idea?id='+encodeURIComponent(b.dataset.folderIdea)))));
  $$('[data-folder-classify-idea]').forEach(b=>b.onclick=()=>classifyResearch('idea_ids',[b.dataset.folderClassifyIdea]));
  $$('[data-book-add]').forEach(b=>b.onclick=()=>addToBookModal(b.dataset.bookAdd));
};
const folderOriginalOpenSource=openSource;
openSource=async function(id,start=0){
  if(view!=='reader')folderReaderOrigin=view==='folders'&&!commonResearch?researchFolder:'';
  return folderOriginalOpenSource(id,start);
};
function researchPicker(key,fid=''){
  const choices=new Set(),items=key==='source_ids'?state.sources:state.ideas;let offset=0;
  showModal(`<h2>${key==='source_ids'?'Choisir des sources':'Choisir des idées'}</h2><p>${fid?`Ajouter au dossier « ${esc(researchOf().folders.find(f=>f.id===fid)?.name||'')} » du livre « ${esc(state.book.title)} ».`:`Ajouter à « ${esc(state.book.title)} ».`} Les originaux restent réutilisables dans les autres livres.</p><input id="researchPickerQuery" type="search" placeholder="Rechercher par titre, auteur ou tag"><div class="row"><button id="researchPickerAll">Cocher les résultats affichés</button><span id="researchPickerCount"></span></div><div id="researchPickerItems" class="project-source-list"></div><div class="row"><button id="researchPickerPrev">Précédent</button><button id="researchPickerNext">Suivant</button></div><div class="modal-actions"><button data-close>Annuler</button><button id="researchPickerSave" class="primary">Ajouter au livre${fid?' et au dossier':''}</button></div>`);
  let visible=[];function fill(){const q=norm($('#researchPickerQuery').value),all=items.filter(i=>!q||norm(i.title+' '+(i.author||'')+' '+(i.tags||i.annotation?.tags||[]).join(' ')).includes(q));visible=all.slice(offset,offset+100);$('#researchPickerCount').textContent=choices.size+' cochés · '+all.length+' résultats';$('#researchPickerItems').innerHTML=visible.map(i=>`<label class="project-source"><input type="checkbox" data-research-pick="${esc(i.id)}" ${choices.has(i.id)?'checked':''}><span><strong>${esc(i.title)}</strong><small>${esc(i.author||'')}${researchOf()[key].includes(i.id)?' · déjà dans le livre':''}</small></span></label>`).join('');$('#researchPickerPrev').disabled=offset===0;$('#researchPickerNext').disabled=offset+100>=all.length;$$('[data-research-pick]').forEach(c=>c.onchange=()=>{if(c.checked&&choices.size>=200){c.checked=false;toast('Ajoutez au maximum 200 éléments à la fois.');return}c.checked?choices.add(c.dataset.researchPick):choices.delete(c.dataset.researchPick);$('#researchPickerCount').textContent=choices.size+' cochés · '+all.length+' résultats'})}fill();
  $('#researchPickerQuery').oninput=()=>{offset=0;fill()};$('#researchPickerPrev').onclick=()=>{offset-=100;fill()};$('#researchPickerNext').onclick=()=>{offset+=100;fill()};$('#researchPickerAll').onclick=()=>{for(const i of visible){if(choices.size>=200)break;choices.add(i.id)}fill()};$('#researchPickerSave').onclick=e=>run(async()=>{await changeResearch({action:'add',[key]:[...choices],folder_ids:fid?[fid]:[],mode:'add'});$('#modal').close();render()},e.currentTarget);
}
function classifyResearch(key,ids){
  if(!ids.length){toast('Choisissez des éléments de ce livre.');return}const r=researchOf(),notes=key==='source_ids'?r.source_notes:r.idea_notes,linked=ids.every(id=>r[key].includes(id));
  showModal(`<h2>${linked?'Classer dans ce livre':'Ajouter à ce livre'}</h2><p>${ids.length} élément(s) · ${esc(state.book.title)}</p><form id="researchClassifyForm"><label>Classement<select id="researchClassifyMode"><option value="${ids.length===1?'replace':'add'}">${ids.length===1?'Choisir les dossiers':'Ajouter aux dossiers cochés'}</option>${ids.length===1?'':'<option value="replace">Remplacer le classement</option><option value="remove">Retirer des dossiers cochés</option>'}</select></label><div class="research-folder-checks">${r.folders.map(f=>`<label><input type="checkbox" name="folder_ids" value="${esc(f.id)}" ${ids.length===1&&f[key].includes(ids[0])?'checked':''}>${esc(f.name)}</label>`).join('')||'<p>Aucun dossier. Cet élément restera dans « À classer ».</p>'}</div>${ids.length===1?`<label>Note de travail pour ce livre<textarea id="researchNote" maxlength="6000" rows="4">${esc(notes?.[ids[0]]||'')}</textarea></label>`:''}${formActions('Enregistrer le classement')}</form>${linked?'<button id="removeResearchItems">Retirer du livre</button><p class="small">Les originaux restent dans la bibliothèque commune et les autres livres.</p>':''}`);
  $('#researchClassifyForm').onsubmit=e=>{e.preventDefault();run(async()=>{const folder_ids=new FormData(e.target).getAll('folder_ids');await changeResearch({action:'classify',[key]:ids,folder_ids,mode:$('#researchClassifyMode').value});if(ids.length===1)await changeResearch({action:'notes',[key]:ids,note:$('#researchNote').value});$('#modal').close();render()},e.submitter)};
  $('#removeResearchItems')?.addEventListener('click',e=>run(async()=>{await changeResearch({action:'remove',[key]:ids});ids.forEach(id=>selected.delete(id));$('#modal').close();render()},e.currentTarget));
}
// Associate explicit imports with the current book, including previously imported videos.
api=async function(path,data){
  const bid=activeBookId,attach=projectContext()&&data!==undefined&&['youtube','import','idea'].includes(path),result=await researchOriginal.api(path,data);
  // Older running servers can serve the new interface before their next restart.
  const books=data===undefined?(path==='books'?result:/^library(\?|$)/.test(path)?result.books:null):null;
  if(books?.some(b=>!b.research))await Promise.all(books.filter(b=>!b.research).map(async b=>{const full=await baseApi('book?book_id='+encodeURIComponent(b.id));b.research=full.research||{source_ids:[],idea_ids:[]}}));
  if(attach&&bid===activeBookId){const item=result.source||result;if(item.id)await changeResearch({action:'add',[path==='idea'?'idea_ids':'source_ids']:[item.id]})}
  return result;
};
uploadFile=async function(file,meta={},asSource=true,onProgress=()=>{}){const bid=activeBookId,attach=asSource&&projectContext(),result=await researchOriginal.uploadFile(file,meta,asSource,onProgress);if(attach&&bid===activeBookId){const item=result.source||result;if(item.id)await changeResearch({action:'add',source_ids:[item.id]})}return result};

renderReader=function(){
  researchOriginal.renderReader();
  const origin=researchOf().folders.find(f=>f.id===folderReaderOrigin);
  if(!commonResearch&&origin&&$('#back')){const back=$('#back');back.textContent='← Retour au dossier « '+origin.name+' »';back.onclick=()=>openResearchFolder(origin.id)}
  const like=$('#readerLike');if(like){const label=current.annotation.liked?'Retirer des favoris':'Ajouter aux favoris';like.setAttribute('aria-label',label);like.innerHTML=uiIcon('♡')+`<span class="source-action-full">${label}</span><span class="source-action-short" aria-hidden="true">Favoris</span>`}
  $('.reader-head').insertAdjacentHTML('beforeend',`<div class="reader-book-links"><div>${bookAssignmentBadges('source_ids',current.id)}</div><button id="readerLinkBooks" class="primary">Lier à des livres</button></div>`);
  $('#readerLinkBooks').onclick=()=>run(()=>linkResearchBooks('source_ids',[current.id]));
  if(!commonResearch&&$('#readFolder')){
    const button=document.createElement('button');button.textContent='Dossiers de ce livre';button.onclick=()=>classifyResearch('source_ids',[current.id]);$('#readFolder').hidden=true;$('#readFolder').after(button);
    $('#notes').value=researchOf().source_notes?.[current.id]||'';
    $('#notes').setAttribute('placeholder','Votre note de travail pour ce livre');
    $('#saveAnnotation').onclick=e=>run(async()=>{
      const note=$('#notes').value;
      current.annotation=await api('annotation',{id:current.id,tags:$('#readTags').value.split(',').map(t=>t.trim()).filter(Boolean),state:$('#readState').value});
      if(!researchOf().source_ids.includes(current.id))await changeResearch({action:'add',source_ids:[current.id]});
      await changeResearch({action:'notes',source_ids:[current.id],note});await reload();toast('Note enregistrée pour ce livre.');
    },e.currentTarget);
  }
};

ideaModal=function(existing=null){
  researchOriginal.ideaModal(existing);
  if(!commonResearch){const select=$('#ideaForm [name=folder]');if(select)select.closest('label').hidden=true;const notice=document.createElement('p');notice.className='small';notice.textContent='Cette idée appartient au livre ouvert. Ses dossiers et sa note de travail se règlent avec « Classer / notes ».';$('#ideaForm').append(notice)}
};

function bookPresentationCard(b){
  const cover=b.covers?.front;
  return `<section class="book-presentation" aria-label="Couverture et téléchargement"><button id="overviewCoverPreview" class="book-preview-cover" aria-label="${cover?'Modifier':'Ajouter'} la couverture">${cover?`<img src="${assetUrl(cover)}" alt="Couverture du livre">`:`${uiIcon('▧')}<span>Ajouter votre<br>photo de couverture</span>`}</button><div class="book-presentation-content"><h2>Présentation et téléchargement</h2><p>${cover?'Votre couverture accompagnera le PDF et l’EPUB.':'Personnalisez la couverture ou téléchargez une version de votre travail.'}</p><div class="book-access-buttons"><button id="overviewDownload">${uiIcon('↓')} Télécharger le livre</button><button id="overviewCover">${cover?'Modifier la couverture':'Ajouter une couverture'}</button><button id="overviewImages">Images et schémas</button></div><small>PDF pour imprimer · EPUB pour lire · Texte pour retravailler</small></div></section>`;
}
function bindBookPresentation(){
  const cover=()=>{ensureDraft();bookDraft.covers?.front?coverModal():coverPickerModal('front')};
  $('#overviewCoverPreview').onclick=cover;$('#overviewCover').onclick=cover;
  $('#overviewDownload').onclick=()=>{ensureDraft();exportModal()};
  $('#overviewImages').onclick=mediaLibraryModal;
}
$('#modal').addEventListener('close',()=>{
  if(view==='overview'&&!loggedOut)run(async()=>{await persistDraft();if(view==='overview')renderResearchOverview()});
});
