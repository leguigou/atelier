import json
import unittest
from urllib.parse import parse_qs
import test_studio as fixtures
import server as app
from studio import Conflict
from research import update, filter_items, migrate
from api_docs import openapi_document


class ResearchTests(unittest.TestCase):
    setUp = fixtures.StudioTests.setUp
    tearDown = fixtures.StudioTests.tearDown

    def change(self, b, **data):
        return update(self.s, b['_book_id'], {'revision':b['_revision'], **data})

    def sample(self):
        s=self.s.make_source('Une source commune','Auteur','Document',[dict(text='Un passage.',start=0,duration=0)])
        i=app.save_idea(dict(title='Une idée',refs=[dict(source_id=s['id'],start=0,end=0)]))
        return s,i

    def test_visual_library_keeps_previews_and_book_memberships(self):
        s=self.s.upload(fixtures.StudioTests.image(self),'photo.png','Photo commune')
        i=app.save_idea(dict(title='Idée illustrée',refs=[dict(source_id=s['id'],start=0,end=0)]))
        a=self.s.create_book({'title':'Livre A'});b=self.s.create_book({'title':'Livre B'})
        for book in (a,b):self.change(book,action='add',source_ids=[s['id']],idea_ids=[i['id']])
        data=app.compact_library()
        source=next(x for x in data['sources'] if x['id']==s['id'])
        self.assertEqual(source['preview_id'],s['preview_id'])
        self.assertEqual(source['asset_id'],s['asset_id'])
        for book in data['books']:
            if book['id'] in (a['_book_id'],b['_book_id']):
                self.assertEqual(book['research']['source_ids'],[s['id']])
                self.assertEqual(book['research']['idea_ids'],[i['id']])

    def test_shared_material_multiple_folders_notes_and_removal_are_isolated(self):
        s,i=self.sample();a=self.s.create_book({'title':'Livre A'});b=self.s.create_book({'title':'Livre B'})
        for name in ('Peur','Relations'):a=self.change(a,action='folder-create',name=name)
        ids=[f['id'] for f in a['research']['folders']]
        a=self.change(a,action='classify',source_ids=[s['id']],idea_ids=[i['id']],folder_ids=ids)
        a=self.change(a,action='notes',source_ids=[s['id']],note='Note pour A')
        b=self.change(b,action='add',source_ids=[s['id']],idea_ids=[i['id']])
        self.assertTrue(all(f['source_ids']==[s['id']] and f['idea_ids']==[i['id']] for f in a['research']['folders']))
        self.assertEqual(b['research']['folders'],[]);self.assertEqual(b['research']['source_notes'],{})
        a=self.change(a,action='remove',source_ids=[s['id']])
        self.assertEqual(a['research']['source_ids'],[])
        self.assertEqual(self.s.book(b['_book_id'])['research']['source_ids'],[s['id']])
        self.assertEqual(app.get_source(s['id'])['id'],s['id'])
        self.assertTrue(all(not f['source_ids'] and f['idea_ids']==[i['id']] for f in a['research']['folders']))

    def test_atomic_invalid_batch_and_stale_revision(self):
        s,_=self.sample();b=self.s.create_book({'title':'Livre'});before=self.s.book(b['_book_id'])
        with self.assertRaises(ValueError):self.change(b,action='add',source_ids=[s['id'],'missing'])
        self.assertEqual(before,self.s.book(b['_book_id']))
        saved=self.change(b,action='folder-create',name='Dossier')
        with self.assertRaises(Conflict):self.change(b,action='add',source_ids=[s['id']])
        self.assertEqual(saved,self.s.book(b['_book_id']))
        with self.assertRaises(ValueError):self.change(saved,action='classify',source_ids=[s['id']],folder_ids=['missing'])

    def test_folder_modes_unfiled_sort_and_api_dispatch(self):
        s,i=self.sample();b=self.s.create_book({'title':'Livre'})
        other=self.s.make_source('Zèbre','Auteur','Document',[])
        b=self.change(b,action='folder-create',name='Dossier');fid=b['research']['folders'][0]['id']
        b=self.change(b,action='classify',source_ids=[s['id']],folder_ids=[fid])
        b=self.change(b,action='add',source_ids=[other['id']],idea_ids=[i['id']])
        q=parse_qs('book_id='+b['_book_id']+'&sort=title&order=asc')
        self.assertEqual([x['id'] for x in app.api_v1.source_list(q)['items']],[s['id'],other['id']])
        q['unfiled']=['true'];self.assertEqual([x['id'] for x in app.api_v1.source_list(q)['items']],[other['id']])
        q.pop('unfiled');q['folder_id']=[fid];self.assertEqual([x['id'] for x in app.api_v1.source_list(q)['items']],[s['id']])
        self.assertEqual(app.api_v1.ideas({'book_id':[b['_book_id']]})['items'][0]['id'],i['id'])
        class Handler:
            def reply(self,value,*args,**kwargs):self.value=value
        h=Handler();self.assertTrue(app.api_v1.handle(h,'GET','/api/v1/books/'+b['_book_id']+'/research',''))
        self.assertEqual(h.value['revision'],b['_revision'])
        app.api_v1.handle(h,'PATCH','/api/v1/books/'+b['_book_id']+'/research','',{'revision':b['_revision'],'action':'classify','source_ids':[s['id']],'folder_ids':[fid],'mode':'remove'})
        self.assertEqual(h.value['research']['folders'][0]['source_ids'],[])
        self.assertEqual(h.value['research']['source_ids'],[s['id'],other['id']])
        with self.assertRaises(ValueError):filter_items(self.s,[],{'folder_id':[fid]},'source_ids')
        document=openapi_document();self.assertIn('/api/v1/books/{book_id}/research',document['paths'])
        self.assertIn('book_id',[x['name'] for x in document['paths']['/api/v1/sources']['get']['parameters']])

    def test_legacy_migration_is_idempotent_and_history_tracks_research(self):
        s,i=self.sample()
        with app.connect() as c:
            c.execute('INSERT INTO folders VALUES(?,?)',('legacy','Ancien dossier'))
            ann=app.annotation(c,s['id']);ann['folder']='legacy';c.execute('INSERT OR REPLACE INTO annotations VALUES(?,?)',(s['id'],app.dumps(ann)))
            b=self.s.book();b.pop('research');c.execute('UPDATE books SET payload=? WHERE id=?',(app.dumps(b),'book-main'))
        migrate(self.s);b=self.s.book();self.assertIn(s['id'],b['research']['source_ids'])
        self.assertEqual(b['research']['folders'][0]['source_ids'],[s['id']])
        migrate(self.s);self.assertEqual(b,self.s.book())
        b=self.change(b,action='folder-delete',folder_id='legacy')
        self.assertIn(s['id'],b['research']['source_ids'])
        self.assertIn('research',[x['path'] for x in self.s.version(b['_revision'])['changes']])


if __name__=='__main__':unittest.main()
