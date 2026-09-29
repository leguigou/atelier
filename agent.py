"""Persistent, source-grounded conversational agent for Atelier."""
import json, re, threading


MAX_TURNS = 24
MAX_TOOL_LOOPS = 8


def _row_thread(row):
    item=dict(row);item['messages']=json.loads(item.pop('messages'));item['actions']=json.loads(item.pop('actions'))
    return item


def list_threads(app):
    with app.connect() as c:rows=c.execute('SELECT * FROM agent_threads ORDER BY updated DESC').fetchall()
    return [{k:v for k,v in _row_thread(r).items() if k not in ('messages','actions')} for r in rows]


def get_thread(app, tid):
    with app.connect() as c:row=c.execute('SELECT * FROM agent_threads WHERE id=?',(tid,)).fetchone()
    if not row:raise ValueError('Conversation introuvable.')
    return _row_thread(row)


def save_thread(app, thread):
    thread['updated']=app.now()
    with app.connect() as c:
        c.execute('INSERT OR REPLACE INTO agent_threads(id,title,book_id,source_id,messages,actions,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                  (thread['id'],thread['title'],thread.get('book_id',''),thread.get('source_id',''),app.dumps(thread['messages']),app.dumps(thread['actions']),thread['created'],thread['updated']))


def create_thread(app, studio, data):
    book_id=str(data.get('book_id') or 'book-main');studio.book(book_id)
    source_id=str(data.get('source_id') or '')
    if source_id:app.get_source(source_id)
    stamp=app.now();thread=dict(id=app.uid(),title='Nouvelle conversation',book_id=book_id,source_id=source_id,messages=[],actions=[],created=stamp,updated=stamp)
    save_thread(app,thread);return thread


def _compact_source(app, source, query='', limit=18):
    terms=set(app.tokens(query));ranked=[]
    for n,seg in enumerate(source.get('segments',[])):
        score=len(terms.intersection(app.tokens(seg.get('text','')))) if terms else 0
        ranked.append((score,n,seg))
    if terms:ranked.sort(key=lambda x:(-x[0],x[1]))
    chosen=ranked[:limit]
    return dict(id=source['id'],title=source['title'],author=source['author'],kind=source.get('kind'),url=source.get('url',''),
                passages=[dict(start=x[2].get('start',0),end=x[2].get('start',0)+x[2].get('duration',0),locator=app.timestamp(x[2].get('start',0)),text=x[2].get('text','')[:1200]) for x in chosen])


def _search_sources(app, args):
    query=str(args.get('query','')).strip();limit=min(12,max(1,int(args.get('limit',6))))
    terms=set(app.tokens(query));items=[]
    with app.connect() as c:rows=c.execute('SELECT payload,text FROM sources').fetchall()
    for row in rows:
        s=json.loads(row['payload']);hay=s.get('title','')+' '+s.get('author','')+' '+row['text']
        score=sum(3 if t in (s.get('title','')+' '+s.get('author','')).lower() else 1 for t in terms if t in hay.lower())
        if query and not score:continue
        snippets=[]
        for seg in s.get('segments',[]):
            if not terms or terms.intersection(app.tokens(seg.get('text',''))):snippets.append(dict(locator=app.timestamp(seg.get('start',0)),text=seg.get('text','')[:420]))
            if len(snippets)>=3:break
        items.append((score,s, snippets))
    items.sort(key=lambda x:(-x[0],x[1].get('date','')),reverse=False)
    return [dict(id=s['id'],title=s['title'],author=s['author'],kind=s.get('kind'),date=s.get('date',''),passages=snippets) for _,s,snippets in items[:limit]]


def _read_source(app, args):
    source=app.get_source(str(args.get('source_id','')));query=str(args.get('query',''))
    return _compact_source(app,source,query,min(30,max(1,int(args.get('limit',18)))))


def _read_book(studio, args):
    book=studio.book(str(args.get('book_id') or 'book-main'))
    return dict(id=book['_book_id'],revision=book['_revision'],title=book['title'],brief=book.get('brief',{}),source_ids=book.get('source_ids',[]),
                chapters=[dict(id=c['id'],title=c['title'],purpose=c.get('purpose',''),text='\n\n'.join(b.get('text','') for b in c.get('blocks',[]) if b.get('type') in ('text','heading','quote'))[:6000],source_ids=list(dict.fromkeys(s for b in c.get('blocks',[]) for s in b.get('source_ids',[])))) for c in book['chapters']])


def _search_ideas(app, args):
    query=str(args.get('query','')).casefold();limit=min(20,max(1,int(args.get('limit',8))))
    with app.connect() as c:items=app.objects(c,'ideas')
    if query:items=[x for x in items if query in (x.get('title','')+' '+x.get('notes','')+' '+' '.join(x.get('tags',[]))).casefold()]
    return [{k:x.get(k) for k in ('id','title','nature','importance','notes','tags','refs')} for x in items[:limit]]


def _proposal(app, thread, name, args):
    specs={
      'propose_create_chapter':('create_chapter',{'title':str(args.get('title','')).strip()[:500],'purpose':str(args.get('purpose','')).strip()[:2500],'position':args.get('position')}),
      'propose_update_chapter':('update_chapter',{'chapter_id':str(args.get('chapter_id','')),'title':str(args.get('title','')).strip()[:500],'purpose':str(args.get('purpose','')).strip()[:2500]}),
      'propose_append_to_chapter':('append_to_chapter',{'chapter_id':str(args.get('chapter_id','')),'text':str(args.get('text','')).strip()[:50000],'source_ids':list(dict.fromkeys(str(x) for x in args.get('source_ids',[])))[:60]}),
      'propose_outline':('replace_outline',{'chapters':[dict(title=str(x.get('title','')).strip()[:500],purpose=str(x.get('purpose','')).strip()[:2500]) for x in args.get('chapters',[])[:40] if isinstance(x,dict)]}),
      'propose_tag_sources':('tag_sources',{'source_ids':list(dict.fromkeys(str(x) for x in args.get('source_ids',[])))[:200],'tags':[str(x).strip()[:80] for x in args.get('tags',[])[:50] if str(x).strip()],'mode':str(args.get('mode','add'))})}
    kind,payload=specs[name]
    if kind=='create_chapter' and not payload['title']:raise ValueError('Titre de chapitre requis.')
    if kind=='append_to_chapter' and not payload['text']:raise ValueError('Texte à ajouter requis.')
    if kind=='replace_outline' and not payload['chapters']:raise ValueError('Le plan proposé est vide.')
    if kind=='tag_sources' and (not payload['source_ids'] or not payload['tags']):raise ValueError('Sources et tags requis.')
    if kind=='tag_sources' and payload['mode'] not in ('add','remove','replace'):raise ValueError('Mode de classement invalide.')
    action=dict(id=app.uid(),kind=kind,args=payload,status='pending',book_id=thread['book_id'],created=app.now())
    thread['actions'].append(action)
    return {'action_id':action['id'],'status':'pending_confirmation','message':'Action préparée. L’utilisateur doit la valider dans le chat avant toute modification.'}


def execute_tool(app, studio, thread, name, args):
    if name=='search_sources':return _search_sources(app,args)
    if name=='read_source':return _read_source(app,args)
    if name=='read_book':return _read_book(studio,args)
    if name=='search_ideas':return _search_ideas(app,args)
    if name.startswith('propose_'):return _proposal(app,thread,name,args)
    raise ValueError('Outil agent inconnu : '+name)


def tool_definitions():
    obj=lambda properties,required=[]:{'type':'object','properties':properties,'required':required,'additionalProperties':False}
    string={'type':'string'};integer={'type':'integer'}
    return [
      {'type':'function','function':{'name':'search_sources','description':'Rechercher des vidéos, documents et passages dans toute la bibliothèque.','parameters':obj({'query':string,'limit':integer},['query'])}},
      {'type':'function','function':{'name':'read_source','description':'Lire des passages précis de la transcription d’une source ou vidéo.','parameters':obj({'source_id':string,'query':string,'limit':integer},['source_id'])}},
      {'type':'function','function':{'name':'read_book','description':'Lire le plan, les objectifs et le texte actuel du livre.','parameters':obj({'book_id':string})}},
      {'type':'function','function':{'name':'search_ideas','description':'Rechercher les idées sourcées de l’Atelier.','parameters':obj({'query':string,'limit':integer},['query'])}},
      {'type':'function','function':{'name':'propose_create_chapter','description':'Préparer la création d’un nouveau chapitre. Nécessite confirmation utilisateur.','parameters':obj({'title':string,'purpose':string,'position':integer},['title'])}},
      {'type':'function','function':{'name':'propose_update_chapter','description':'Préparer la modification du titre ou de l’objectif d’un chapitre.','parameters':obj({'chapter_id':string,'title':string,'purpose':string},['chapter_id'])}},
      {'type':'function','function':{'name':'propose_append_to_chapter','description':'Préparer l’ajout d’un texte sourcé à un chapitre. Nécessite confirmation utilisateur.','parameters':obj({'chapter_id':string,'text':string,'source_ids':{'type':'array','items':string}},['chapter_id','text'])}},
      {'type':'function','function':{'name':'propose_outline','description':'Préparer le remplacement du plan complet. À utiliser seulement si l’utilisateur demande explicitement un nouveau plan ou une refonte.','parameters':obj({'chapters':{'type':'array','items':obj({'title':string,'purpose':string},['title'])}},['chapters'])}},
      {'type':'function','function':{'name':'propose_tag_sources','description':'Préparer l’ajout, le retrait ou le remplacement de tags sur des vidéos ou documents. Nécessite confirmation utilisateur.','parameters':obj({'source_ids':{'type':'array','items':string},'tags':{'type':'array','items':string},'mode':{'type':'string','enum':['add','remove','replace']}},['source_ids','tags'])}}
    ]


def _system_prompt(app, thread):
    return (app.prompt_text('assistant') +
            f"\nContexte courant : livre {thread['book_id']} ; source affichée {thread.get('source_id') or 'aucune'}.")


def run_job(app, studio, jobs, job):
    try:
        job.update(status='running',stage='thinking',message='Lecture de la demande…',progress=10,updated=app.now());persist_job(app,job)
        thread=get_thread(app,job['thread_id']);cfg=app.settings()
        if cfg.get('provider')=='anthropic':raise ValueError('L’agent outillé nécessite actuellement DeepSeek ou une API compatible OpenAI.')
        history=[{'role':m['role'],'content':m['content']} for m in thread['messages'][-MAX_TURNS:]]
        messages=[{'role':'system','content':_system_prompt(app, thread)},*history];trace=[]
        for turn in range(MAX_TOOL_LOOPS):
            job.update(stage='tools' if turn else 'thinking',message='Consultation de l’Atelier…' if turn else 'Réflexion et choix des outils…',progress=min(80,20+turn*10),updated=app.now());persist_job(app,job)
            payload=dict(model=cfg['model'],messages=messages,tools=tool_definitions(),tool_choice='auto',max_tokens=8000)
            if cfg.get('provider')=='deepseek':payload['reasoning_effort']='none'
            response=app.llm_request('/chat/completions',payload);choices=response.get('choices') or []
            if not choices:raise ValueError('Le modèle n’a renvoyé aucune réponse.')
            message=choices[0].get('message') or {};calls=message.get('tool_calls') or []
            if calls:
                messages.append({'role':'assistant','content':message.get('content') or '', 'tool_calls':calls})
                for call in calls:
                    fn=(call.get('function') or {}).get('name','');raw=(call.get('function') or {}).get('arguments','{}')
                    args={}
                    try:args=json.loads(raw);result=execute_tool(app,studio,thread,fn,args);ok=True
                    except Exception as e:result={'error':str(e)};ok=False
                    trace.append({'tool':fn,'args':args,'ok':ok,'summary':('Action préparée' if fn.startswith('propose_') and ok else 'Consulté' if ok else str(result.get('error','Erreur')))})
                    messages.append({'role':'tool','tool_call_id':call.get('id',''),'content':app.dumps(result)[:50000]})
                save_thread(app,thread);continue
            content=str(message.get('content') or '').strip()
            if not content:raise ValueError('Le modèle a renvoyé une réponse vide.')
            thread['messages'].append(dict(id=app.uid(),role='assistant',content=content,created=app.now(),trace=trace))
            save_thread(app,thread)
            job.update(status='finished',stage='finished',message='Réponse prête.',progress=100,updated=app.now(),finished=app.now());persist_job(app,job);return
        raise ValueError('L’agent a dépassé le nombre maximal d’étapes. Reformulez la demande plus précisément.')
    except Exception as e:
        message=str(e)[:1200];job.update(status='failed',stage='failed',message=message,error=message,progress=100,updated=app.now(),finished=app.now());persist_job(app,job)


def persist_job(app, job):
    with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('agent-job:'+job['id'],app.dumps(job)))


def start(app, studio, jobs, data):
    text=app.required(data,'message',12000);tid=str(data.get('thread_id') or '')
    thread=get_thread(app,tid) if tid else create_thread(app,studio,data)
    if data.get('book_id'):
        studio.book(str(data['book_id']));thread['book_id']=str(data['book_id'])
    if 'source_id' in data:
        source_id=str(data.get('source_id') or '')
        if source_id:app.get_source(source_id)
        thread['source_id']=source_id
    if any(j.get('thread_id')==thread['id'] and j.get('status') in ('queued','running') for j in jobs.values()):raise ValueError('Cet agent traite déjà un message.')
    if thread['title']=='Nouvelle conversation':thread['title']=re.sub(r'\s+',' ',text).strip()[:80]
    thread['messages'].append(dict(id=app.uid(),role='user',content=text,created=app.now()));save_thread(app,thread)
    job=dict(id=app.uid(),thread_id=thread['id'],status='queued',stage='queued',message='Mise en file…',progress=0,created=app.now(),updated=app.now());jobs[job['id']]=job;persist_job(app,job)
    threading.Thread(target=run_job,args=(app,studio,jobs,job),daemon=True).start()
    return dict(job=job,thread=thread)


def apply_action(app, studio, thread_id, action_id, approve=True):
    thread=get_thread(app,thread_id);action=next((x for x in thread['actions'] if x['id']==action_id),None)
    if not action:raise ValueError('Action introuvable.')
    if action['status']!='pending':raise ValueError('Cette action a déjà été traitée.')
    if not approve:action.update(status='rejected',decided=app.now());save_thread(app,thread);return action
    args=action['args'];kind=action['kind']
    if kind=='tag_sources':
        result=app.update_source_tags(args['source_ids'],args['tags'],args.get('mode','add'))
        action.update(status='applied',decided=app.now());save_thread(app,thread)
        return dict(action=action,tags=result)
    book=studio.book(action['book_id'])
    if kind=='create_chapter':
        chapter=dict(id=app.uid(),title=app.required(args,'title',500),purpose=str(args.get('purpose',''))[:2500],ideas=[],blocks=[]);position=args.get('position')
        if type(position) is int:book['chapters'].insert(max(0,min(position,len(book['chapters']))),chapter)
        else:book['chapters'].append(chapter)
    elif kind=='update_chapter':
        chapter=next((x for x in book['chapters'] if x['id']==args['chapter_id']),None)
        if not chapter:raise ValueError('Chapitre introuvable.')
        if args.get('title'):chapter['title']=args['title']
        if args.get('purpose'):chapter['purpose']=args['purpose']
    elif kind=='append_to_chapter':
        chapter=next((x for x in book['chapters'] if x['id']==args['chapter_id']),None)
        if not chapter:raise ValueError('Chapitre introuvable.')
        source_ids=[]
        for sid in args.get('source_ids',[]):app.get_source(sid);source_ids.append(sid)
        book['source_ids']=list(dict.fromkeys([*book.get('source_ids',[]),*source_ids]))[:60]
        chapter['blocks'].append(dict(id=app.uid(),type='text',text=app.required(args,'text',50000),source_ids=source_ids))
    elif kind=='replace_outline':
        book['chapters']=[dict(id=app.uid(),title=app.required(x,'title',500),purpose=str(x.get('purpose',''))[:2500],ideas=[],blocks=[]) for x in args['chapters']]
    else:raise ValueError('Action non prise en charge.')
    saved=studio.save_book(book,'Assistant IA · '+kind.replace('_',' '));action.update(status='applied',decided=app.now(),revision=saved['_revision']);save_thread(app,thread)
    return dict(action=action,book=saved)
