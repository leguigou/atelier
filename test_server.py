import unittest, tempfile, json, threading, urllib.request, urllib.error, hashlib
from pathlib import Path
from unittest.mock import patch
import server as app
from io import BytesIO

class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        app.DB=Path(cls.tmp.name)/'test.sqlite'
        app.JOBS.clear(); app.SECRET=''; app.VAULT_KEY=''
        app.init()
        cls.http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        app.PORT=cls.http.server_address[1]
        app.APP_URL=f'http://127.0.0.1:{app.PORT}'
        cls.base=app.APP_URL
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.tmp.cleanup()
    def setUp(self): app.PASSWORD_HASH=b''
    def call(self,route,data=None,headers=None):
        h={'Content-Type':'application/json',**(headers or {})}
        req=urllib.request.Request(self.base+route,data=json.dumps(data).encode() if data is not None else None,headers=h)
        try:
            with urllib.request.urlopen(req) as r: return r.status,r.headers,r.read()
        except urllib.error.HTTPError as e: return e.code,e.headers,e.read()
    def call_method(self,method,route,data=None,headers=None):
        h={'Content-Type':'application/json',**(headers or {})}
        body=json.dumps(data).encode() if data is not None else None
        req=urllib.request.Request(self.base+route,data=body,headers=h,method=method)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.headers,r.read()
        except urllib.error.HTTPError as e:return e.code,e.headers,e.read()
    def backup_bytes(self):
        captured=[]
        body=app.application({'REQUEST_METHOD':'GET','PATH_INFO':'/api/backup','HTTP_HOST':f'127.0.0.1:{app.PORT}','wsgi.input':BytesIO()},lambda status,headers:captured.append(status))
        self.assertEqual(captured[0],'200 OK')
        return b''.join(body)
    def test_catalog_and_idempotent_import(self):
        before=app.library();app.sync();after=app.library()
        self.assertEqual(len(before['sources']),269)
        self.assertEqual(len(after['sources']),269)
        self.assertEqual(sum(s['segment_count']>0 for s in after['sources']),69)
        self.assertEqual(len(after['ideas']),18)
    def test_compact_library_omits_heavy_text_and_search_stays_available(self):
        compact=app.compact_library()
        self.assertNotIn('search_text',compact['sources'][0])
        self.assertTrue(all('quote' not in ref for idea in compact['ideas'] for ref in idea.get('refs',[])))
        self.assertIn('dQTr8VInXUE',app.search_source_ids('9 etapes'))
    def test_auth_blocks_private_reads_and_writes(self):
        app.PASSWORD_HASH=hashlib.scrypt(b'correct-password-for-test',salt=app.PASSWORD_SALT,n=16384,r=8,p=1)
        self.assertEqual(self.call('/api/library')[0],401)
        self.assertEqual(self.call('/api/backup')[0],401)
        self.assertEqual(self.call('/api/folder',{'name':'denied'})[0],401)
        status,headers,_=self.call('/api/login',{'password':'correct-password-for-test'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertEqual(self.call('/api/library',headers={'Cookie':cookie})[0],200)
        self.assertEqual(self.call('/api/logout',{},headers={'Cookie':cookie})[0],200)
        self.assertEqual(self.call('/api/library',headers={'Cookie':cookie})[0],401)
        app.PASSWORD_HASH=b''
    def test_auth_rate_limit(self):
        app.PASSWORD_HASH=b'test'
        with app.connect() as c:c.execute('DELETE FROM attempts')
        for _ in range(10):self.assertEqual(self.call('/api/login',{'password':'wrong'})[0],401)
        self.assertEqual(self.call('/api/login',{'password':'wrong'})[0],429)
        with app.connect() as c:c.execute('DELETE FROM attempts')
        app.PASSWORD_HASH=b''
    def test_password_change_persists_and_revokes_sessions(self):
        old_salt,old_hash=app.PASSWORD_SALT,app.PASSWORD_HASH
        old='old-password-for-tests';new='abcdef'
        app.PASSWORD_HASH=hashlib.scrypt(old.encode(),salt=app.PASSWORD_SALT,n=16384,r=8,p=1)
        with app.connect() as c:c.execute('DELETE FROM attempts')
        try:
            data=dict(current_password=old,new_password=new,confirmation=new)
            self.assertEqual(self.call('/api/password',data)[0],401)
            _,h,_=self.call('/api/login',{'password':old});cookie={'Cookie':h['Set-Cookie'].split(';')[0]}
            _,h2,_=self.call('/api/login',{'password':old});cookie2={'Cookie':h2['Set-Cookie'].split(';')[0]}
            self.assertEqual(self.call('/api/password',{**data,'current_password':'wrong'},cookie)[0],400)
            self.assertEqual(self.call('/api/password',{**data,'confirmation':'different'},cookie)[0],400)
            self.assertEqual(self.call('/api/password',{**data,'new_password':'short','confirmation':'short'},cookie)[0],400)
            self.assertEqual(self.call('/api/password',data,{**cookie,'Origin':'https://attacker.invalid'})[0],400)
            self.assertEqual(self.call('/api/password',data,cookie)[0],200)
            self.assertEqual(self.call('/api/library',headers=cookie)[0],401)
            self.assertEqual(self.call('/api/library',headers=cookie2)[0],401)
            app.PASSWORD_HASH=b'';app.load_password()
            self.assertEqual(self.call('/api/login',{'password':old})[0],401)
            self.assertEqual(self.call('/api/login',{'password':new})[0],200)
            with app.connect() as c: stored=dict(c.execute('SELECT * FROM authentication').fetchone())
            self.assertNotIn(new,json.dumps(stored))
            digest=stored['digest'];app.PASSWORD_HASH=b''
            self.assertNotIn(digest.encode(),self.backup_bytes())
        finally:
            with app.connect() as c:
                c.execute('DELETE FROM authentication');c.execute('DELETE FROM attempts');c.execute('DELETE FROM sessions')
            app.PASSWORD_SALT,app.PASSWORD_HASH=old_salt,old_hash
    def test_foreign_origin_rejected(self):
        self.assertEqual(self.call('/api/folder',{'name':'denied'},headers={'Origin':'https://attacker.invalid'})[0],400)
    def test_routed_host_with_same_origin(self):
        app.ROUTED_LOCAL=True
        try:
            self.assertEqual(self.call('/api/health',headers={'Host':'books.example.test','Origin':'https://books.example.test'})[0],200)
            self.assertEqual(self.call('/api/health',headers={'Host':'books.example.test','Origin':'https://attacker.invalid'})[0],400)
        finally: app.ROUTED_LOCAL=False
    def test_annotations_survive_sync(self):
        sid='dQTr8VInXUE'
        self.assertEqual(self.call('/api/annotation',{'id':sid,'notes':'Une note personnelle','liked':True,'archived':True,'tags':['marché']})[0],200)
        app.sync();s=app.get_source(sid)
        self.assertEqual(s['annotation']['notes'],'Une note personnelle')
        self.assertTrue(s['annotation']['liked'])
        self.assertTrue(s['annotation']['archived'])
    def test_api_transcript_survives_inventory_sync(self):
        with app.connect() as c:
            row=next(r for r in c.execute('SELECT id,payload,text FROM sources') if not json.loads(r['payload']).get('segments'))
            original=(row['id'],row['payload'],row['text'])
        sid=original[0]
        try:
            app.api_v1.transcript(sid,{'text':'[00:00] Transcription manuelle\n[00:12] Suite','language':'fr','status':'Texte vérifié'})
            before=app.get_source(sid);app.sync();after=app.get_source(sid)
            self.assertEqual(after,before)
            self.assertEqual(after['segments'],before['segments'])
            self.assertEqual(after['status'],'Texte vérifié')
            self.assertEqual(after['language'],'fr')
            self.assertFalse(after['automatic'])
        finally:
            with app.connect() as c:c.execute('UPDATE sources SET payload=?,text=? WHERE id=?',(original[1],original[2],sid))
    def test_import_new_author_and_text(self):
        status,_,raw=self.call('/api/import',dict(title='Recherche complémentaire',author='Auteur test',text='[00:00] Une première idée\n[01:20] Une nuance',kind='Article',url='https://example.org/source'))
        self.assertEqual(status,200)
        s=app.get_source(json.loads(raw)['id'])
        self.assertEqual(s['segments'][1]['start'],80)
        self.assertEqual(s['author'],'Auteur test')
        with app.connect() as c:c.execute('DELETE FROM sources WHERE id=?',(s['id'],))
    def test_export_keeps_provenance(self):
        self.call('/api/book',dict(title='Essai sourcé',_revision=app.studio.book()['_revision'],chapters=[dict(title='Comprendre',ideas=['IDE-001'],notes='Mon texte original')]))
        out=app.export_book()
        self.assertIn('Mon texte original',out)
        self.assertIn('https://www.youtube.com/watch?v=dQTr8VInXUE&t=',out)
        self.assertIn('Bibliographie',out)
    def test_invalid_citation_rejected(self):
        with self.assertRaises(ValueError):app.save_idea(dict(title='Idée',refs=[dict(source_id='unknown',start=0,end=1)]))
        with self.assertRaises(ValueError):app.save_idea(dict(title='Idée',refs=[dict(source_id='dQTr8VInXUE',start=-1,end=1)]))
    def test_mock_llm_validates_indices_and_uses_real_quotes(self):
        s=app.get_source('dQTr8VInXUE');s['segments']=s['segments'][:3]
        reply={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary':'Test','tags':['test'],'chapters':[{'title':'Début','segment_index':0}],'ideas':[{'title':'Idée valide','segment_start':0,'segment_end':1,'tags':[]},{'title':'Hallucination','segment_start':999,'segment_end':1000}]})}}]}
        with patch.object(app,'llm_request',return_value=reply):n=app.extract(s,{'message':''})
        self.assertEqual(n,1)
        with app.connect() as c:
            ideas=app.objects(c,'ideas');found=next(i for i in ideas if i['title']=='Idée valide')
            self.assertEqual(found['refs'][0]['quote'],' '.join(x['text'] for x in s['segments'][:2]))
            self.assertEqual(found['importance'],'Contextuelle')
            c.execute('DELETE FROM ideas WHERE id=?',(found['id'],))
    def test_analysis_uses_low_reasoning_effort_and_reasoning_json_fallback(self):
        s=app.get_source('dQTr8VInXUE');s['segments']=s['segments'][:2];captured=[]
        answer={'summary':'Test','tags':[],'chapters':[],'ideas':[{'title':'Idée raisonnée','importance':'Fondamentale','segment_start':0,'segment_end':0}]}
        def fake_request(route,payload):
            captured.append(payload)
            return {'choices':[{'finish_reason':'stop','message':{'content':'','reasoning_content':json.dumps(answer)}}],'usage':{'completion_tokens':50,'completion_tokens_details':{'reasoning_tokens':20}}}
        with patch.object(app,'llm_request',side_effect=fake_request):n=app.extract(s,{'message':''})
        self.assertEqual(n,1);self.assertEqual(captured[0]['reasoning_effort'],'low');self.assertEqual(captured[0]['max_tokens'],16000)
        with app.connect() as c:
            found=next(i for i in app.objects(c,'ideas') if i['title']=='Idée raisonnée')
            self.assertEqual(found['importance'],'Fondamentale');c.execute('DELETE FROM ideas WHERE id=?',(found['id'],))
    def test_analysis_error_exposes_finish_reason_and_token_usage(self):
        s=app.get_source('dQTr8VInXUE');s['segments']=s['segments'][:1]
        reply={'choices':[{'finish_reason':'length','message':{'content':'','reasoning_content':'réflexion'}}],
               'usage':{'prompt_tokens':100,'completion_tokens':20,'completion_tokens_details':{'reasoning_tokens':20}}}
        with patch.object(app,'llm_request',return_value=reply),self.assertRaisesRegex(ValueError,'finish_reason=length') as caught:app.extract(s,{'message':''})
        self.assertIn('reasoning_tokens=20',str(caught.exception));self.assertIn('content=vide',str(caught.exception))
    def test_rewrite_preserves_complete_order_and_adds_final_punctuation(self):
        s=app.get_source('dQTr8VInXUE');s['segments']=s['segments'][:3]
        rows={'paragraphs':[{'segment_start':0,'segment_end':1,'text':'Première information reformulée.'},{'segment_start':2,'segment_end':2,'text':'Dernière information'}]}
        reply={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(rows)}}]}
        job={'id':'test-rewrite','total':1,'done':0,'message':''}
        with patch.object(app,'llm_request',return_value=reply):count=app.rewrite_transcript(s,job)
        self.assertEqual(count,2)
        self.assertEqual(job['done'],job['total'])
        rewritten=app.get_source(s['id'])['annotation']['rewritten_transcript']
        self.assertEqual((rewritten[0]['segment_start'],rewritten[-1]['segment_end']),(0,2))
        self.assertTrue(rewritten[-1]['text'].endswith('.'))
        with app.connect() as c:
            ann=app.annotation(c,s['id']);ann.pop('rewritten_transcript',None);ann.pop('rewrite_model',None);ann.pop('rewrite_created',None)
            c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)',(s['id'],app.dumps(ann)))
            c.execute("DELETE FROM settings WHERE id='job:test-rewrite'")
    def test_rewrite_rejects_an_omitted_segment(self):
        s=app.get_source('dQTr8VInXUE');s['segments']=s['segments'][:3]
        rows={'paragraphs':[{'segment_start':0,'segment_end':0,'text':'Début.'},{'segment_start':2,'segment_end':2,'text':'Fin.'}]}
        reply={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(rows)}}]}
        with patch.object(app,'llm_request',return_value=reply),self.assertRaisesRegex(ValueError,'omis ou désordonné'):app.rewrite_transcript(s,{'id':'test-rewrite-invalid','total':1,'done':0,'message':''})
        with app.connect() as c:c.execute("DELETE FROM settings WHERE id='job:test-rewrite-invalid'")
    def test_rewrite_resumes_from_last_completed_batch(self):
        s=app.get_source('dQTr8VInXUE');original=s['annotation'];s['segments']=[dict(start=i,duration=1,text=('texte '+str(i)+' ')*800) for i in range(3)]
        chunks=app.transcript_rewrite_chunks(s['segments']);self.assertEqual(len(chunks),3)
        def answer(chunk):
            a,b=chunk[0]['index'],chunk[-1]['index']
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'paragraphs':[{'segment_start':a,'segment_end':b,'text':f'Lot {a}.'}]})}}]}
        first=answer(chunks[0]);job={'id':'test-rewrite-resume-1','total':len(chunks),'done':0,'message':''}
        try:
            with patch.object(app,'llm_request',side_effect=[first,ValueError('coupure réseau')]),self.assertRaisesRegex(ValueError,'coupure réseau'):app.rewrite_transcript(s,job)
            draft=app.rewrite_draft(s,chunks,app.settings()['model']);self.assertEqual(draft['done'],1);self.assertEqual(len(draft['paragraphs']),1)
            calls=[]
            def resumed(route,request):
                chunk=json.loads(request['messages'][1]['content'])['segments'];calls.append(chunk[0]['index']);return answer(chunk)
            resumed_job={'id':'test-rewrite-resume-2','total':len(chunks),'done':0,'message':''}
            with patch.object(app,'llm_request',side_effect=resumed):count=app.rewrite_transcript(s,resumed_job)
            self.assertEqual(calls,[1,2]);self.assertEqual(count,3);self.assertEqual(resumed_job['resumed_from'],1)
            self.assertIsNone(app.rewrite_draft(s,chunks,app.settings()['model']))
        finally:
            with app.connect() as c:
                c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)',(s['id'],app.dumps(original)))
                c.execute("DELETE FROM settings WHERE id IN ('job:test-rewrite-resume-1','job:test-rewrite-resume-2',?)",('rewrite-draft:'+s['id'],))
    def test_idea_importance_is_saved_and_unknown_fields_are_rejected(self):
        data=dict(title='Idée importante',importance='Opérationnelle',archived=True,refs=[dict(source_id='dQTr8VInXUE',start=0,end=1)])
        item=app.save_idea(data);self.assertEqual(item['importance'],'Opérationnelle');self.assertTrue(item['archived'])
        try:
            with self.assertRaisesRegex(ValueError,'Champ.*inconnu'):app.save_idea({**data,'champ_invente':True})
            with self.assertRaisesRegex(ValueError,'Importance invalide'):app.save_idea({**data,'importance':'Urgente'})
        finally:
            with app.connect() as c:c.execute('DELETE FROM ideas WHERE id=?',(item['id'],))
    def test_blank_api_key_is_preserved_and_clear_is_explicit(self):
        previous=app.SECRET;app.SECRET='key-to-keep'
        payload=dict(provider='deepseek',base_url='https://api.deepseek.com',model='deepseek-flash',api_key='')
        try:
            self.assertEqual(self.call('/api/settings',payload)[0],200);self.assertEqual(app.SECRET,'key-to-keep')
            self.assertEqual(self.call('/api/settings',{**payload,'clear_api_key':True})[0],200);self.assertEqual(app.SECRET,'')
        finally:app.SECRET=previous
    def test_openapi_documents_pagination_limit_and_importance(self):
        doc=app.openapi_document();params=doc['paths']['/api/v1/sources']['get']['parameters']
        limit=next(x for x in params if x['name']=='limit')
        self.assertEqual(limit['schema']['maximum'],200)
        self.assertIn('liked',{x['name'] for x in params});self.assertIn('archived',{x['name'] for x in params})
        idea=doc['components']['schemas']['IdeaInput']
        self.assertIn('importance',idea['properties']);self.assertIn('liked',idea['properties']);self.assertIn('archived',idea['properties']);self.assertFalse(idea['additionalProperties'])
        self.assertIn('/api/v1/sources/tags',doc['paths']);self.assertIn('/api/v1/tags',doc['paths'])
        self.assertIn('/api/v1/sources/batch',doc['paths']);self.assertIn('/api/v1/ideas/batch',doc['paths'])
        self.assertEqual(doc['components']['schemas']['SourceBatchInput']['properties']['source_ids']['maxItems'],200)
        self.assertEqual(doc['components']['schemas']['SourceTagsInput']['properties']['source_ids']['maxItems'],200)
    def test_batch_favorite_archive_and_tags_are_atomic(self):
        sources=[s['id'] for s in app.library()['sources'][:2]]
        with app.connect() as c:
            ideas=[i['id'] for i in app.objects(c,'ideas')[:2]]
            old_annotations={sid:app.annotation(c,sid) for sid in sources}
            old_ideas={r['id']:r['payload'] for r in c.execute(f"SELECT id,payload FROM ideas WHERE id IN ({','.join('?' for _ in ideas)})",ideas)}
        try:
            result=app.api_v1.batch_sources({'source_ids':sources,'tags':['Lot API'],'mode':'add','liked':True,'archived':True})
            self.assertEqual(result['count'],2)
            self.assertTrue(all(x['liked'] and x['archived'] and 'Lot API' in x['tags'] for x in result['updated']))
            result=app.api_v1.batch_ideas({'idea_ids':ideas,'tags':['Idées lot'],'mode':'replace','liked':True,'archived':True})
            self.assertEqual(result['count'],2);self.assertTrue(all(x['tags']==['Idées lot'] for x in result['updated']))
            before=app.get_source(sources[0])['annotation']
            with self.assertRaisesRegex(ValueError,'introuvable'):app.api_v1.batch_sources({'source_ids':[sources[0],'inconnu'],'archived':False})
            self.assertEqual(app.get_source(sources[0])['annotation'],before)
        finally:
            with app.connect() as c:
                for sid,item in old_annotations.items():c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)',(sid,app.dumps(item)))
                for iid,payload in old_ideas.items():c.execute('UPDATE ideas SET payload=? WHERE id=?',(payload,iid))
    def test_bulk_source_tags_add_remove_and_replace(self):
        ids=[s['id'] for s in app.library()['sources'][:2]];before={sid:app.get_source(sid)['annotation']['tags'] for sid in ids}
        try:
            result=app.update_source_tags(ids,['Vlog','Facecam'],'add')
            self.assertEqual(result['count'],2);self.assertIn('Vlog',app.get_source(ids[0])['annotation']['tags'])
            app.update_source_tags(ids,['vlog'],'remove')
            self.assertNotIn('Vlog',app.get_source(ids[0])['annotation']['tags'])
            app.update_source_tags(ids,['Entretien'],'replace')
            self.assertEqual(app.get_source(ids[1])['annotation']['tags'],['Entretien'])
        finally:
            with app.connect() as c:
                for sid,tags in before.items():
                    item=app.annotation(c,sid);item['tags']=tags;c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)',(sid,app.dumps(item)))
    def test_no_key_no_analysis_and_no_secret_export(self):
        app.SECRET=''
        self.assertEqual(self.call('/api/analyze',{'ids':['dQTr8VInXUE']})[0],400)
        app.SECRET='secret-marker-for-test'
        self.assertNotIn('secret-marker-for-test',self.backup_bytes().decode())
        app.SECRET=''
    def test_similarity_returns_distinct_ideas(self):
        for p in app.related():
            self.assertNotEqual(p['a'],p['b']);self.assertGreater(p['score'],0)
    def test_protects_paths_and_headers(self):
        self.assertEqual(self.call('/../server.py')[0],404)
        status,headers,_=self.call('/')
        self.assertEqual(status,200);self.assertEqual(headers['X-Frame-Options'],'DENY')
    def test_wsgi_production_transport(self):
        captured=[]
        response=app.application({'REQUEST_METHOD':'GET','PATH_INFO':'/api/library','HTTP_HOST':f'127.0.0.1:{app.PORT}','wsgi.input':BytesIO()},lambda status,headers:captured.append((status,headers)))
        self.assertEqual(captured[0][0],'200 OK')
        self.assertEqual(len(json.loads(response[0])['sources']),269)
        body=json.dumps({'title':'WSGI book','chapters':[],'_revision':app.studio.book()['_revision']}).encode()
        app.application({'REQUEST_METHOD':'POST','PATH_INFO':'/api/book','HTTP_HOST':f'127.0.0.1:{app.PORT}','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(body)),'wsgi.input':BytesIO(body)},lambda status,headers:captured.append((status,headers)))
        self.assertEqual(captured[-1][0],'200 OK')
    def test_vault_encrypts_and_reloads_without_leak(self):
        from cryptography.fernet import Fernet
        app.VAULT_KEY=Fernet.generate_key().decode().rstrip('=')
        try:
            app.store_secret('test-secret-never-plaintext')
            with app.connect() as c:stored=c.execute("SELECT payload FROM settings WHERE id='secret'").fetchone()[0]
            self.assertNotIn('test-secret-never-plaintext',stored)
            app.SECRET='';app.load_secret()
            self.assertEqual(app.SECRET,'test-secret-never-plaintext')
            self.assertNotIn('test-secret-never-plaintext',self.backup_bytes().decode())
        finally:
            app.VAULT_KEY='';app.SECRET=''
    def test_failed_vault_save_keeps_previous_api_key(self):
        app.VAULT_KEY='invalid';app.SECRET='previous-test-key'
        try:
            status,_,raw=self.call('/api/settings',dict(base_url='https://api.deepseek.com',model='deepseek-flash',api_key='candidate-test-key'))
            self.assertEqual(status,400)
            self.assertEqual(app.SECRET,'previous-test-key')
            self.assertIn('coffre',json.loads(raw)['error'])
            self.assertNotIn('candidate-test-key',raw.decode())
        finally:app.VAULT_KEY='';app.SECRET=''
    def test_anthropic_provider_adapts_messages_and_authentication(self):
        previous_secret=app.SECRET
        with app.connect() as c:
            old=c.execute("SELECT payload FROM settings WHERE id='llm'").fetchone()
            c.execute("INSERT OR REPLACE INTO settings VALUES('llm',?)",(json.dumps({'provider':'anthropic','base_url':'https://api.anthropic.com/v1','model':'claude-test','instruction':''}),))
        app.SECRET='anthropic-test-key';captured=[]
        class FakeResponse(BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):return False
        def fake_open(request,timeout=0):
            captured.append(request)
            return FakeResponse(json.dumps({'content':[{'type':'text','text':'{"ok":true}'}],'stop_reason':'end_turn'}).encode())
        try:
            payload={'model':'claude-test','messages':[{'role':'system','content':'Instruction'},{'role':'user','content':'Question'}],'max_tokens':123}
            with patch.object(app.urllib.request,'urlopen',side_effect=fake_open):result=app.llm_request('/chat/completions',payload)
            self.assertEqual(captured[0].full_url,'https://api.anthropic.com/v1/messages')
            self.assertEqual(captured[0].get_header('X-api-key'),'anthropic-test-key')
            sent=json.loads(captured[0].data);self.assertEqual(sent['system'],'Instruction');self.assertEqual(sent['max_tokens'],123)
            self.assertEqual(result['choices'][0]['message']['content'],'{"ok":true}')
        finally:
            app.SECRET=previous_secret
            with app.connect() as c:
                if old:c.execute("INSERT OR REPLACE INTO settings VALUES('llm',?)",(old[0],))
                else:c.execute("DELETE FROM settings WHERE id='llm'")
    def test_llm_request_retries_truncated_responses(self):
        previous_secret=app.SECRET
        with app.connect() as c:
            old=c.execute("SELECT payload FROM settings WHERE id='llm'").fetchone()
            c.execute("INSERT OR REPLACE INTO settings VALUES('llm',?)",(json.dumps({'provider':'deepseek','base_url':'https://api.deepseek.com','model':'deepseek-test','instruction':''}),))
        app.SECRET='retry-test-key'
        class FakeResponse(BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):return False
        complete=FakeResponse(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'ok'}}]}).encode())
        try:
            with patch.object(app.urllib.request,'urlopen',side_effect=[app.IncompleteRead(b'{',10),app.IncompleteRead(b'{',10),complete]) as opened,patch.object(app.time,'sleep'):
                result=app.llm_request('/chat/completions',{'model':'deepseek-test','messages':[]})
            self.assertEqual(opened.call_count,3);self.assertEqual(result['choices'][0]['message']['content'],'ok')
        finally:
            app.SECRET=previous_secret
            with app.connect() as c:
                if old:c.execute("INSERT OR REPLACE INTO settings VALUES('llm',?)",(old[0],))
                else:c.execute("DELETE FROM settings WHERE id='llm'")
    def test_documented_bearer_api_and_token_lifecycle(self):
        password='api-password-for-tests'
        app.PASSWORD_HASH=hashlib.scrypt(password.encode(),salt=app.PASSWORD_SALT,n=16384,r=8,p=1)
        source_id=None;idea_id=None
        try:
            self.assertEqual(self.call('/api')[0],200)
            status,_,raw=self.call('/api/openapi.json')
            self.assertEqual(status,200);self.assertIn('/api/v1/sources',json.loads(raw)['paths'])
            _,headers,_=self.call('/api/login',{'password':password});cookie={'Cookie':headers['Set-Cookie'].split(';')[0]}
            status,_,raw=self.call('/api/tokens',{'name':'Agent de test'},cookie)
            self.assertEqual(status,201);created=json.loads(raw);token=created['token']
            self.assertTrue(token.startswith('atelier_'));self.assertNotIn(token,json.dumps(self.call('/api/tokens',headers=cookie)[2].decode()))
            auth={'Authorization':'Bearer '+token}
            self.assertEqual(self.call('/api/v1/sources?limit=2',headers=auth)[0],200)
            status,_,raw=self.call('/api/v1/sources',{'title':'Vidéo API','author':'Test','kind':'Vidéo','url':'https://example.test/video'},auth)
            self.assertEqual(status,201);source_id=json.loads(raw)['id']
            status,_,raw=self.call_method('PATCH',f'/api/v1/sources/{source_id}/annotation',{'liked':True,'archived':True},auth)
            self.assertEqual(status,200);self.assertTrue(json.loads(raw)['liked']);self.assertTrue(json.loads(raw)['archived'])
            filtered=json.loads(self.call('/api/v1/sources?liked=true&archived=true',headers=auth)[2])['items']
            self.assertTrue(any(x['id']==source_id for x in filtered))
            status,_,raw=self.call('/api/v1/sources/tags',{'source_ids':[source_id],'tags':['Vlog','Facecam'],'mode':'add'},auth)
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['updated'][0]['tags'],['Vlog','Facecam'])
            status,_,raw=self.call('/api/v1/tags',headers=auth)
            self.assertEqual(status,200);self.assertTrue(any(x['name']=='Vlog' for x in json.loads(raw)['items']))
            status,_,raw=self.call_method('PUT',f'/api/v1/sources/{source_id}/transcript',{'text':'[00:00] Bonjour\n[01:02] Suite','language':'fr'},auth)
            self.assertEqual(status,200);self.assertEqual(len(json.loads(raw)['segments']),2)
            status,_,raw=self.call(f'/api/v1/sources/{source_id}/transcript?format=text',headers=auth)
            self.assertEqual(status,200);self.assertIn('[01:02] Suite',raw.decode())
            status,_,raw=self.call('/api/v1/ideas',{'title':'Idée API favorite et archivée','refs':[{'source_id':source_id,'start':0,'end':1}],'liked':True,'archived':True},auth)
            self.assertEqual(status,201);idea_id=json.loads(raw)['id']
            filtered=json.loads(self.call('/api/v1/ideas?liked=true&archived=true',headers=auth)[2])['items']
            self.assertTrue(any(x['id']==idea_id for x in filtered))
            status,_,raw=self.call_method('PATCH',f'/api/v1/ideas/{idea_id}',{'archived':False},auth)
            self.assertEqual(status,200);self.assertFalse(json.loads(raw)['archived'])
            status,_,raw=self.call_method('PATCH','/api/v1/sources/batch',{'source_ids':[source_id],'tags':['Lot'],'mode':'add','liked':False,'archived':False},auth)
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['count'],1)
            status,_,raw=self.call_method('PATCH','/api/v1/ideas/batch',{'idea_ids':[idea_id],'tags':['Lot idées'],'mode':'add','liked':False,'archived':True},auth)
            self.assertEqual(status,200);self.assertTrue(json.loads(raw)['updated'][0]['archived'])
            listed=json.loads(self.call('/api/tokens',headers=cookie)[2])['items'][0]
            self.assertGreaterEqual(listed['use_count'],4);self.assertIsNotNone(listed['last_used_at'])
            self.assertEqual(self.call('/api/token-delete',{'id':created['id']},cookie)[0],200)
            self.assertEqual(self.call('/api/v1/sources',headers=auth)[0],401)
        finally:
            with app.connect() as c:
                if idea_id:c.execute('DELETE FROM ideas WHERE id=?',(idea_id,))
                if source_id:c.execute('DELETE FROM annotations WHERE id=?',(source_id,));c.execute('DELETE FROM sources WHERE id=?',(source_id,))
                c.execute('DELETE FROM api_tokens');c.execute('DELETE FROM sessions');c.execute('DELETE FROM attempts')
            app.PASSWORD_HASH=b''

if __name__=='__main__':unittest.main(verbosity=2)
