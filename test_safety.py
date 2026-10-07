import hashlib
import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import server as app
import backup
import search


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = app.DB, app.PASSWORD_HASH, app.SECRET, app.VAULT_KEY
        app.DB = Path(self.tmp.name) / 'test.sqlite'
        app.PASSWORD_HASH=b''; app.SECRET=''; app.VAULT_KEY=''
        app.JOBS.clear();app.EDITORIAL_JOBS.clear();app.AGENT_JOBS.clear()
        app.init()

    def tearDown(self):
        app.DB, app.PASSWORD_HASH, app.SECRET, app.VAULT_KEY = self.previous
        app.JOBS.clear();app.EDITORIAL_JOBS.clear();app.AGENT_JOBS.clear()
        self.tmp.cleanup()

    def request(self, route, raw=None, headers=None):
        env={'REQUEST_METHOD':'POST' if raw is not None else 'GET','PATH_INFO':route,
             'HTTP_HOST':f'127.0.0.1:{app.PORT}','CONTENT_TYPE':'application/zip',
             'CONTENT_LENGTH':str(len(raw or b'')),'wsgi.input':BytesIO(raw or b''),**(headers or {})}
        response=[]
        body=b''.join(app.application(env,lambda status,headers:response.append((status,headers))))
        return int(response[0][0].split()[0]),body

    def alter_archive(self, raw, transform):
        output=BytesIO()
        with zipfile.ZipFile(BytesIO(raw)) as original,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as modified:
            manifest=json.loads(original.read('manifest.json'));transform(manifest)
            modified.writestr('manifest.json',json.dumps(manifest))
            for name in original.namelist():
                if name!='manifest.json':modified.writestr(name,original.read(name))
        return output.getvalue()

    def test_complete_backup_roundtrip_media_history_and_credentials(self):
        asset=app.studio.store_asset(b'original document','original.txt')
        source=app.studio.make_source('Recherche de sécurité','Auteur','Document',[dict(start=0,duration=0,text='Texte portable')],asset)
        b=app.studio.book();b['title']='Livre sauvegardé';b['source_ids']=[source['id']]
        b=app.studio.save_book(b)
        with app.connect() as c:
            c.execute("INSERT INTO annotations VALUES(?,?)",(source['id'],json.dumps({'notes':'Note conservée','tags':['portable']})))
            c.execute("INSERT OR REPLACE INTO settings VALUES('secret','private-secret-fixture')")
            c.execute("INSERT OR REPLACE INTO settings VALUES('llm',?)",(json.dumps({'model':'configuration-locale'}),))
            c.execute("INSERT INTO sessions VALUES('private-session-fixture',99999999999)")
        raw=backup.create(app)
        with zipfile.ZipFile(BytesIO(raw)) as z:
            self.assertNotIn(b'private-secret-fixture',z.read('manifest.json'))
            self.assertNotIn(b'private-session-fixture',z.read('manifest.json'))
            self.assertEqual(z.read('media/'+asset['path']),b'original document')
        changed=app.studio.book();changed['title']='Avant restauration';changed=app.studio.save_book(changed)
        result=backup.restore(app,raw)
        restored=app.studio.book()
        self.assertEqual(restored['title'],'Livre sauvegardé')
        self.assertNotEqual(restored['_revision'],b['_revision'])
        self.assertEqual(app.studio.history()[0]['id'],restored['_revision'])
        self.assertEqual(app.get_source(source['id'])['annotation']['notes'],'Note conservée')
        self.assertEqual((app.studio.media/app.studio.asset(asset['id'])['path']).read_bytes(),b'original document')
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT payload FROM settings WHERE id='secret'").fetchone()[0],'private-secret-fixture')
            self.assertIsNotNone(c.execute("SELECT 1 FROM sessions WHERE token='private-session-fixture'").fetchone())
        safety=backup.inspect(app,(app.DB.parent/'backups'/result['safety_backup']).read_bytes())
        self.assertEqual(json.loads(safety['tables']['books'][0]['payload'])['title'],'Avant restauration')
        self.assertIn(source['id'],app.search_source_ids('portable'))
        from studio import Conflict
        with self.assertRaises(Conflict):app.studio.save_book(changed)

    def test_bad_archive_cannot_mutate_data_or_escape_media(self):
        original=app.studio.book();raw=backup.create(app)
        bad=self.alter_archive(raw,lambda m:m['tables']['books'][0].update(payload='{}'))
        with self.assertRaises(ValueError):backup.restore(app,bad)
        self.assertEqual(app.studio.book(),original)
        buffer=BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            z.writestr('../outside.txt','bad');z.writestr('manifest.json','{}')
        with self.assertRaises(ValueError):backup.inspect(app,buffer.getvalue())
        self.assertFalse((app.DB.parent/'outside.txt').exists())

    def test_checksum_and_missing_files_are_rejected(self):
        app.studio.store_asset(b'content','document.txt');raw=backup.create(app)
        corrupt=self.alter_archive(raw,lambda m:next(iter(m['files'].values())).update(sha256='0'*64))
        with self.assertRaisesRegex(ValueError,'endommagé'):backup.inspect(app,corrupt)
        incomplete=self.alter_archive(raw,lambda m:m.update(files={}))
        with self.assertRaises(ValueError):backup.inspect(app,incomplete)

    def test_failure_to_save_safety_copy_preserves_live_data(self):
        raw=backup.create(app);b=app.studio.book();b['title']='Texte à protéger';app.studio.save_book(b)
        with patch.object(backup,'create',side_effect=OSError('disk full')),self.assertRaises(OSError):backup.restore(app,raw)
        self.assertEqual(app.studio.book()['title'],'Texte à protéger')

    def test_restore_requires_session_confirmation_and_idle_jobs(self):
        raw=backup.create(app)
        code,_=self.request('/api/backup-restore',raw);self.assertEqual(code,400)
        app.JOBS['busy']={'status':'running'}
        with self.assertRaisesRegex(ValueError,'travaux'):backup.restore(app,raw)
        app.JOBS.clear();app.PASSWORD_HASH=b'protected'
        code,_=self.request('/api/backup.zip');self.assertEqual(code,401)
        code,_=self.request('/api/backup-inspect',raw);self.assertEqual(code,401)
        with app.connect() as c:
            token='atelier_'+'a'*40
            c.execute('INSERT INTO api_tokens(id,name,token_hash,prefix,created_at) VALUES(?,?,?,?,?)',('t','agent',hashlib.sha256(token.encode()).hexdigest(),'atelier_a',app.now()))
        code,_=self.request('/api/backup-inspect',raw,{'HTTP_AUTHORIZATION':'Bearer '+token});self.assertEqual(code,403)

    def test_search_finds_reordered_accented_words_and_exact_segment(self):
        source=app.studio.make_source('Notes de travail','Auteur','Document',[
            dict(start=0,duration=0,text='Introduction sans mot recherché.'),
            dict(start=90,duration=15,text='La trésorerie doit rester positive pour lancer une activité.',page=7)])
        self.assertIn(source['id'],app.search_source_ids('activite tresorerie'))
        found=search.passages(app,'activite tresorerie')
        item=next(item for item in found['items'] if item['source_id']==source['id'])
        self.assertEqual((item['segment_index'],item['start'],item['page']),(1,90,7))
        self.assertIn('trésorerie',item['excerpt'])
        self.assertEqual(search.passages(app,'" OR * : --')['items'],search.passages(app,'OR')['items'])
        app.api_v1.save_source({'text':'Une correction unique zebratrigger'},app.get_source(source['id']))
        self.assertNotIn(source['id'],app.search_source_ids('activite tresorerie'))
        self.assertIn(source['id'],app.search_source_ids('zebratrigger'))
        app.update_source_tags([source['id']],['Étiquette spéciale'],'replace')
        self.assertIn(source['id'],app.search_source_ids('etiquette speciale'))
        app.update_source_tags([source['id']],[],'replace')
        self.assertNotIn(source['id'],app.search_source_ids('etiquette speciale'))
        with app.connect() as c:
            c.execute('DELETE FROM annotations WHERE id=?',(source['id'],))
            c.execute('DELETE FROM sources WHERE id=?',(source['id'],))
        self.assertNotIn(source['id'],app.search_source_ids('zebratrigger'))


if __name__=='__main__':unittest.main()
