/* Backup/recovery and passage search share the existing navigation. */
SETTINGS_TABS.push(['sauvegardes','Sauvegardes']);
let latestRestoreResult=null;
const shellWithSafety=shell;
shell=function(content){
  shellWithSafety(content);
  if($('#backup')){$('#backup').textContent='Sauvegarder / restaurer';$('#backup').onclick=()=>{navigate('settings');settingsTabClick('sauvegardes')}}
  if(view==='settings'){
    const panel=document.createElement('section');panel.id='tab-sauvegardes';panel.className='settings-tab'+(settingsTab==='sauvegardes'?' active':'');
    panel.innerHTML=`<div class="panel"><h2>Sauvegarder votre Atelier</h2><p>Une seule archive contient tous les livres, leurs versions, les sources, idées, annotations, conversations, photos et documents originaux.</p><button class="primary" id="downloadBackup">Télécharger la sauvegarde complète</button><p class="small">Les identifiants de connexion et les clés API restent propres à votre installation. Archive : 256 Mo maximum ; contenu décompressé : 512 Mo.</p></div><div class="panel"><h2>Restaurer une sauvegarde</h2><p>Choisissez une archive Atelier. Son contenu sera vérifié et présenté avant de remplacer vos données. Une sauvegarde de sécurité de l’état actuel sera conservée sur le serveur.</p><label>Archive de sauvegarde<input id="restoreArchive" type="file" accept=".zip,application/zip"></label><p id="restoreStatus" role="status"></p><div id="restorePreview"></div></div>`;
    $('.settings').append(panel);
    $('#downloadBackup').onclick=e=>run(async()=>{await persistDraft();await downloadFullBackup();toast('Sauvegarde complète téléchargée.')},e.currentTarget);
    $('#restoreArchive').onchange=e=>run(async()=>{
      latestRestoreResult=null;
      const file=e.target.files[0];$('#restorePreview').replaceChildren();if(!file)return;
      if(file.size>256*1024*1024)throw Error('Archive limitée à 256 Mo.');
      $('#restoreStatus').textContent='Vérification de la sauvegarde…';
      try{
        const summary=await backupRequest('backup-inspect',file);
        if($('#restoreArchive')?.files[0]!==file)return;
        $('#restoreStatus').textContent='Sauvegarde vérifiée.';
        $('#restorePreview').innerHTML=`<p>Du ${esc(fullDate(summary.created))} : <strong>${summary.books} livre(s), ${summary.sources} source(s), ${summary.ideas} idée(s), ${summary.assets} fichier(s)</strong>.</p><label class="restore-agreement"><input id="restoreAgreement" type="checkbox"> Je souhaite remplacer les données actuelles par cette sauvegarde.</label><button id="confirmBackupRestore" class="primary" disabled>Restaurer cette sauvegarde</button>`;
        $('#restoreAgreement').onchange=e=>$('#confirmBackupRestore').disabled=!e.target.checked;
        $('#confirmBackupRestore').onclick=e=>run(async()=>{
          await persistDraft();const result=await backupRequest('backup-restore',file,true);
          bookDraft=null;bookDirty=false;bookConflict=false;rememberBook('book-main');sourceSearchIds=null;sourceSearchPassages=null;query='';selected.clear();current=null;
          latestRestoreResult=result;
          await reload();renderSettings();settingsTabClick('sauvegardes');
          toast('Livres, sources et fichiers restaurés.');
        },e.currentTarget);
      }catch(err){if($('#restoreStatus'))$('#restoreStatus').textContent=err.message;throw err}
    });
    if(latestRestoreResult){
      $('#restoreStatus').textContent='Restauration terminée. Votre état précédent est conservé sur le serveur.';
      const link=document.createElement('a');link.className='button-link';link.href='/api/safety-backup?name='+encodeURIComponent(latestRestoreResult.safety_backup);link.textContent='Télécharger la sauvegarde avant restauration';$('#restorePreview').append(link);
    }
  }
};
async function downloadFullBackup(){
  const response=await fetch('/api/backup.zip');
  if(!response.ok){if(response.status===401)renderLogin();const result=await response.json();throw Error(result.error||'Sauvegarde impossible.')}
  download('atelier-sauvegarde-'+new Date().toISOString().slice(0,10)+'.zip',await response.blob(),'application/zip');
}
async function backupRequest(route,file,restore=false){
  const response=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/zip',...(restore?{'X-Atelier-Restore':'replace'}:{})},body:file});
  const result=await response.json();if(response.status===401)renderLogin();if(!response.ok)throw Error(result.error||'Restauration impossible.');return result;
}

const libraryWithPassages=renderLibrary;
renderLibrary=function(){libraryWithPassages();renderPassageResults()};
function renderPassageResults(){
  if(!query.trim()||!sourceSearchPassages||sourceSearchPassages.query!==query)return;
  const allowed=new Set(filtered().map(s=>s.id));
  const items=sourceSearchPassages.items.filter(item=>allowed.has(item.source_id));
  const panel=document.createElement('section');panel.className='panel passage-results';panel.setAttribute('aria-label','Passages trouvés');
  panel.innerHTML=`<h2>Passages trouvés</h2><p class="small">Les mots recherchés peuvent apparaître dans un ordre différent. Cliquez sur un extrait pour ouvrir son emplacement.</p>${items.map((item,index)=>`<button class="passage-result" data-passage="${index}"><span><strong>${esc(item.title)}</strong><small>${esc(item.author)} · ${esc(item.page?'p. '+item.page:item.section||(['Vidéo','Short'].includes(item.kind)?time(item.start):'Passage '+(item.segment_index+1)))}</small></span><p>${esc(item.excerpt)}</p></button>`).join('')||'<p class="small">Aucun extrait correspondant aux filtres dans les résultats chargés.</p>'}${sourceSearchPassages.items.length<sourceSearchPassages.total?'<button id="morePassages">Charger plus de passages</button>':''}`;
  $('.source-grid')?.before(panel);
  panel.querySelectorAll('[data-passage]').forEach(button=>button.onclick=()=>openPassage(items[Number(button.dataset.passage)]));
  $('#morePassages')?.addEventListener('click',e=>run(async()=>{
    const searched=query,result=await api('passages?q='+encodeURIComponent(searched)+'&offset='+sourceSearchPassages.items.length);
    if(query!==searched||sourceSearchPassages?.query!==searched)return;
    sourceSearchPassages.items.push(...result.items);sourceSearchPassages.total=result.total;renderLibrary();
  },e.currentTarget));
}
async function openPassage(item){
  await openSource(item.source_id,item.start);
  if(current?.id!==item.source_id)return;
  const candidates=$$('[id^="seg-"]').filter(el=>Number(el.id.slice(4))<=item.segment_index);
  const target=candidates.at(-1);if(target){target.classList.add('search-hit');target.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
}
