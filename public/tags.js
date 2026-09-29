/* Bulk source classification by reusable tags. */
const tagPresets=['Vlog','Entretien','Facecam','Tutoriel','Coulisses','Témoignage','Podcast','Étude de cas','Short'];
const renderLibraryBeforeTags=renderLibrary;
renderLibrary=function(){
  renderLibraryBeforeTags();
  const actions=document.querySelector('.resultbar .row');
  if(!actions||!selected.size)return;
  const button=document.createElement('button');button.id='batchTags';button.innerHTML='🏷 Classer par tags';
  button.onclick=tagBatchModal;actions.prepend(button);
};

function tagBatchModal(){
  const existing=[...new Set(state.sources.flatMap(s=>s.annotation.tags||[]))].sort((a,b)=>a.localeCompare(b,'fr'));
  const choices=[...new Set([...tagPresets,...existing])];
  showModal(`<form id="tagBatchForm"><div class="eyebrow">CLASSEMENT</div><h2>Classer ${selected.size} source${selected.size>1?'s':''}</h2><p class="sub">Choisissez un ou plusieurs tags. Vous pourrez ensuite les utiliser comme filtre dans la bibliothèque.</p><div class="tag-choices">${choices.map(t=>`<label><input type="checkbox" name="tag" value="${esc(t)}"><span>${esc(t)}</span></label>`).join('')}</div><label for="newTags">Autres tags · séparés par une virgule</label><input id="newTags" name="new_tags" placeholder="Interview client, Stratégie, Acquisition…"><label for="tagMode">Action</label><select id="tagMode" name="mode"><option value="add">Ajouter aux tags existants</option><option value="remove">Retirer ces tags</option><option value="replace">Remplacer tous les tags</option></select><p class="small tag-warning" hidden>Le remplacement efface les autres tags des sources sélectionnées.</p><div class="modal-actions"><button type="button" data-close>Annuler</button><button class="primary" type="submit">Appliquer</button></div></form>`);
  const form=$('#tagBatchForm'),mode=$('#tagMode');mode.onchange=()=>$('.tag-warning').hidden=mode.value!=='replace';
  form.onsubmit=e=>{e.preventDefault();run(async()=>{const data=new FormData(form),tags=[...data.getAll('tag'),...String(data.get('new_tags')||'').split(',')].map(x=>x.trim()).filter(Boolean);if(!tags.length&&data.get('mode')!=='replace')throw Error('Choisissez au moins un tag.');const result=await api('source-tags',{ids:[...selected],tags,mode:data.get('mode')});await reload();selected.clear();$('#modal').close();renderLibrary();toast(`${result.count} source${result.count>1?'s':''} classée${result.count>1?'s':''}.`)},e.submitter)};
}
