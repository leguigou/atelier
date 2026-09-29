"""Versioned public API for Atelier.

The HTTP transport and authentication live in server.py.  This module only
contains resource validation and dispatch so the browser application and the
machine API keep sharing the same data model.
"""
import json
import re
from urllib.parse import parse_qs


class ApiV1:
    def __init__(self, app):
        self.a = app

    def segments(self, data):
        if isinstance(data.get('text'), str):
            rows = []
            for line in data['text'].splitlines():
                if not line.strip():
                    continue
                match = re.match(r'^\[?(\d+:\d+(?::\d+)?)(?:[.,]\d+)?\]?\s+(.+)', line)
                rows.append(dict(start=self.a.seconds(match[1]) if match else 0,
                                 duration=0, text=match[2] if match else line.strip()))
        else:
            rows = data.get('segments')
            if not isinstance(rows, list):
                raise ValueError('Fournissez « text » ou « segments ».')
            clean = []
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('text'), str) or not row['text'].strip():
                    raise ValueError('Chaque segment doit contenir un texte non vide.')
                start = float(row.get('start', 0)); duration = float(row.get('duration', 0))
                if start < 0 or duration < 0:
                    raise ValueError('Les horodatages doivent être positifs.')
                item = dict(start=start, duration=duration, text=row['text'].strip())
                for key in ('page', 'section', 'speaker'):
                    if key in row: item[key] = row[key]
                clean.append(item)
            rows = clean
        if len(rows) > 200000 or sum(len(x['text']) for x in rows) > 5_000_000:
            raise ValueError('Transcription trop volumineuse.')
        return sorted(rows, key=lambda x: x['start'])

    def save_source(self, data, source=None):
        creating = source is None
        source = dict(source or {})
        for key, limit in (('title', 1000), ('author', 300)):
            if creating or key in data: source[key] = self.a.required(data, key, limit)
        allowed = ('url','date','kind','description','original_tags','chapters','status',
                   'automatic','language','provenance','views','youtube_id')
        for key in allowed:
            if key in data: source[key] = data[key]
        if 'url' in source: source['url'] = self.a.safe_url(str(source['url']))
        if 'segments' in data or 'text' in data: source['segments'] = self.segments(data)
        source.setdefault('id', data.get('id') or self.a.uid())
        source.setdefault('url', ''); source.setdefault('date', '')
        source.setdefault('kind', 'Vidéo' if source.get('youtube_id') else 'Document')
        source.setdefault('description', ''); source.setdefault('original_tags', [])
        source.setdefault('segments', []); source.setdefault('chapters', [])
        source.setdefault('status', 'Importée' if source['segments'] else 'Sans texte')
        source.setdefault('automatic', False); source.setdefault('language', '')
        source.setdefault('provenance', 'API'); source.setdefault('views', 0)
        source.setdefault('added_at', self.a.now())
        source['duration'] = max(float(source.get('duration', 0) or 0),
                                 max((x['start'] + x.get('duration', 0) for x in source['segments']), default=0))
        payload = self.a.dumps(source); text = ' '.join(x['text'] for x in source['segments'])
        with self.a.connect() as c:
            if creating:
                c.execute('INSERT INTO sources VALUES(?,?,?)', (source['id'], payload, text))
            else:
                c.execute('UPDATE sources SET payload=?,text=? WHERE id=?', (payload, text, source['id']))
        return self.a.get_source(source['id'])

    @staticmethod
    def page(items, query):
        try:
            limit = min(200, max(1, int(query.get('limit', ['50'])[0])))
            offset = max(0, int(query.get('offset', ['0'])[0]))
        except ValueError:
            raise ValueError('Pagination invalide.') from None
        return dict(items=items[offset:offset+limit], total=len(items), limit=limit, offset=offset)

    @staticmethod
    def boolean_filter(query, name):
        value=query.get(name, [''])[0].lower()
        if value == '': return None
        if value in ('true','1'): return True
        if value in ('false','0'): return False
        raise ValueError(f'Filtre {name} invalide : utilisez true ou false.')

    def source_list(self, query):
        q = query.get('q', [''])[0].casefold(); kind = query.get('kind', [''])[0]
        author = query.get('author', [''])[0]; transcript = query.get('has_transcript', [''])[0]
        liked=self.boolean_filter(query,'liked');archived=self.boolean_filter(query,'archived')
        with self.a.connect() as c:
            rows = c.execute('SELECT payload,text FROM sources').fetchall()
            out = []
            for row in rows:
                source = json.loads(row['payload']); segments = source.pop('segments', [])
                if q and q not in (source.get('title','')+' '+source.get('author','')+' '+row['text']).casefold(): continue
                if kind and source.get('kind') != kind: continue
                if author and source.get('author') != author: continue
                if transcript in ('true','1') and not segments: continue
                if transcript in ('false','0') and segments: continue
                source['segment_count'] = len(segments)
                source['annotation'] = self.a.annotation(c, source['id'])
                if liked is not None and bool(source['annotation'].get('liked')) != liked:continue
                if archived is not None and bool(source['annotation'].get('archived')) != archived:continue
                out.append(source)
        out.sort(key=lambda x: (x.get('date',''), x.get('added_at','')), reverse=True)
        return self.page(out, query)

    def transcript(self, sid, data=None, delete=False):
        source = self.a.get_source(sid); source.pop('annotation', None)
        source['segments'] = [] if delete else self.segments(data or {})
        source['status'] = 'Sans texte' if delete else str((data or {}).get('status', 'Texte ajouté via API'))[:100]
        if data and 'language' in data: source['language'] = str(data['language'])[:30]
        return self.save_source(source, source)

    def delete_source(self, sid, force=False):
        self.a.get_source(sid)
        with self.a.connect() as c:
            ideas = self.a.objects(c, 'ideas')
            referenced = [x for x in ideas if any(r.get('source_id') == sid for r in x.get('refs', []))]
            if referenced and not force:
                raise ValueError(f'Source utilisée par {len(referenced)} idée(s). Ajoutez ?force=true pour la supprimer et nettoyer les références.')
            for idea in referenced:
                idea['refs'] = [r for r in idea.get('refs', []) if r.get('source_id') != sid]
                if idea['refs']: c.execute('UPDATE ideas SET payload=? WHERE id=?', (self.a.dumps(idea), idea['id']))
                else: c.execute('DELETE FROM ideas WHERE id=?', (idea['id'],))
            c.execute('DELETE FROM annotations WHERE id=?', (sid,))
            if c.execute('DELETE FROM sources WHERE id=?', (sid,)).rowcount != 1: raise ValueError('Source introuvable.')
        return {'deleted': True, 'id': sid}

    def annotation(self, sid, data=None):
        self.a.get_source(sid)
        if data is None:
            with self.a.connect() as c: return self.a.annotation(c, sid)
        with self.a.connect() as c:
            item = self.a.annotation(c, sid)
            for key in ('liked','archived','tags','notes','state','folder','chapters'):
                if key in data:
                    if key in ('liked','archived') and not isinstance(data[key],bool):raise ValueError(f'{key} doit être un booléen.')
                    item[key] = data[key]
            c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)', (sid, self.a.dumps(item)))
        return item

    @staticmethod
    def apply_tags(existing, tags, mode):
        wanted={x.casefold() for x in tags}
        if mode == 'add':
            known={x.casefold() for x in existing}
            return [*existing,*[x for x in tags if x.casefold() not in known]][:50]
        if mode == 'remove':return [x for x in existing if x.casefold() not in wanted]
        return tags

    def batch_input(self, data, id_field):
        allowed={id_field,'ids','tags','mode','liked','archived'}
        unknown=sorted(set(data)-allowed)
        if unknown:raise ValueError('Champ(s) inconnu(s) : '+', '.join(unknown))
        raw_ids=data.get(id_field,data.get('ids',[]))
        if not isinstance(raw_ids,list):raise ValueError(f'{id_field} doit être une liste.')
        ids=list(dict.fromkeys(str(x) for x in raw_ids if str(x)))
        if not ids or len(ids)>200:raise ValueError('Sélectionnez entre 1 et 200 identifiants.')
        for key in ('liked','archived'):
            if key in data and not isinstance(data[key],bool):raise ValueError(f'{key} doit être un booléen.')
        has_tags='tags' in data
        mode=str(data.get('mode','add'))
        if mode not in ('add','remove','replace'):raise ValueError('Mode de classement invalide.')
        tags=[]
        if has_tags:
            if not isinstance(data['tags'],list) or len(data['tags'])>50:raise ValueError('tags doit contenir au maximum 50 éléments.')
            for value in data['tags']:
                tag=re.sub(r'\s+',' ',str(value)).strip()
                if not tag or len(tag)>80:raise ValueError('Chaque tag doit contenir entre 1 et 80 caractères.')
                if tag.casefold() not in {x.casefold() for x in tags}:tags.append(tag)
            if not tags and mode!='replace':raise ValueError('Ajoutez au moins un tag.')
        elif 'mode' in data:raise ValueError('Le champ mode nécessite tags.')
        if not has_tags and 'liked' not in data and 'archived' not in data:raise ValueError('Indiquez tags, liked ou archived.')
        return ids,tags,mode,has_tags

    def batch_sources(self, data):
        ids,tags,mode,has_tags=self.batch_input(data,'source_ids')
        updated=[]
        with self.a.connect() as c:
            known={r[0] for r in c.execute(f"SELECT id FROM sources WHERE id IN ({','.join('?' for _ in ids)})",ids)}
            missing=[sid for sid in ids if sid not in known]
            if missing:raise ValueError('Source(s) introuvable(s) : '+', '.join(missing))
            for sid in ids:
                item=self.a.annotation(c,sid)
                if has_tags:item['tags']=self.apply_tags(list(item.get('tags',[])),tags,mode)
                for key in ('liked','archived'):
                    if key in data:item[key]=data[key]
                c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)',(sid,self.a.dumps(item)))
                updated.append({'id':sid,'tags':item['tags'],'liked':item['liked'],'archived':item['archived']})
        return {'updated':updated,'count':len(updated),'mode':mode if has_tags else None}

    def batch_ideas(self, data):
        ids,tags,mode,has_tags=self.batch_input(data,'idea_ids')
        updated=[]
        with self.a.connect() as c:
            rows={r['id']:json.loads(r['payload']) for r in c.execute(f"SELECT id,payload FROM ideas WHERE id IN ({','.join('?' for _ in ids)})",ids)}
            missing=[iid for iid in ids if iid not in rows]
            if missing:raise ValueError('Idée(s) introuvable(s) : '+', '.join(missing))
            for iid in ids:
                item=rows[iid]
                if has_tags:item['tags']=self.apply_tags(list(item.get('tags',[])),tags,mode)
                for key in ('liked','archived'):
                    if key in data:item[key]=data[key]
                c.execute('UPDATE ideas SET payload=? WHERE id=?',(self.a.dumps(item),iid))
                updated.append({'id':iid,'tags':item.get('tags',[]),'liked':bool(item.get('liked')),'archived':bool(item.get('archived'))})
        return {'updated':updated,'count':len(updated),'mode':mode if has_tags else None}

    def tags(self):
        counts={}
        with self.a.connect() as c:
            for row in c.execute('SELECT payload FROM annotations'):
                for tag in json.loads(row[0]).get('tags',[]):counts[tag]=counts.get(tag,0)+1
        return [{'name':name,'count':count} for name,count in sorted(counts.items(),key=lambda x:(-x[1],x[0].casefold()))]

    def ideas(self, query):
        with self.a.connect() as c: items = self.a.objects(c, 'ideas')
        q = query.get('q', [''])[0].casefold()
        if q: items = [x for x in items if q in (x.get('title','')+' '+x.get('notes','')+' '+' '.join(x.get('tags',[]))).casefold()]
        liked=self.boolean_filter(query,'liked');archived=self.boolean_filter(query,'archived')
        if liked is not None:items=[x for x in items if bool(x.get('liked')) == liked]
        if archived is not None:items=[x for x in items if bool(x.get('archived')) == archived]
        return self.page(sorted(items, key=lambda x:x.get('created',''), reverse=True), query)

    def delete_idea(self, iid):
        with self.a.connect() as c:
            if c.execute('DELETE FROM ideas WHERE id=?', (iid,)).rowcount != 1: raise ValueError('Idée introuvable.')
        return {'deleted': True, 'id': iid}

    def folders(self):
        with self.a.connect() as c: return [dict(r) for r in c.execute('SELECT * FROM folders ORDER BY name')]

    def delete_folder(self, fid):
        with self.a.connect() as c:
            if c.execute('DELETE FROM folders WHERE id=?', (fid,)).rowcount != 1: raise ValueError('Dossier introuvable.')
            for table in ('annotations','ideas'):
                for row in c.execute(f'SELECT id,payload FROM {table}').fetchall():
                    item=json.loads(row['payload'])
                    if item.get('folder') == fid:
                        item['folder']=''; c.execute(f'UPDATE {table} SET payload=? WHERE id=?',(self.a.dumps(item),row['id']))
        return {'deleted': True, 'id': fid}

    def handle(self, handler, method, path, raw_query, data=None):
        """Return True when the route belongs to /api/v1."""
        if not path.startswith('/api/v1'): return False
        query = parse_qs(raw_query); tail = path[len('/api/v1'):].rstrip('/')
        if tail == '':
            return handler.reply({'name':'Atelier API','version':'1.0','openapi':'/api/openapi.json',
                                  'documentation':'/api','authentication':'Authorization: Bearer <token>'}) or True
        if tail == '/sources' and method == 'GET': return handler.reply(self.source_list(query)) or True
        if tail == '/sources' and method == 'POST': return handler.reply(self.save_source(data), 201) or True
        if tail == '/sources/youtube' and method == 'POST': return handler.reply(self.a.studio.youtube(data), 201) or True
        if tail == '/sources/tags' and method == 'POST': return handler.reply(self.a.update_source_tags(data.get('source_ids',data.get('ids',[])),data.get('tags',[]),str(data.get('mode','add')))) or True
        if tail == '/sources/batch' and method in ('PATCH','POST'):return handler.reply(self.batch_sources(data)) or True
        if tail == '/tags' and method == 'GET': return handler.reply({'items':self.tags()}) or True
        if tail == '/uploads' and method == 'POST': return False  # handled by the binary transport
        match = re.fullmatch(r'/sources/([^/]+)(?:/(transcript|annotation))?', tail)
        if match:
            sid, child = match.groups()
            if not child and method == 'GET': return handler.reply(self.a.get_source(sid)) or True
            if not child and method in ('PATCH','PUT'): return handler.reply(self.save_source(data, {k:v for k,v in self.a.get_source(sid).items() if k!='annotation'})) or True
            if not child and method == 'DELETE': return handler.reply(self.delete_source(sid, query.get('force',['false'])[0].lower() in ('1','true'))) or True
            if child == 'transcript' and method == 'GET':
                source=self.a.get_source(sid); fmt=query.get('format',['json'])[0]
                if fmt == 'text':
                    text='\n'.join(f"[{self.a.timestamp(x['start'])}] {x['text']}" for x in source['segments'])
                    return handler.reply(text, ctype='text/plain; charset=utf-8') or True
                return handler.reply({'source_id':sid,'language':source.get('language',''),'status':source.get('status',''),'segments':source['segments']}) or True
            if child == 'transcript' and method in ('POST','PUT','PATCH'): return handler.reply(self.transcript(sid, data)) or True
            if child == 'transcript' and method == 'DELETE': return handler.reply(self.transcript(sid, delete=True)) or True
            if child == 'annotation' and method == 'GET': return handler.reply(self.annotation(sid)) or True
            if child == 'annotation' and method in ('PUT','PATCH'): return handler.reply(self.annotation(sid, data)) or True
        if tail == '/ideas' and method == 'GET': return handler.reply(self.ideas(query)) or True
        if tail == '/ideas' and method == 'POST': return handler.reply(self.a.save_idea(data), 201) or True
        if tail == '/ideas/batch' and method in ('PATCH','POST'):return handler.reply(self.batch_ideas(data)) or True
        match = re.fullmatch(r'/ideas/([^/]+)', tail)
        if match:
            iid=match[1]
            with self.a.connect() as c: row=c.execute('SELECT payload FROM ideas WHERE id=?',(iid,)).fetchone()
            if method == 'DELETE': return handler.reply(self.delete_idea(iid)) or True
            if not row: raise ValueError('Idée introuvable.')
            item=json.loads(row[0])
            if method == 'GET': return handler.reply(item) or True
            if method in ('PUT','PATCH'): return handler.reply(self.a.save_idea({**item, **data, 'id':iid})) or True
        if tail == '/folders' and method == 'GET': return handler.reply({'items':self.folders()}) or True
        if tail == '/folders' and method == 'POST':
            name=self.a.required(data,'name',150); item={'id':self.a.uid(),'name':name}
            with self.a.connect() as c:c.execute('INSERT INTO folders VALUES(?,?)',(item['id'],name))
            return handler.reply(item,201) or True
        match=re.fullmatch(r'/folders/([^/]+)',tail)
        if match:
            fid=match[1]
            if method == 'DELETE': return handler.reply(self.delete_folder(fid)) or True
            if method in ('PATCH','PUT'):
                name=self.a.required(data,'name',150)
                with self.a.connect() as c:
                    if c.execute('UPDATE folders SET name=? WHERE id=?',(name,fid)).rowcount!=1:raise ValueError('Dossier introuvable.')
                return handler.reply({'id':fid,'name':name}) or True
        if tail == '/books' and method == 'GET': return handler.reply({'items':self.a.studio.books()}) or True
        if tail == '/books' and method == 'POST': return handler.reply(self.a.studio.create_book(data),201) or True
        match=re.fullmatch(r'/books/([^/]+)',tail)
        if match:
            bid=match[1]
            if method == 'GET': return handler.reply(self.a.studio.book(bid)) or True
            if method in ('PUT','PATCH'):
                current=self.a.studio.book(bid); candidate={**current,**data,'_book_id':bid}
                return handler.reply(self.a.studio.save_book(candidate,data.get('_label','API'))) or True
            if method == 'DELETE':
                if bid == 'book-main': raise ValueError('Le projet principal ne peut pas être supprimé.')
                with self.a.connect() as c:
                    c.execute('DELETE FROM book_versions WHERE book_id=?',(bid,))
                    if c.execute('DELETE FROM books WHERE id=?',(bid,)).rowcount!=1:raise ValueError('Projet introuvable.')
                return handler.reply({'deleted':True,'id':bid}) or True
        if tail == '/related' and method == 'GET': return handler.reply({'items':self.a.related()}) or True
        if tail == '/jobs' and method == 'GET': return handler.reply({'items':list(self.a.JOBS.values())}) or True
        if tail == '/analysis' and method == 'POST':
            if not self.a.SECRET: raise ValueError('Configurez la clé du fournisseur IA dans les paramètres.')
            ids=list(dict.fromkeys(data.get('source_ids',data.get('ids',[]))))
            if not ids or len(ids)>20: raise ValueError('Sélectionnez entre 1 et 20 sources.')
            for sid in ids:
                if not self.a.get_source(sid)['segments']:raise ValueError('Une source ne possède pas de texte.')
            with self.a.LOCK:
                if any(j['status'] in ('queued','running') for j in self.a.JOBS.values()):raise ValueError('Une analyse est déjà en cours.')
                job=dict(id=self.a.uid(),status='queued',total=len(ids),done=0,message='Préparation…',created=self.a.now(),sources=ids)
                self.a.JOBS[job['id']]=job;self.a.persist_job(job)
            self.a.threading.Thread(target=self.a.run_job,args=(job,ids),daemon=True).start()
            return handler.reply(job,202) or True
        return handler.reply({'error':'Route API v1 introuvable.'},404) or True
