/* Books are the entry point; shared research is linked into independent workspaces. */
let commonResearch=false, researchFolder='', researchIdeaSort='recent';
view='books';
const researchOf=()=>state.book.research||{source_ids:state.book.source_ids||[],idea_ids:[],folders:[],source_notes:{},idea_notes:{}};
const projectContext=()=>!commonResearch&&!['books','settings'].includes(view);
const researchOriginal={shell,render,navigate,filtered,renderLibrary,renderIdeas,renderFolders,renderReader,ideaModal,card,api,uploadFile,addArchiveTab};

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
function resetResearchFilters(){query='';author='';status='';kind='';folder='';scope='all';tagsSel=[];page=1;selected.clear();sourceSearchIds=null;sourceSearchPassages=null;clearTimeout(sourceSearchTimer);ideaQuery='';ideaMode='all';ideaFolder='';ideaTags=[];ideaVisibleLimit=60}
navigate=function(v){
  if(v==='common'){commonResearch=true;researchFolder='';resetResearchFilters();v='library'}
  else if(['overview','ideas','folders','book'].includes(v)&&commonResearch){commonResearch=false;researchFolder='';resetResearchFilters()}
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
  $('.project-switcher')?.remove();
  const nav=[['books','▤','Mes livres'],['overview','▤','Vue d’ensemble'],['folders','▱','Dossiers'],['library','▦','Sources'],['ideas','✧','Idées'],['book','▤','Manuscrit'],['common','▦','Bibliothèque commune'],['settings','⚙','Réglages']];
  $('.nav').innerHTML=nav.map(([v,i,l])=>`<button data-nav="${v}" class="${(v==='common'?commonResearch&&view==='library':v===view&&!(v==='library'&&commonResearch))?'active':''}"><span class="icon">${uiIcon(i)}</span>${l}</button>`).join('');
  $$('[data-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.nav==='library'&&commonResearch){commonResearch=false;resetResearchFilters()}navigate(b.dataset.nav)});
  $('.mobile-nav').innerHTML=[['books','▤','Livres'],['overview','▤','Projet'],['folders','▱','Dossiers'],['library','▦','Sources'],['book','▤','Écrire']].map(([v,i,l])=>`<button data-mobile-nav="${v}" class="${view===v?'active':''}">${uiIcon(i)}<small>${l}</small></button>`).join('');
  $$('[data-mobile-nav]').forEach(b=>b.onclick=()=>{if(b.dataset.mobileNav==='library'&&commonResearch){commonResearch=false;resetResearchFilters()}navigate(b.dataset.mobileNav)});
  const crumb=$('.crumb');if(crumb)crumb.textContent=view==='books'?'Mes livres':commonResearch?'Bibliothèque commune':state.book.title+' / '+(nav.find(n=>n[0]===view)?.[2]||'Lecture');
  if(view!=='books'&&view!=='settings'){
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
filtered=function(){const list=researchOriginal.filtered();return commonResearch?list:list.filter(s=>researchMatches(s,'source_ids'))};
function researchControls(key){return `<div class="row research-controls"><label>Dossier <select id="researchFolderFilter"><option value="">Tous les dossiers</option><option value="unfiled" ${researchFolder==='unfiled'?'selected':''}>À classer</option>${researchOf().folders.map(f=>`<option value="${esc(f.id)}" ${researchFolder===f.id?'selected':''}>${esc(f.name)}</option>`).join('')}</select></label><button id="pickResearch">Choisir dans la bibliothèque commune</button>${key==='source_ids'&&selected.size?'<button id="classifySelection">Classer la sélection</button>':''}</div>`}
function bindResearchControls(key){$('#researchFolderFilter').onchange=e=>{researchFolder=e.target.value;page=1;render()};$('#pickResearch').onclick=()=>researchPicker(key);$('#classifySelection')?.addEventListener('click',()=>classifyResearch('source_ids',[...selected].filter(id=>researchOf().source_ids.includes(id))))}
card=function(s){let html=researchOriginal.card(s);if(projectContext())html=html.replace('</article>',`<div class="research-item-tools"><span class="small">${researchOf().folders.filter(f=>f.source_ids.includes(s.id)).map(f=>esc(f.name)).join(' · ')||'À classer'}</span><button data-research-source="${esc(s.id)}">Classer / notes</button></div></article>`);else if(commonResearch)html=html.replace('</article>',`<div class="research-item-tools"><button data-link-source="${esc(s.id)}">${researchOf().source_ids.includes(s.id)?'Déjà dans ce livre · classer':'Ajouter à ce livre'}</button></div></article>`);return html};
renderLibrary=function(){
  if(!commonResearch)folder='';researchOriginal.renderLibrary();
  if(!commonResearch){$('.heading h1').textContent='Sources du livre';$('#folder')?.parentElement.querySelector('#folder')?.remove();$('#clearFolder')?.remove();$('#sync')?.remove();$('.stats').remove();$('.resultbar').before(document.createRange().createContextualFragment(researchControls('source_ids')));bindResearchControls('source_ids')}
  installResearchCollectionBar('library');
  if(!commonResearch&&scope==='archived'&&!filtered().length){
    const count=state.sources.filter(s=>s.annotation.archived).length;
    $('.source-grid').after(document.createRange().createContextualFragment(`<div class="notice">Ce livre n’a aucune archive correspondant aux filtres. La bibliothèque commune contient ${count} source(s) archivée(s). <button id="showCommonArchives">Voir toutes les archives</button></div>`));
    $('#showCommonArchives').onclick=()=>openResearchCollection('library',true,true);
  }
  $$('[data-research-source]').forEach(b=>b.onclick=()=>classifyResearch('source_ids',[b.dataset.researchSource]));
  $$('[data-link-source]').forEach(b=>b.onclick=()=>classifyResearch('source_ids',[b.dataset.linkSource]));
};
function bookIdeaPool(){
  const r=researchOf(),sources=new Set(r.source_ids),retained=new Set(r.idea_ids);
  return state.ideas.filter(i=>retained.has(i.id)||(i.refs||[]).some(ref=>sources.has(ref.source_id)));
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
  if(commonResearch){researchOriginal.renderIdeas();$('.heading h1').textContent='Idées de la bibliothèque commune';installResearchCollectionBar('ideas');return}
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
  if(attach&&bid===activeBookId){const item=result.source||result;if(item.id)await changeResearch({action:'add',[path==='idea'?'idea_ids':'source_ids']:[item.id]})}
  return result;
};
uploadFile=async function(file,meta={},asSource=true,onProgress=()=>{}){const bid=activeBookId,attach=asSource&&projectContext(),result=await researchOriginal.uploadFile(file,meta,asSource,onProgress);if(attach&&bid===activeBookId){const item=result.source||result;if(item.id)await changeResearch({action:'add',source_ids:[item.id]})}return result};

renderReader=function(){
  researchOriginal.renderReader();
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
