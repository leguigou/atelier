import unittest,tempfile,json,zipfile,threading,urllib.request,urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from reportlab.pdfgen import canvas
from pypdf import PdfReader
import server as app
from studio import Studio,Conflict,zip_checked

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old_db=app.DB;app.DB=Path(self.tmp.name)/'studio.sqlite'
        self.oldsecret=app.SECRET;self.oldvault=app.VAULT_KEY;app.SECRET='';app.VAULT_KEY='';app.JOBS.clear();app.init();self.s=app.studio
    def tearDown(self):
        app.DB=self.old_db;app.SECRET=self.oldsecret;app.VAULT_KEY=self.oldvault;self.tmp.cleanup()
    def image(self):
        b=BytesIO();Image.new('RGB',(640,400),'#afc49a').save(b,'PNG');return b.getvalue()
    def text_book(self,b=None,text='Premier paragraphe'):
        b=b or self.s.book();b['chapters']=[dict(id='chapter1',title='Commencer',ideas=['IDE-001'],blocks=[dict(id='block1',type='text',text=text)])];return self.s.save_book(b)
    def test_projects_are_isolated(self):
        first=self.text_book();second=self.s.create_book({'title':'Deuxième ouvrage'});self.text_book(second,'Un autre texte')
        self.assertEqual(self.s.book(first['_book_id'])['chapters'][0]['blocks'][0]['text'],'Premier paragraphe')
        self.assertEqual(len(self.s.history(first['_book_id'])),2)
        self.assertEqual(len(self.s.history(second['_book_id'])),2)
        self.assertNotEqual(self.s.history(first['_book_id'])[0]['id'],self.s.history(second['_book_id'])[0]['id'])
    def test_versions_diff_restore_and_stale_conflict(self):
        one=self.text_book();old=json.loads(json.dumps(one));two=json.loads(json.dumps(one));two['chapters'][0]['blocks'][0]['text']='Premier paragraphe enrichi';two=self.s.save_book(two)
        changes=self.s.version(two['_revision'])['changes'];textchange=next(c for c in changes if c.get('block_id')=='block1')
        self.assertEqual(textchange['chapter_id'],'chapter1');self.assertTrue(any(d['type']=='insert' and 'enrichi' in d['text'] for d in textchange['diff']))
        with self.assertRaises(Conflict):self.s.save_book(old)
        restored=self.s.restore(one['_revision'],two['_revision']);self.assertEqual(restored['chapters'][0]['blocks'][0]['text'],'Premier paragraphe');self.assertNotEqual(restored['_revision'],one['_revision']);self.assertEqual(len(self.s.history()),4)
    def test_noop_does_not_create_version(self):
        b=self.s.book();self.s.save_book(b);self.assertEqual(len(self.s.history()),1)
    def test_review_notes_status_history_restore_and_conflict(self):
        first=self.text_book();b=json.loads(json.dumps(first))
        b['chapters'][0]['status']='review'
        b['review_notes']=[dict(id='note1',chapter_id='chapter1',block_id='block1',offset=5,excerpt='Premier',text='Préciser cette idée',done=False)]
        saved=self.s.save_book(b)
        self.assertEqual(self.s.book()['review_notes'][0]['text'],'Préciser cette idée')
        changes=self.s.version(saved['_revision'])['changes']
        self.assertTrue(any(c['path']=='review_notes' for c in changes))
        self.assertTrue(any(c['path']=='chapter1/status' for c in changes))
        with self.assertRaises(Conflict):self.s.save_book(first)
        restored=self.s.restore(first['_revision'],saved['_revision'])
        self.assertEqual(restored.get('review_notes',[]),[])
    def test_invalid_review_data_is_rejected(self):
        for field,value in [('status','invalid'),('review_notes',[dict(id='n',offset=-1)]),('review_notes',[dict(id='n',text=123)])]:
            with self.subTest(field=field,value=value):
                b=self.text_book()
                if field=='status':b['chapters'][0][field]=value
                else:b[field]=value
                with self.assertRaises(ValueError):self.s.save_book(b)
    def test_reader_keeps_original_text_and_location_without_exporting_source_lines(self):
        raw='Premier paragraphe\nSources : référence privée\n\nSecond paragraphe'
        b=self.text_book(text=raw);section=self.s.book_sections(b)[0]
        self.assertEqual(section['chapter_id'],'chapter1')
        self.assertEqual(section['blocks'][0]['id'],'block1')
        self.assertEqual(section['blocks'][0]['original_text'],raw)
        self.assertNotIn('référence privée',section['blocks'][0]['text'])
    def test_image_upload_preserves_original_normalizes_preview(self):
        raw=self.image();s=self.s.upload(raw,'../photo.png',author='Test')
        self.assertEqual(s['kind'],'Image');a=self.s.asset(s['asset_id']);self.assertEqual(a['name'],'photo.png');self.assertEqual((self.s.media/a['path']).read_bytes(),raw);self.assertTrue((self.s.media/a['preview']).exists())
        with Image.open(self.s.media/a['preview']) as im:self.assertEqual(im.size,(640,400))
    def test_pdf_upload_and_page_render(self):
        raw=BytesIO();p=canvas.Canvas(raw);p.drawString(50,700,'Premiere page de recherche');p.showPage();p.drawString(50,700,'Deuxieme page');p.save()
        s=self.s.upload(raw.getvalue(),'recherche.pdf');self.assertEqual(s['page_count'],2);self.assertEqual(s['segments'][1]['page'],2)
        image=self.s.pdf_page(s['asset_id'],2);self.assertTrue(image.startswith(b'\x89PNG'))
        with self.assertRaises(ValueError):self.s.pdf_page(s['asset_id'],3)
    def test_pdf_scan_has_explicit_warning(self):
        raw=BytesIO();p=canvas.Canvas(raw);p.rect(50,500,100,100);p.showPage();p.save();s=self.s.upload(raw.getvalue(),'scan.pdf');self.assertEqual(s['segments'],[]);self.assertIn('OCR',s['warning'])
    def test_epub_export_roundtrip_contains_images_and_spine(self):
        b=self.text_book();a=self.s.store_asset(self.image(),'illustration.png');b['chapters'][0]['blocks'].append(dict(id='photo',type='image',asset_id=a['id'],caption='Une illustration sourcée',width=100));self.s.save_book(b)
        raw=self.s.epub()
        with zipfile.ZipFile(BytesIO(raw)) as z:
            self.assertEqual(z.namelist()[0],'mimetype');self.assertEqual(z.getinfo('mimetype').compress_type,zipfile.ZIP_STORED);self.assertIn(b'<spine>',z.read('OEBPS/book.opf'));self.assertIn('OEBPS/images/'+a['id']+'.png',z.namelist())
        source=self.s.upload(raw,'mon-livre.epub');self.assertEqual(source['kind'],'EPUB');self.assertTrue(any(x['type']=='image' for x in source['reading']));self.assertTrue(any('Premier paragraphe' in x['text'] for x in source['segments']))
    def test_a5_pdf_has_text_images_and_dimensions(self):
        b=self.text_book(text=('Écrire un livre avec des sources. ' * 150));a=self.s.store_asset(self.image(),'schema.png');b['chapters'][0]['blocks'].append(dict(id='image',type='image',asset_id=a['id'],caption='Figure de recherche',width=75));self.s.save_book(b)
        raw=self.s.pdf();r=PdfReader(BytesIO(raw));self.assertGreater(len(r.pages),2);self.assertAlmostEqual(float(r.pages[0].mediabox.width),419.5276,places=2);self.assertAlmostEqual(float(r.pages[0].mediabox.height),595.2756,places=2)
        text='\n'.join(p.extract_text() for p in r.pages);self.assertIn('Figure de recherche',text);self.assertNotIn('Sources et références',text)
    def test_proposal_lands_in_the_stored_book_even_with_a_stale_draft(self):
        # Un brouillon de navigateur périmé ne doit plus faire perdre les paragraphes retenus.
        b=self.text_book(text='Déjà écrit.')
        b['editorial_proposal']=dict(mode='draft',book_id=b['_book_id'],chapter_id='chapter1',revision=b['_revision'],created='2026-09-30T00:00:00+00:00',
            paragraphs=[dict(text='Nouveau paragraphe',evidence_ids=['E1'])],evidence=[dict(id='E1',source_id='source1',idea_id='IDE-001')],
            questions=[],rationale='',analysis='',interpretation='',ideas_used=[],omitted=[],model='m',notice='')
        b=self.s.save_book(b)
        applied=self.s.editorial_apply(b['_book_id'],'chapter1',[0])
        blocks=self.s.book(b['_book_id'])['chapters'][0]['blocks']
        self.assertEqual([x['text'] for x in blocks],['Déjà écrit.','Nouveau paragraphe'])
        self.assertEqual(blocks[-1]['source_ids'],['source1']);self.assertTrue(applied['editorial_proposal']['applied_at'])
        with self.assertRaises(ValueError):self.s.editorial_apply(b['_book_id'],'chapter1',[0])
    def test_cover_variants_are_validated_and_exported(self):
        b=self.text_book();front=self.s.store_asset(self.image(),'couverture-avant.png');back=self.s.store_asset(self.image(),'couverture-arriere.png')
        b['covers']={'front':front['id'],'back':back['id'],'front_variants':[front['id']],'back_variants':[back['id']]};saved=self.s.save_book(b)
        self.assertEqual(saved['covers']['front'],front['id']);self.assertEqual([a['id'] for a in self.s.assets(True)][:2],[back['id'],front['id']])
        pdf=PdfReader(BytesIO(self.s.pdf()));self.assertGreaterEqual(len(pdf.pages),3)
        with zipfile.ZipFile(BytesIO(self.s.epub())) as z:
            opf=z.read('OEBPS/book.opf').decode();self.assertIn('properties="cover-image"',opf);self.assertIn('OEBPS/images/'+front['id']+'.png',z.namelist());self.assertIn('OEBPS/images/'+back['id']+'.png',z.namelist())
        invalid=json.loads(json.dumps(saved));invalid['covers']['front']='missing'
        with self.assertRaises(ValueError):self.s.save_book(invalid)
    def test_docx_extraction_and_binary_attachment(self):
        b=BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="test"><w:body><w:p><w:r><w:t>Une source Word</w:t></w:r></w:p></w:body></w:document>')
        s=self.s.upload(b.getvalue(),'note.docx');self.assertIn('Une source Word',s['segments'][0]['text'])
        other=self.s.upload(b'original bytes','archive.xyz');self.assertEqual(other['segments'],[]);self.assertIn('pas prise en charge',other['warning'])
    def test_youtube_validation_dedup_and_failure_fallback(self):
        self.assertEqual(self.s.youtube_id('https://youtu.be/dQTr8VInXUE?t=5'),'dQTr8VInXUE')
        with self.assertRaises(ValueError):self.s.youtube_id('http://localhost:5000/private')
        r=self.s.youtube({'url':'https://youtube.com/watch?v=dQTr8VInXUE'});self.assertTrue(r['already_present'])
        s=self.s.make_source('Test vidéo','Auteur','Vidéo',[],youtube_id='abcdefghijk',url='https://www.youtube.com/watch?v=abcdefghijk')
        j=dict(id=app.uid(),status='queued',done=0,total=1,message='',errors=[])
        with patch('requests.Session.request',side_effect=ConnectionError('offline')),patch('youtube_transcript_api.YouTubeTranscriptApi.list',side_effect=RuntimeError('429')):self.s.fetch_youtube(s,j)
        self.assertEqual(j['status'],'finished');self.assertEqual(app.get_source(s['id'])['status'],'Texte non récupéré')
    def test_assets_and_versions_need_login(self):
        original=app.PASSWORD_HASH;app.PASSWORD_HASH=b'required'
        try:
            from io import BytesIO
            for path in ['/api/asset?id=anything','/api/history','/api/book.epub','/api/book.pdf','/api/books']:
                result=[];app.application({'REQUEST_METHOD':'GET','PATH_INFO':path.split('?')[0],'QUERY_STRING':path.split('?')[1] if '?' in path else '','HTTP_HOST':f'127.0.0.1:{app.PORT}','wsgi.input':BytesIO()},lambda status,headers:result.append(status));self.assertTrue(result[0].startswith('401'))
        finally:app.PASSWORD_HASH=original

if __name__=='__main__':unittest.main(verbosity=2)
