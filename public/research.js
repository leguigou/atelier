/* Books are the entry point; shared research is linked into independent workspaces. */
let commonResearch=false, researchFolder='', researchIdeaSort='recent';
view='books';
const researchOf=()=>state.book.research||{source_ids:state.book.source_ids||[],idea_ids:[],folders:[],source_notes:{},idea_notes:{}};
const projectContext=()=>!commonResearch&&!['books','settings'].includes(view);
const researchOriginal={shell,render,navigate,filtered,renderLibrary,renderIdeas,renderFolders,renderReader,ideaModal,ideaCard,card,api,uploadFile,addArchiveTab};
let commonAssignmentFilter='', sharedIdeaSelection=new Set();

async function changeResearch(data){
  await persistDraft();
  const b=await researchOriginal.api('book-research',{book_id:activeBookId,revision:state.book._revision,...data});
  state.book=b;if(bookDraft&&!bookDirty)bookDraft=structuredClone(b);
  state.books=await api('books');return b;
}
async function openResearchBook(id){
  await persistDraft();if(bookDirty)return;
  rememberBook(id);bookDraft=null;chapterId=null;commonResearch=false;researchFolder='';resetResearchFilters();
  await reload();view='overview';render();
}
function resetResearchFilters(){query='';author='';status='';kind='';folder='';scope='all';tagsSel=[];page=1;selected.clear();sharedIdeaSelection.clear();commonAssignmentFilter='';sourceSearchIds=null;sourceSearchPassages=null;clearTimeout(sourceSearchTimer);ideaQuery='';ideaMode='all';ideaFolder='';ideaTags=[];ideaVisibleLimit=60}
navigate=function(v){
  if(v==='common'){commonResearch=true;researchFolder='';resetResearchFilters();v='library'}
  else if(['books','overview','ideas','folders','book'].includes(v)&&commonResearch){commonResearch=false;researchFolder='';resetResearchFilters()}
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
  const nav=[['books','▤','Mes livres'],['overview','▤','Vue d’ensemble'],['folders','▱','Dossiers'],['library','▦','Sources'],['ideas','✧','Idées'],['book','▤','Manuscrit'],['common','▦','Bibliothèque commune'],['settings','⚙','Réglages']];
  $('.nav').innerHTML=nav.map(([v,i,l])=>`<button data-nav="${v}" class="${(v==='common'?commonResearch&&['library','ideas','reader'].includes(view):v===view&&!(commonResearch&&['library','ideas','reader'].includes(v)))?'active':''}"><span class="icon">${uiIcon(i)}</span>${l}</button>`).join('');
  $$('[data-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.nav==='library'&&commonResearch){commonResearch=false;resetResearchFilters()}navigate(b.dataset.nav)});
  $('.mobile-nav').innerHTML=[['books','▤','Livres'],['common','▦','Bibliothèque'],['library','▦','Sources'],['folders','▱','Dossiers'],['book','▤','Écrire']].map(([v,i,l])=>`<button data-mobile-nav="${v}" class="${(v==='common'?commonResearch:view===v&&!commonResearch)?'active':''}">${uiIcon(i)}<small>${l}</small></button>`).join('');
  $$('[data-mobile-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.mobileNav==='library'&&commonResearch){commonResearch=false;resetResearchFilters()}navigate(b.dataset.mobileNav)});
  const crumb=$('.crumb');if(crumb)crumb.textContent=view==='books'?'Mes livres':commonResearch?'Bibliothèque commune':state.book.title+' / '+(nav.find(n=>n[0]===view)?.[2]||'Lecture');
  if(view!=='books'&&view!=='settings'&&!commonResearch){
    $('.main').insertAdjacentHTML('afterbegin',`<div class="research-context"><label>Livre <select id="researchBookSelect">${(state.books||[]).map(b=>`<option value="${esc(b.id)}" ${b.id===activeBookId?'selected':''}>${esc(b.title)}</option>`).join('')}</select></label><button id="researchAllBooks">Mes livres</button>${commonResearch?'<span class="small">Documents partagés entre tous les livres</span>':`<span class="small">${esc(state.book.description||'Sources, idées et dossiers de ce livre')}</span>`}</div>`);
    $('#researchBookSelect').onchange=e=>run(()=>openResearchBook(e.target.value));$('#researchAllBooks').onclick=()=>navigate('books');
  }
};
function renderBooks(){
  shell(header('Votre bibliothèque personnelle','Mes livres','Choisissez un livre pour retrouver sa matière et son manuscrit.','<button id="createResearchBook" class="primary">Créer un livre</button>')+`<div class="books-grid">${(state.books||[]).map(b=>`<article class="project-book"><button data-open-book="${esc(b.id)}" class="project-book-cover" aria-label="Ouvrir ${esc(b.title)}">${b.cover?`<img src="${assetUrl(b.cover)}" alt="">`:`<span>${uiIcon('▤')}</span>`}</button><div><h2>${esc(b.title)}</h2><p>${esc(b.description||b.author||'Un projet à faire grandir')}</p><span class="small">${({preparation:'En préparation',writing:'En écriture',done:'Terminé'})[b.project_status]||'En préparation'} · ${b.chapters} chapitres · ${b.sources||0} sources · ${b.ideas||0} idées retenues</span><p><button data-open-book="${esc(b.id)}" class="primary">Ouvrir le livre</button></p></div></article>`).join('')}</div>`);
  $('#createResearchBook').onclick=newBookModal;$$('[data-open-book]').forEach(b=>b.onclick=()=>run(()=>openResearchBook(b.dataset.openBook),b));
}
newBookModal=function(){
  showModal(`<h2>Créer un livre</h2><p>Commencez par votre projet. Vous pourrez ajouter sa matière et son plan ensuite.</p><form id="newBookForm"><label>Titre<input name="title" required maxlength="300"></label><label>Quelques mots sur ce projet<textarea name="description" maxlength="6000" rows="3"></textarea></label><label>Auteur<input name="author" maxlength="300"></label>${formActions('Créer le livre')}</form>`);
  $('#newBookForm').onsubmit=e=>{e.preventDefault();run(async()=>{await persistDraft();const b=await api('book-create',Object.fromEntries(new FormData(e.target)));await openResearchBook(b._book_id);$('#modal').close()},e.submitter)};
};
function renderResearchOverview(){
  const r=researchOf(),b=state.book;
  shell(header('Votre projet',esc(b.title),esc(b.description)||'Organisez la matière de ce livre, puis avancez dans le manuscrit.','<button id="researchDetails">Décrire le projet</button>')+bookPresentationCard(b)+`<div class="stats"><div class="stat"><strong>${r.source_ids.length}</strong><span>sources du livre</span></div><div class="stat"><strong>${bookIdeaPool().length}</strong><span>idées disponibles</span></div><div class="stat"><strong>${r.folders.length}</strong><span>dossiers</span></div><div class="stat"><strong>${b.chapters.length}</strong><span>chapitres</span></div></div><div class="research-start"><section class="panel"><h2>Rassembler la matière</h2><p>Ajoutez vos documents, retrouvez des idées et classez-les dans un ou plusieurs dossiers.</p><div class="row"><button id="overviewSources">Sources</button><button id="overviewIdeas">Idées</button><button id="overviewFolders">Dossiers</button></div></section><section class="panel"><h2>Faire avancer le livre</h2><p>${esc(b.brief?.intention||'Définissez votre intention, construisez un plan et commencez à écrire.')}</p><button id="overviewWrite" class="primary">Ouvrir le manuscrit</button></section></div><section class="panel"><h2>Bibliothèque commune</h2><p>Réutilisez une source ou une idée dans plusieurs livres. Chaque projet conserve son propre classement et ses notes de travail.</p><button id="overviewCommon">Explorer les sources communes</button></section>`);
  bindBookPresentation();
  for(const [id,v] of [['overviewSources','library'],['overviewIdeas','ideas'],['overviewFolders','folders'],['overviewWrite','book'],['overviewCommon','common']])$('#'+id).onclick=()=>navigate(v);
  $('#researchDetails').onclick=()=>{showModal(`<h2>Décrire le projet</h2><form id="researchDetailsForm"><label>Titre<input name="title" required maxlength="300" value="${esc(b.title)}"></label><label>Description<textarea name="description" maxlength="6000">${esc(b.description||'')}</textarea></label><label>État du livre<select name="project_status">${[['preparation','En préparation'],['writing','En écriture'],['done','Terminé']].map(([v,l])=>`<option value="${v}" ${b.project_status===v?'selected':''}>${l}</option>`).join('')}</select></label>${formActions('Enregistrer')}</form>`);$('#researchDetailsForm').onsubmit=e=>{e.preventDefault();run(async()=>{await persistDraft();await saveBook({...state.book,...Object.fromEntries(new FormData(e.target))});state.books=await api('books');$('#modal').close();render()},e.submitter)}};
}
function researchMatches(item,key){const r=researchOf();if(!r[key].includes(item.id))return false;if(researchFolder==='unfiled')return !r.folders.some(f=>f[key].includes(item.id));return !researchFolder||r.folders.find(f=>f.id===researchFolder)?.[key].includes(item.id)}
filtered=function(){const list=researchOriginal.filtered();return commonResearch?list.filter(s=>matchesBookAssignment('source_ids',s.id)):list.filter(s=>researchMatches(s,'source_ids'))};
function researchControls(key){return `<div class="row research-controls"><label>Dossier <select id="researchFolderFilter"><option value="">Tous les dossiers</option><option value="unfiled" ${researchFolder==='unfiled'?'selected':''}>À classer</option>${researchOf().folders.map(f=>`<option value="${esc(f.id)}" ${researchFolder===f.id?'selected':''}>${esc(f.name)}</option>`).join('')}</select></label><button id="pickResearch">Choisir dans la bibliothèque commune</button>${key==='source_ids'&&selected.size?'<button id="classifySelection">Classer la sélection</button>':''}</div>`}
function bindResearchControls(key){$('#researchFolderFilter').onchange=e=>{researchFolder=e.target.value;page=1;render()};$('#pickResearch').onclick=()=>researchPicker(key);$('#classifySelection')?.addEventListener('click',()=>classifyResearch('source_ids',[...selected].filter(id=>researchOf().source_ids.includes(id))))}
card=function(s){let html=researchOriginal.card(s);if(projectContext())html=html.replace('</article>',`<div class="research-item-tools"><span class="small">${researchOf().folders.filter(f=>f.source_ids.includes(s.id)).map(f=>esc(f.name)).join(' · ')||'À classer'}</span><button data-research-source="${esc(s.id)}">Classer / notes</button></div></article>`);else if(commonResearch){html=html.replace('</article>',`<div class="shared-card-books">${bookAssignmentBadges('source_ids',s.id)}</div><div class="research-item-tools"><button data-open="${esc(s.id)}">Ouvrir la source</button><button class="primary" data-link-source="${esc(s.id)}">Lier à des livres</button></div></article>`);if(!yt(s)&&!s.preview_id)html=html.replace('<div class="document-cover">Aa</div>',sourceThumbnail(s))}return html};
renderLibrary=function(){
  if(!commonResearch)folder='';researchOriginal.renderLibrary();
  if(!commonResearch){$('.heading h1').textContent='Sources du livre';$('#folder')?.parentElement.querySelector('#folder')?.remove();$('#clearFolder')?.remove();$('#sync')?.remove();$('.stats').remove();$('.resultbar').before(document.createRange().createContextualFragment(researchControls('source_ids')));bindResearchControls('source_ids')}
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
function bookAssignmentBadges(key,id){
  const books=linkedResearchBooks(key,id);
  return books.length?`<span class="small">Lié à ${books.length} livre${books.length>1?'s':''}</span><div class="linked-book-badges">${books.map(b=>`<span>${b.cover?`<img src="${assetUrl(b.cover)}" alt="">`:uiIcon('▤')}${esc(b.title)}</span>`).join('')}</div>`:'<span class="small">À répartir · aucun livre lié</span>';
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
}
function collapseSharedSourceFilters(){
  const filters=$('.filters');if(!filters)return;
  const search=filters.querySelector('.search');if(search)filters.before(search);
  const details=document.createElement('details');details.className='shared-filter-details';details.innerHTML='<summary>Affiner : auteur, format, statut et dossier</summary>';
  filters.before(details);details.append(filters);
  const folderRow=$('#folder')?.closest('.row');if(folderRow)details.append(folderRow);
}
ideaCard=function(i){
  if(!commonResearch)return researchOriginal.ideaCard(i);
  const s=(i.refs||[]).map(r=>source(r.source_id)).find(Boolean);
  return `<article class="idea-card shared-idea-card"><button class="shared-idea-preview" data-open-shared-idea="${esc(i.id)}" aria-label="Ouvrir l’idée ${esc(i.title)}">${sourceThumbnail(s)}<span class="preview-label">Idée · ${esc(s?.author||'Note personnelle')}</span></button><div class="shared-idea-content"><div class="row"><label class="shared-idea-check"><input type="checkbox" data-select-shared-idea="${esc(i.id)}" ${sharedIdeaSelection.has(i.id)?'checked':''} aria-label="Sélectionner ${esc(i.title)}">Sélectionner</label><button data-idea-archive="${esc(i.id)}" aria-label="${i.archived?'Restaurer':'Archiver'} cette idée">${i.archived?'Restaurer':'Archiver'}</button><button class="heart ${i.liked?'liked':''}" data-idea-like="${esc(i.id)}" aria-label="Aimer cette idée">${uiIcon('♡')}</button></div><h3><button data-open-shared-idea="${esc(i.id)}">${esc(i.title)}</button></h3><p class="shared-idea-excerpt">${esc(i.notes||'Ouvrez cette idée pour retrouver son contexte et ses passages sources.')}</p><div class="tags">${(i.tags||[]).slice(0,4).map(t=>`<button class="tag" data-idea-tag="${esc(t)}">${esc(t)}</button>`).join('')}</div>${bookAssignmentBadges('idea_ids',i.id)}<div class="research-item-tools"><button data-open-shared-idea="${esc(i.id)}">Ouvrir l’idée</button><button class="primary" data-link-idea="${esc(i.id)}">Lier à des livres</button></div></div></article>`;
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
  const first=key==='source_ids'?source(ids[0]):state.ideas.find(i=>i.id===ids[0]);
  showModal(`<div class="eyebrow">Répartir votre bibliothèque</div><h2>Lier à des livres</h2><p>${ids.length===1?esc(first?.title||'Élément sélectionné'):ids.length+' éléments sélectionnés'}</p><p class="small">Cochez un ou plusieurs livres. Chaque livre garde ses dossiers et ses notes. Décocher retire le lien et son classement dans ce livre ; l’original reste dans la bibliothèque.</p><form id="linkBooksForm"><div class="link-books-grid">${books.map(b=>{const n=ids.filter(id=>originals.get(b.id).has(id)).length;return `<label class="link-book-choice"><input type="checkbox" name="book_ids" value="${esc(b.id)}" ${n===ids.length?'checked':''} data-partial="${n>0&&n<ids.length}"><span class="link-book-cover">${b.cover?`<img src="${assetUrl(b.cover)}" alt="">`:uiIcon('▤')}</span><span><strong>${esc(b.title)}</strong><small>${n===ids.length?'Déjà lié':n?n+' sur '+ids.length+' déjà liés':'Aucun lien avec cette sélection'}</small></span></label>`}).join('')}</div><p id="linkBooksStatus" role="status"></p>${formActions('Enregistrer les liens')}</form>`);
  $$('[name=book_ids]').forEach(input=>{input.indeterminate=input.dataset.partial==='true';input.onchange=()=>{input.indeterminate=false;touched.add(input.value);input.closest('label').classList.toggle('chosen',input.checked)}});
  $('#linkBooksForm').onsubmit=e=>{e.preventDefault();run(async()=>{
    const choices=new Set(new FormData(e.target).getAll('book_ids'));let saved=0;
    try{
      for(const b of books){
        if(!touched.has(b.id))continue;
        const fresh=await baseApi('book?book_id='+encodeURIComponent(b.id)),members=new Set(fresh.research?.[key]||[]),adding=choices.has(b.id);
        const changes=ids.filter(id=>adding?!members.has(id):members.has(id));
        if(changes.length)await baseApi('book-research',{book_id:b.id,revision:fresh._revision,action:adding?'add':'remove',[key]:changes});
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
  if(commonResearch){const hasFilters=commonAssignmentFilter||(v==='library'?(query||author||status||kind||folder||tagsSel.length||scope!=='all'):(ideaQuery||ideaFolder||ideaTags.length||ideaMode!=='all'));return `<section class="research-collection common-collection" aria-label="Bibliothèque commune"><div class="row"><button data-common-section="library" aria-pressed="${v==='library'}">Sources</button><button data-common-section="ideas" aria-pressed="${v==='ideas'}">Idées</button><button data-research-collection="book">Ce livre</button><button id="resetCollectionFilters" ${hasFilters?'':'hidden'}>Effacer les filtres</button></div></section>`}
  return `<section class="research-collection" aria-label="Périmètre de la bibliothèque"><div class="row"><strong>Afficher</strong><button data-research-collection="book" aria-pressed="${!commonResearch}">Ce livre</button><button data-research-collection="common" aria-pressed="${commonResearch}">Bibliothèque commune</button><button id="resetCollectionFilters">Effacer les filtres</button></div><p class="small">${commonResearch?'Tous les livres · bibliothèque complète':`Livre « ${esc(state.book.title)} »`} · ${count} ${v==='library'?'sources':'idées disponibles'}</p>${commonResearch?`<div class="row"><button data-common-section="library" aria-pressed="${v==='library'}">Sources</button><button data-common-section="ideas" aria-pressed="${v==='ideas'}">Idées</button></div>`:''}</section>`;
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
    const all=state.ideas;state.ideas=all.filter(i=>matchesBookAssignment('idea_ids',i.id));
    try{researchOriginal.renderIdeas()}finally{state.ideas=all}
    $('.heading h1').textContent='Idées de la bibliothèque commune';installResearchCollectionBar('ideas');
    $('.idea-list')?.classList.add('shared-idea-grid');installSharedLibraryTools('idea_ids');bindSharedIdeas();return;
  }
  const r=researchOf(),retained=new Set(r.idea_ids),pool=bookIdeaPool();
  const archiveCount=pool.filter(i=>i.archived).length;
  const active=pool.filter(i=>!i.archived);
  let items=pool.filter(i=>bookIdeaMatches(i)&&(ideaMode==='archived'?i.archived:!i.archived)&&(ideaMode!=='liked'||i.liked)&&(ideaMode!=='retained'||retained.has(i.id))&&(!ideaTags.length||i.tags?.some(t=>ideaTags.includes(t)))&&(!ideaQuery||norm(i.title+' '+(i.notes||'')+' '+(i.tags||[]).join(' ')).includes(norm(ideaQuery))));
  items.sort((a,b)=>researchIdeaSort==='title'?a.title.localeCompare(b.title,'fr'):String(b.created||'').localeCompare(a.created||''));
  const shown=items.slice(0,ideaVisibleLimit);
  shell(header('La matière du projet','Idées du livre','Les idées des sources de ce livre sont disponibles ici. Retenez et classez celles que vous souhaitez travailler.')+researchControls('idea_ids')+`<div class="tabs"><button data-imode="all" class="${ideaMode==='all'?'active':''}">Toutes les idées (${active.length})</button><button data-imode="retained" class="${ideaMode==='retained'?'active':''}">Retenues (${active.filter(i=>retained.has(i.id)).length})</button><button data-imode="liked" class="${ideaMode==='liked'?'active':''}">Favoris</button></div><div class="row"><input id="researchIdeaSearch" type="search" value="${esc(ideaQuery)}" placeholder="Rechercher une idée"><select id="researchIdeaSort"><option value="recent">Derniers ajouts</option><option value="title" ${researchIdeaSort==='title'?'selected':''}>Titre A → Z</option></select><span>${items.length} idées</span></div>${ideaTags.length?`<div class="tagbar">${ideaTags.map(t=>`<button data-remove-project-idea-tag="${esc(t)}" class="tag active">${esc(t)} ×</button>`).join('')}</div>`:''}<div class="idea-list">${shown.map(i=>ideaCard(i)).join('')||'<div class="empty">Aucune idée dans cette sélection. Effacez les filtres ou ouvrez la bibliothèque commune pour retrouver toutes les idées.</div>'}</div>${shown.length<items.length?'<button id="moreProjectIdeas">Afficher 60 idées supplémentaires</button>':''}`);
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
  $('#researchFolderForm').onsubmit=e=>{e.preventDefault();run(async()=>{await changeResearch({action:f?'folder-rename':'folder-create',folder_id:f?.id,name:new FormData(e.target).get('name')});$('#modal').close();render()},e.submitter)};
}
renderFolders=function(){
  if(commonResearch)return researchOriginal.renderFolders();const r=researchOf(),f=r.folders.find(f=>f.id===researchFolder);
  shell(header('Organiser la recherche',f?esc(f.name):'Dossiers du livre','Une source ou une idée peut appartenir à plusieurs dossiers.','<button id="newResearchFolder" class="primary">Nouveau dossier</button>')+`<div class="research-folder-grid">${r.folders.map(f=>`<article class="panel"><h2>${esc(f.name)}</h2><p>${f.source_ids.length} sources · ${f.idea_ids.length} idées</p><div class="row"><button data-folder-open="${esc(f.id)}">Ouvrir</button><button data-folder-rename="${esc(f.id)}">Renommer</button><button data-folder-remove="${esc(f.id)}">Retirer le dossier</button></div></article>`).join('')||'<p>Créez un premier dossier pour regrouper vos sources et vos idées par thème.</p>'}</div>${f?`<section class="panel"><div class="row"><h2>${esc(f.name)}</h2><button id="folderAddSources">Ajouter des sources</button><button id="folderAddIdeas">Ajouter des idées</button></div><h3>Sources</h3><div class="source-grid">${state.sources.filter(s=>f.source_ids.includes(s.id)).map(card).join('')||'<p>Aucune source dans ce dossier.</p>'}</div><h3>Idées</h3><div class="idea-list">${state.ideas.filter(i=>f.idea_ids.includes(i.id)).map(i=>`<article><button data-folder-idea="${esc(i.id)}">${esc(i.title)}</button><button data-folder-classify-idea="${esc(i.id)}">Classer / notes</button></article>`).join('')||'<p>Aucune idée dans ce dossier.</p>'}</div></section>`:''}`);
  $('#newResearchFolder').onclick=()=>researchFolderModal();$$('[data-folder-open]').forEach(b=>b.onclick=()=>{researchFolder=b.dataset.folderOpen;renderFolders()});$$('[data-folder-rename]').forEach(b=>b.onclick=()=>researchFolderModal(r.folders.find(f=>f.id===b.dataset.folderRename)));
  $$('[data-folder-remove]').forEach(b=>b.onclick=()=>{showModal(`<h2>Retirer ce dossier ?</h2><p>Ses sources et ses idées resteront dans le livre.</p><div class="modal-actions"><button data-close>Annuler</button><button id="confirmResearchFolderRemove">Retirer le dossier</button></div>`);$('#confirmResearchFolderRemove').onclick=e=>run(async()=>{await changeResearch({action:'folder-delete',folder_id:b.dataset.folderRemove});researchFolder='';$('#modal').close();render()},e.currentTarget)});
  if(f){bindCards();$('#folderAddSources').onclick=()=>researchPicker('source_ids',f.id);$('#folderAddIdeas').onclick=()=>researchPicker('idea_ids',f.id);$$('[data-research-source]').forEach(b=>b.onclick=()=>classifyResearch('source_ids',[b.dataset.researchSource]));$$('[data-folder-idea]').forEach(b=>b.onclick=()=>run(async()=>ideaModal(await api('idea?id='+encodeURIComponent(b.dataset.folderIdea)))));$$('[data-folder-classify-idea]').forEach(b=>b.onclick=()=>classifyResearch('idea_ids',[b.dataset.folderClassifyIdea]))}
};
function researchPicker(key,fid=''){
  const choices=new Set(),items=key==='source_ids'?state.sources:state.ideas;let offset=0;
  showModal(`<h2>${key==='source_ids'?'Choisir des sources':'Choisir des idées'}</h2><p>Ajouter à « ${esc(state.book.title)} ». Les originaux restent réutilisables dans les autres livres.</p><input id="researchPickerQuery" type="search" placeholder="Rechercher par titre, auteur ou tag"><div class="row"><button id="researchPickerAll">Cocher les résultats affichés</button><span id="researchPickerCount"></span></div><div id="researchPickerItems" class="project-source-list"></div><div class="row"><button id="researchPickerPrev">Précédent</button><button id="researchPickerNext">Suivant</button></div><div class="modal-actions"><button data-close>Annuler</button><button id="researchPickerSave" class="primary">Ajouter au livre${fid?' et au dossier':''}</button></div>`);
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
  return `<section class="book-presentation" aria-label="Couverture et téléchargement"><button id="overviewCoverPreview" class="book-preview-cover" aria-label="${cover?'Modifier':'Ajouter'} la couverture">${cover?`<img src="${assetUrl(cover)}" alt="Couverture du livre">`:`${uiIcon('▧')}<span>Ajouter votre<br>photo de couverture</span>`}</button><div class="book-presentation-content"><h2>Votre livre, prêt à emporter</h2><p>${cover?'Votre couverture accompagnera le PDF et l’EPUB.':'Ajoutez une couverture en photo, puis téléchargez votre livre.'}</p><div class="book-access-buttons"><button id="overviewDownload" class="primary">${uiIcon('↓')} Télécharger le livre</button><button id="overviewCover">${cover?'Modifier la couverture':'Ajouter une couverture'}</button><button id="overviewImages">Images et schémas</button></div><small>PDF pour imprimer · EPUB pour lire · Texte pour retravailler</small></div></section>`;
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
