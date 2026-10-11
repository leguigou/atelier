/* CommonMark plus tables and strikethrough; raw HTML stays literal. */
const BookMarkdown=window.markdownit({html:false,breaks:false,linkify:false});
const renderBookImage=BookMarkdown.renderer.rules.image;
BookMarkdown.renderer.rules.image=(tokens,index,options,env,self)=>{
  const token=tokens[index];
  if(!/^\/api\/asset\?id=[a-zA-Z0-9_-]+(?:&preview=1)?$/.test(token.attrGet('src')||''))return `<span>${BookMarkdown.utils.escapeHtml(token.content||'Image')} (à importer dans la médiathèque)</span>`;
  return renderBookImage(tokens,index,options,env,self);
};
// Small editorial extensions, also implemented by the publication renderer.
BookMarkdown.inline.ruler.before('emphasis','editorial_styles',(state,silent)=>{
  const source=state.src.slice(state.pos),match=source.match(/^(\+\+|==|\^|~)([^\n]+?)\1/);
  if(!match||!match[2].trim()||((match[1]==='^'||match[1]==='~')&&(/\s/.test(match[2])||match[2].includes(match[1]))))return false;
  const tag={'++':'u','==':'mark','^':'sup','~':'sub'}[match[1]];
  if(!silent){state.push(tag+'_open',tag,1);const token=state.push('text','',0);token.content=match[2];state.push(tag+'_close',tag,-1)}
  state.pos+=match[0].length;return true;
});
const markdownExamples=[
  ['Titres','Structure','# Titre principal\n\n## Section\n\n### Sous-section\n\n#### Niveau 4\n\n##### Niveau 5\n\n###### Niveau 6'],
  ['Gras','Caractères','**Texte en gras**'],['Italique','Caractères','*Texte en italique*'],
  ['Gras et italique','Caractères','***Texte accentué***'],['Barré','Caractères','~~Texte barré~~'],
  ['Souligné · extension Atelier','Caractères','++Texte souligné++'],['Surligné · extension Atelier','Caractères','==Texte surligné=='],
  ['Exposant · extension Atelier','Caractères','Une surface de 12 m^2^.'],['Indice · extension Atelier','Caractères','La molécule H~2~O.'],
  ['Autres délimiteurs','Caractères','__Gras__ et _italique_ et ___gras italique___.'],
  ['Code dans une phrase','Caractères','`code ou mot littéral`'],
  ['Paragraphes','Paragraphes','Premier paragraphe.\n\nDeuxième paragraphe.'],
  ['Retour à la ligne','Paragraphes','Première ligne\\\nDeuxième ligne.'],
  ['Citation et retrait','Paragraphes','> Une citation en retrait.\n>\n> Un second paragraphe.\n>\n> > Une citation imbriquée.'],
  ['Liste à puces','Listes','- Premier élément\n- Deuxième élément\n  - Sous-élément\n  - Autre sous-élément'],
  ['Liste numérotée','Listes','1. Première étape\n2. Deuxième étape\n   1. Sous-étape'],
  ['Autres puces','Listes','* Première puce\n* Deuxième puce\n\n+ Autre liste\n+ Autre élément'],
  ['Séparateur','Structure','---'],
  ['Tableau aligné','Tableaux','| Élément | Description | Quantité |\n| :--- | :---: | ---: |\n| Exemple A | **Texte gras** | 12 |\n| Exemple B | *Texte italique* | 8 |'],
  ['Lien','Liens et images','[Texte du lien](https://example.org "Titre du lien")'],
  ['Lien par référence','Liens et images','[Un site][site]\n\n[site]: https://example.org "Titre du site"'],
  ['Adresse et courriel','Liens et images','<https://example.org>\n\n<contact@example.org>'],
  ['Image importée','Liens et images','![Description de l’image](/api/asset?id=IDENTIFIANT&preview=1 "Légende")'],
  ['Image cliquable','Liens et images','[![Description](/api/asset?id=IDENTIFIANT&preview=1)](https://example.org)'],
  ['Bloc de code','Code','```text\nTexte conservé tel quel.\n    Retrait conservé ici.\n```'],
  ['Code par indentation','Code','    Quatre espaces créent un bloc de code.'],
  ['Caractères littéraux','Caractères','\\*astérisques\\* et \\[crochets\\] ; barre de tableau : \\|'],
];
function markdownRender(text){return BookMarkdown.render(String(text||''))}
function markdownToolbar(){return `<div class="markdown-toolbar" role="group" aria-label="Format du texte">${[['bold','Gras'],['italic','Italique'],['strike','Barré'],['underline','Souligné'],['mark','Surligné'],['sup','Exposant'],['sub','Indice'],['title','Titre'],['quote','Citation'],['bullet','Liste'],['number','Numéros'],['table','Tableau'],['link','Lien'],['image','Image'],['break','Retour ligne'],['code','Code']].map(([id,label])=>`<button type="button" data-format="${id}">${label}</button>`).join('')}<button type="button" data-markdown-guide>Guide Markdown</button><button type="button" data-markdown-preview aria-expanded="false">Aperçu</button></div>`}
function insertMarkdown(editor,before,after='',placeholder='texte'){
  if(!editor)return;
  const start=editor.selectionStart,end=editor.selectionEnd,selected=editor.value.slice(start,end)||placeholder;
  editor.setRangeText(before+selected+after,start,end,'end');editor.focus();
  editor.setSelectionRange(start+before.length,start+before.length+selected.length);
  editor.dispatchEvent(new Event('input',{bubbles:true}));
}
function applyMarkdown(editor,format){
  const inline={bold:['**','**'],italic:['*','*'],strike:['~~','~~'],underline:['++','++'],mark:['==','=='],sup:['^','^'],sub:['~','~'],code:['`','`'],link:['[','](https://example.org)']};
  if(inline[format]){insertMarkdown(editor,...inline[format]);return}
  if(format==='image'){imageModal();return}
  if(format==='table'){insertMarkdown(editor,'\n\n'+markdownExamples.find(x=>x[0]==='Tableau aligné')[2]+'\n\n','','');return}
  if(format==='break'){insertMarkdown(editor,'\\\n','','');return}
  const start=editor.value.lastIndexOf('\n',editor.selectionStart-1)+1;
  const end=editor.value.indexOf('\n',editor.selectionEnd),stop=end<0?editor.value.length:end;
  const lines=editor.value.slice(start,stop).split('\n');
  const result=lines.map((line,n)=>(format==='title'?'## ':format==='quote'?'> ':format==='number'?`${n+1}. `:'- ')+line).join('\n');
  editor.setRangeText(result,start,stop,'select');editor.focus();editor.dispatchEvent(new Event('input',{bubbles:true}));
}
function installMarkdownTools(){
  for(const block of $$('.editor-block')){
    const editor=block.querySelector('textarea');if(!editor)continue;
    const preview=block.querySelector('.markdown-preview');
    block.querySelectorAll('[data-format]').forEach(button=>{button.onpointerdown=e=>e.preventDefault();button.onclick=()=>applyMarkdown(editor,button.dataset.format)});
    block.querySelector('[data-markdown-guide]').onclick=()=>markdownGuide(editor);
    block.querySelector('[data-markdown-preview]').onclick=e=>{preview.hidden=!preview.hidden;e.currentTarget.setAttribute('aria-expanded',String(!preview.hidden));preview.innerHTML=markdownRender(editor.value)};
    editor.addEventListener('input',()=>{if(!preview.hidden)preview.innerHTML=markdownRender(editor.value)});
    editor.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&!e.altKey&&['b','i'].includes(e.key.toLowerCase())){e.preventDefault();applyMarkdown(editor,e.key.toLowerCase()==='b'?'bold':'italic')}});
  }
}
function markdownGuide(editor=null){
  showModal(`<h2>Guide de mise en forme Markdown</h2><p>Choisissez un exemple pour voir son code et son résultat. Les codes s’utilisent dans les blocs de texte.</p><label>Exemple<select id="markdownExample">${markdownExamples.map(([name,group],i)=>`<option value="${i}">${group} · ${name}</option>`).join('')}</select></label><pre class="markdown-syntax"><code id="markdownCode"></code></pre><div id="markdownResult" class="markdown-body markdown-preview"></div><p class="small">Une ligne vide sépare les paragraphes. Deux espaces en fin de ligne ou une barre oblique inverse créent un retour à la ligne. Les retraits de listes utilisent des espaces ; quatre espaces hors liste créent du code.</p><p class="small">Pour les images, utilisez « Image » et la médiathèque. Remplacez IDENTIFIANT par l’identifiant d’un média importé. Les images externes ne sont pas chargées. L’alignement, l’alinéa et l’espacement se règlent dans la mise en page du livre. Souligné (++), surligné (==), exposant (^) et indice (~) sont des extensions Atelier ; exposants et indices s’écrivent sans espaces. Les couleurs libres, polices, notes de bas de page, cases à cocher et HTML ne sont pas pris en charge.</p><div class="modal-actions"><button data-close>Fermer</button><button id="insertMarkdownExample" class="primary">Insérer l’exemple</button></div>`);
  const update=()=>{const text=markdownExamples[Number($('#markdownExample').value)][2];$('#markdownCode').textContent=text;$('#markdownResult').innerHTML=markdownRender(text)};
  $('#markdownExample').onchange=update;update();
  $('#insertMarkdownExample').disabled=!editor&&!currentChapter();
  $('#insertMarkdownExample').onclick=()=>{const text=markdownExamples[Number($('#markdownExample').value)][2];$('#modal').close();if(editor&&editor.isConnected)insertMarkdown(editor,'\n\n'+text+'\n\n','','');else{const block={id:newId(),type:'text',text};currentChapter().blocks.push(block);changed('Exemple Markdown ajouté');renderBook()}};
}
const renderFormattingBook=renderBook;
renderBook=function(){renderFormattingBook();installMarkdownTools()};
