"""Human and machine readable documentation for the public Atelier API."""
import html


def openapi_document():
    security=[{'bearerAuth':[]}]
    def op(summary, description='', body=False, created=False):
        item={'summary':summary,'description':description,'security':security,
              'responses':{'201' if created else '200':{'description':'Succès'},'400':{'description':'Requête invalide'},'401':{'description':'Jeton absent ou invalide'}}}
        if body:item['requestBody']={'required':True,'content':{'application/json':{'schema':{'type':'object'}}}}
        return item
    paths={
      '/api/v1':{'get':op('Décrire l’API','Point d’entrée léger avec les liens de documentation.')},
      '/api/v1/sources':{
        'get':op('Lister et rechercher les sources','Pagination avec limit/offset. Filtres : q, author, kind, has_transcript, liked et archived. Les transcriptions complètes sont accessibles sur la ressource dédiée.'),
        'post':op('Créer une source ou une vidéo','Champs requis : title et author. Accepte url, youtube_id, kind, date, description, language, text ou segments.',True,True)},
      '/api/v1/sources/youtube':{'post':op('Ajouter une vidéo YouTube','Corps : {"url":"https://…"}. Récupère les métadonnées et la transcription disponible.',True,True)},
      '/api/v1/sources/tags':{'post':op('Classer plusieurs sources par tags','Ajoute, retire ou remplace les tags de 1 à 200 sources. Corps : {"source_ids":["…"],"tags":["Vlog"],"mode":"add|remove|replace"}.',True)},
      '/api/v1/sources/batch':{'patch':op('Modifier plusieurs sources ou vidéos','Jusqu’à 200 ID. Permet de combiner tags, liked et archived dans une opération atomique.',True),'post':op('Modifier plusieurs sources ou vidéos','Alias de PATCH pour les clients ne prenant pas en charge PATCH.',True)},
      '/api/v1/tags':{'get':op('Lister les tags','Retourne les tags existants avec leur nombre de sources.')},
      '/api/v1/uploads':{'post':op('Importer un fichier','Corps binaire (application/octet-stream, 30 Mo max). Paramètres : name, title, author et source=0|1.')},
      '/api/v1/sources/{source_id}':{
        'get':op('Lire une source','Retourne toutes les métadonnées, la transcription et l’annotation.'),
        'patch':op('Modifier une source','Modifie les champs fournis. Accepte aussi text ou segments pour remplacer la transcription.',True),
        'put':op('Remplacer ou modifier une source','Même validation que PATCH.',True),
        'delete':op('Supprimer une source','Refuse une source référencée. Utiliser force=true pour nettoyer ses références.')},
      '/api/v1/sources/{source_id}/transcript':{
        'get':op('Lire une transcription','Retour JSON par défaut. Ajouter format=text pour un texte horodaté.'),
        'post':op('Ajouter une transcription','Corps : text, ou segments [{start,duration,text}].',True),
        'put':op('Remplacer une transcription','Corps : text, ou segments [{start,duration,text}].',True),
        'patch':op('Modifier une transcription','Remplace la transcription avec le contenu fourni.',True),
        'delete':op('Supprimer une transcription')},
      '/api/v1/sources/{source_id}/annotation':{
        'get':op('Lire les notes, le favori et l’état d’archivage d’une source'),
        'put':op('Enregistrer notes et classement','Champs : liked, archived, tags, notes, state, folder et chapters.',True),
        'patch':op('Modifier notes, favori ou archivage','Seuls les champs fournis sont modifiés. Exemple : {"liked":true,"archived":false}.',True)},
      '/api/v1/ideas':{
        'get':op('Lister et rechercher les idées','Pagination limit/offset, recherche q et filtres liked/archived.'),
        'post':op('Créer une idée sourcée','Requiert title et au moins une référence {source_id,start,end}.',True,True)},
      '/api/v1/ideas/batch':{'patch':op('Modifier plusieurs idées','Jusqu’à 200 ID. Permet de combiner tags, liked et archived dans une opération atomique.',True),'post':op('Modifier plusieurs idées','Alias de PATCH pour les clients ne prenant pas en charge PATCH.',True)},
      '/api/v1/ideas/{idea_id}':{
        'get':op('Lire une idée'),'put':op('Modifier une idée',body=True),'patch':op('Modifier une partie d’une idée',body=True),'delete':op('Supprimer une idée')},
      '/api/v1/folders':{'get':op('Lister les dossiers'),'post':op('Créer un dossier','Corps : {"name":"…"}.',True,True)},
      '/api/v1/folders/{folder_id}':{'put':op('Renommer un dossier',body=True),'patch':op('Renommer un dossier',body=True),'delete':op('Supprimer un dossier','Le contenu est conservé et simplement déclassé.')},
      '/api/v1/books':{'get':op('Lister les projets de livre'),'post':op('Créer un projet de livre','Corps : title et, facultativement, author.',True,True)},
      '/api/v1/books/{book_id}':{'get':op('Lire un livre'),'put':op('Enregistrer un livre',body=True),'patch':op('Modifier un livre','Fusionne les champs fournis et crée une version.',True),'delete':op('Supprimer un livre','Le livre principal book-main ne peut pas être supprimé.')},
      '/api/v1/related':{'get':op('Lister les rapprochements entre idées')},
      '/api/v1/jobs':{'get':op('Lister les travaux d’analyse IA')},
      '/api/v1/analysis':{'post':op('Lancer une analyse IA','Corps : {"source_ids":["…"]}, de 1 à 20 sources transcrites.',True)},
    }
    parameters={
      'SourceId':{'name':'source_id','in':'path','required':True,'schema':{'type':'string'}},
      'IdeaId':{'name':'idea_id','in':'path','required':True,'schema':{'type':'string'}},
      'FolderId':{'name':'folder_id','in':'path','required':True,'schema':{'type':'string'}},
      'BookId':{'name':'book_id','in':'path','required':True,'schema':{'type':'string'}}}
    schemas={
      'Segment':{'type':'object','required':['start','text'],'properties':{'start':{'type':'number','minimum':0},'duration':{'type':'number','minimum':0},'text':{'type':'string'},'speaker':{'type':'string'},'page':{'type':'integer'},'section':{'type':'string'}}},
      'TranscriptInput':{'type':'object','description':'Fournir text ou segments.','properties':{'text':{'type':'string','description':'Une ligne par segment, avec horodatage facultatif [mm:ss].'},'segments':{'type':'array','items':{'$ref':'#/components/schemas/Segment'}},'language':{'type':'string'},'status':{'type':'string'}},'anyOf':[{'required':['text']},{'required':['segments']}]},
      'SourceInput':{'type':'object','required':['title','author'],'properties':{'title':{'type':'string','maxLength':1000},'author':{'type':'string','maxLength':300},'url':{'type':'string','format':'uri'},'youtube_id':{'type':'string'},'kind':{'type':'string'},'date':{'type':'string'},'description':{'type':'string'},'language':{'type':'string'},'text':{'type':'string'},'segments':{'type':'array','items':{'$ref':'#/components/schemas/Segment'}}}},
      'AnnotationInput':{'type':'object','properties':{'liked':{'type':'boolean'},'archived':{'type':'boolean'},'tags':{'type':'array','items':{'type':'string'}},'notes':{'type':'string'},'state':{'type':'string'},'folder':{'type':'string'},'chapters':{'type':'array','items':{'type':'object'}}}},
      'SourceTagsInput':{'type':'object','additionalProperties':False,'required':['source_ids','tags'],'properties':{'source_ids':{'type':'array','minItems':1,'maxItems':200,'items':{'type':'string'}},'tags':{'type':'array','maxItems':50,'items':{'type':'string','minLength':1,'maxLength':80}},'mode':{'type':'string','enum':['add','remove','replace'],'default':'add'}}},
      'SourceBatchInput':{'type':'object','additionalProperties':False,'required':['source_ids'],'anyOf':[{'required':['tags']},{'required':['liked']},{'required':['archived']}],'properties':{'source_ids':{'type':'array','minItems':1,'maxItems':200,'items':{'type':'string'}},'tags':{'type':'array','maxItems':50,'items':{'type':'string','minLength':1,'maxLength':80}},'mode':{'type':'string','enum':['add','remove','replace'],'default':'add'},'liked':{'type':'boolean'},'archived':{'type':'boolean'}}},
      'Reference':{'type':'object','required':['source_id','start','end'],'properties':{'source_id':{'type':'string'},'start':{'type':'number','minimum':0},'end':{'type':'number','minimum':0},'quote':{'type':'string'}}},
      'IdeaInput':{'type':'object','additionalProperties':False,'required':['title','refs'],'properties':{'title':{'type':'string'},'notes':{'type':'string'},'nature':{'type':'string'},'importance':{'type':'string','enum':['Fondamentale','Opérationnelle','Contextuelle']},'tags':{'type':'array','items':{'type':'string'}},'status':{'type':'string'},'folder':{'type':'string'},'liked':{'type':'boolean'},'archived':{'type':'boolean'},'refs':{'type':'array','minItems':1,'items':{'$ref':'#/components/schemas/Reference'}}}},
      'IdeaBatchInput':{'type':'object','additionalProperties':False,'required':['idea_ids'],'anyOf':[{'required':['tags']},{'required':['liked']},{'required':['archived']}],'properties':{'idea_ids':{'type':'array','minItems':1,'maxItems':200,'items':{'type':'string'}},'tags':{'type':'array','maxItems':50,'items':{'type':'string','minLength':1,'maxLength':80}},'mode':{'type':'string','enum':['add','remove','replace'],'default':'add'},'liked':{'type':'boolean'},'archived':{'type':'boolean'}}},
      'FolderInput':{'type':'object','required':['name'],'properties':{'name':{'type':'string','maxLength':150}}},
      'BookInput':{'type':'object','required':['title'],'properties':{'title':{'type':'string'},'author':{'type':'string'},'subtitle':{'type':'string'},'brief':{'type':'object'},'source_ids':{'type':'array','items':{'type':'string'}},'chapters':{'type':'array','items':{'type':'object'}}}},
      'AnalysisInput':{'type':'object','required':['source_ids'],'properties':{'source_ids':{'type':'array','minItems':1,'maxItems':20,'items':{'type':'string'}}}},
      'YouTubeInput':{'type':'object','required':['url'],'properties':{'url':{'type':'string','format':'uri'}}}}
    for partial,base in (('SourcePatch','SourceInput'),('IdeaPatch','IdeaInput'),('BookPatch','BookInput')):
        schemas[partial]=dict(schemas[base]);schemas[partial].pop('required',None)
    for path,item in paths.items():
        for marker,ref in (('{source_id}','SourceId'),('{idea_id}','IdeaId'),('{folder_id}','FolderId'),('{book_id}','BookId')):
            if marker in path:
                for operation in item.values():operation.setdefault('parameters',[]).append({'$ref':'#/components/parameters/'+ref})
    pagination=[{'name':'limit','in':'query','description':'Nombre maximal de résultats (maximum 200). La valeur effective est renvoyée dans le champ limit.','schema':{'type':'integer','minimum':1,'maximum':200,'default':50}},{'name':'offset','in':'query','description':'Décalage du premier résultat.','schema':{'type':'integer','minimum':0,'default':0}}]
    for path in ('/api/v1/sources','/api/v1/ideas'):
        paths[path]['get'].setdefault('parameters',[]).extend(pagination)
        paths[path]['get']['parameters'].extend([{'name':'liked','in':'query','description':'Filtrer les favoris.','schema':{'type':'boolean'}},{'name':'archived','in':'query','description':'Filtrer le contenu archivé ou actif.','schema':{'type':'boolean'}}])
    body_schemas={
      ('/api/v1/sources','post'):'SourceInput',('/api/v1/sources/youtube','post'):'YouTubeInput',
      ('/api/v1/sources/tags','post'):'SourceTagsInput',
      ('/api/v1/sources/batch','post'):'SourceBatchInput',('/api/v1/sources/batch','patch'):'SourceBatchInput',
      ('/api/v1/sources/{source_id}','put'):'SourcePatch',('/api/v1/sources/{source_id}','patch'):'SourcePatch',
      ('/api/v1/sources/{source_id}/transcript','post'):'TranscriptInput',('/api/v1/sources/{source_id}/transcript','put'):'TranscriptInput',('/api/v1/sources/{source_id}/transcript','patch'):'TranscriptInput',
      ('/api/v1/sources/{source_id}/annotation','put'):'AnnotationInput',('/api/v1/sources/{source_id}/annotation','patch'):'AnnotationInput',
      ('/api/v1/ideas','post'):'IdeaInput',('/api/v1/ideas/{idea_id}','put'):'IdeaPatch',('/api/v1/ideas/{idea_id}','patch'):'IdeaPatch',
      ('/api/v1/ideas/batch','post'):'IdeaBatchInput',('/api/v1/ideas/batch','patch'):'IdeaBatchInput',
      ('/api/v1/folders','post'):'FolderInput',('/api/v1/folders/{folder_id}','put'):'FolderInput',('/api/v1/folders/{folder_id}','patch'):'FolderInput',
      ('/api/v1/books','post'):'BookInput',('/api/v1/books/{book_id}','put'):'BookPatch',('/api/v1/books/{book_id}','patch'):'BookPatch',('/api/v1/analysis','post'):'AnalysisInput'}
    for (path,method),schema in body_schemas.items():
        paths[path][method]['requestBody']['content']['application/json']['schema']={'$ref':'#/components/schemas/'+schema}
    return {'openapi':'3.1.0','info':{'title':'Atelier API','version':'1.0.0','description':'API REST pour administrer les sources, vidéos, transcriptions, annotations, idées, dossiers et livres de l’Atelier.'},
            'servers':[{'url':'/','description':'Serveur Atelier courant'}],
            'tags':[{'name':'sources'},{'name':'transcriptions'},{'name':'contenu'}],
            'paths':paths,'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'Atelier token'}},'parameters':parameters,'schemas':schemas}}


def api_documentation():
    endpoints=[
      ('Sources et vidéos','GET, POST','/api/v1/sources','Lister, rechercher et ajouter tout contenu.'),
      ('Vidéo YouTube','POST','/api/v1/sources/youtube','Ajouter une URL et récupérer ce que YouTube rend disponible.'),
      ('Une source','GET, PATCH, DELETE','/api/v1/sources/{id}','Lire, modifier ou supprimer métadonnées et contenu.'),
      ('Transcription','GET, POST, PUT, PATCH, DELETE','/api/v1/sources/{id}/transcript','Récupérer, ajouter, remplacer ou supprimer une transcription.'),
      ('Annotations','GET, PUT, PATCH','/api/v1/sources/{id}/annotation','Notes, tags, favori, état de lecture et dossier.'),
      ('Idées','GET, POST, PATCH, DELETE','/api/v1/ideas','Gérer les idées et leurs références horodatées.'),
      ('Dossiers','GET, POST, PATCH, DELETE','/api/v1/folders','Classer les sources et les idées.'),
      ('Livres','GET, POST, PATCH, DELETE','/api/v1/books','Gérer les projets, chapitres et blocs éditoriaux.'),
      ('Analyse IA','POST','/api/v1/analysis','Lancer une analyse de 1 à 20 sources.'),
      ('Travaux','GET','/api/v1/jobs','Suivre les analyses asynchrones.')]
    rows=''.join(f'<tr><td><strong>{html.escape(a)}</strong><small>{html.escape(d)}</small></td><td><code>{html.escape(m)}</code></td><td><code>{html.escape(p)}</code></td></tr>' for a,m,p,d in endpoints)
    return '''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Atelier API</title><style>
    :root{--ink:#253c33;--green:#355746;--paper:#fffefa;--line:#dde2d8;--muted:#6f766d}*{box-sizing:border-box}body{margin:0;background:#f4f5ef;color:var(--ink);font:15px system-ui,sans-serif}main{max-width:1050px;margin:auto;padding:55px 24px 90px}h1{font:46px Georgia,serif;margin:.2em 0}h2{font:27px Georgia,serif;margin-top:48px}.lead{font-size:19px;line-height:1.65;max-width:760px;color:var(--muted)}.badge{display:inline-block;background:#dfe8d8;padding:6px 10px;border-radius:5px;font-size:12px;letter-spacing:.08em}.card{background:var(--paper);border:1px solid var(--line);padding:23px;border-radius:10px;margin:20px 0}code,pre{font-family:ui-monospace,monospace}pre{overflow:auto;background:#20372e;color:#f7f3e8;padding:20px;border-radius:8px;line-height:1.55}table{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--line)}td,th{text-align:left;padding:15px;border-bottom:1px solid var(--line);vertical-align:top}td small{display:block;color:var(--muted);margin-top:5px}a{color:var(--green)}.links{display:flex;gap:12px;flex-wrap:wrap}.links a{padding:10px 14px;border:1px solid var(--green);border-radius:6px;text-decoration:none}@media(max-width:700px){h1{font-size:36px}table{display:block;overflow:auto}}
    </style></head><body><main><span class="badge">API REST · VERSION 1</span><h1>Faire travailler un agent avec l’Atelier.</h1><p class="lead">Cette API permet de lire et gérer les vidéos, documents, transcriptions, annotations, idées, dossiers et livres. Elle est décrite en OpenAPI pour qu’un agent puisse découvrir précisément chaque opération.</p><div class="links"><a href="/api/openapi.json">Schéma OpenAPI JSON</a><a href="/api/llms.txt">Résumé pour agents</a><a href="/">Retour à l’Atelier</a></div><h2>Authentification</h2><div class="card"><p>Créez un jeton dans <strong>Paramètres → Accès API</strong>. Le secret n’est affiché qu’une fois. Envoyez-le ensuite dans chaque requête :</p><pre>Authorization: Bearer atelier_VOTRE_JETON</pre><p>Exemple :</p><pre>curl -H "Authorization: Bearer atelier_VOTRE_JETON" \\
  "https://votre-domaine.example/api/v1/sources?has_transcript=true&amp;limit=20"</pre></div><h2>Capacités</h2><table><thead><tr><th>Ressource</th><th>Méthodes</th><th>Route</th></tr></thead><tbody>'''+rows+'''</tbody></table><h2>Formats de transcription</h2><div class="card"><p>Une transcription peut être envoyée comme texte horodaté :</p><pre>{
  "text": "[00:00] Introduction\\n[01:12] Premier sujet",
  "language": "fr"
}</pre><p>…ou comme segments structurés :</p><pre>{
  "segments": [
    {"start": 0, "duration": 4.2, "text": "Introduction"},
    {"start": 72, "duration": 8, "text": "Premier sujet"}
  ]
}</pre></div><h2>Règles utiles</h2><div class="card"><ul><li>Les listes utilisent <code>limit</code> (maximum 200) et <code>offset</code>.</li><li><code>GET /api/v1/sources?q=…</code> cherche dans titres, auteurs et transcriptions.</li><li>Les réponses et erreurs sont en JSON, sauf une transcription demandée avec <code>?format=text</code>.</li><li>Le serveur ne conserve jamais le jeton en clair. Sa dernière utilisation et son compteur sont visibles dans l’administration.</li></ul></div></main></body></html>'''
