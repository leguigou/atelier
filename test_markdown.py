import unittest, tempfile, zipfile
from pathlib import Path
from io import BytesIO
from defusedxml import ElementTree as ET
from PIL import Image
from pypdf import PdfReader
import server as app
from book_markdown import render

class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=(app.DB,app.SECRET,app.VAULT_KEY)
        app.DB=Path(self.temp.name)/'test.sqlite';app.SECRET=app.VAULT_KEY='';app.init()
    def tearDown(self):
        app.DB,app.SECRET,app.VAULT_KEY=self.old;self.temp.cleanup()
    def test_rich_exports_and_local_image(self):
        image=BytesIO();Image.new('RGB',(200,100),'green').save(image,'PNG')
        asset=app.studio.store_asset(image.getvalue(),'example.png')['id']
        text='## Section\n\n**Gras** et *italique* et ~~barré~~.\n\nPremière ligne\\\nDeuxième ligne.\n\n- **Élément A**\n- Élément B\n  - Sous-élément\n\n> Une citation.\n\n| Nom | Valeur |\n| :--- | ---: |\n| Donnée | 42 |\n\n```text\ncode <littéral>\n```\n\n![Image test](/api/asset?id='+asset+'&preview=1)\n\n[Un lien](https://example.org)'
        book=app.studio.book();book['chapters']=[dict(id='ch',title='Chapitre',ideas=[],blocks=[dict(id='bl',type='text',text=text)])]
        book['layout'].update(alignment='left',paragraph_indent=5,paragraph_spacing=12)
        app.studio.save_book(book)
        with zipfile.ZipFile(BytesIO(app.studio.epub())) as z:
            markup=z.read('OEBPS/ch1.xhtml').decode();ET.fromstring(markup)
            for tag in ['<strong>','<em>','<s>','<table>','<blockquote>','<pre>','<br />']:self.assertIn(tag,markup)
            self.assertIn('images/'+asset+'.png',markup);self.assertIn('OEBPS/images/'+asset+'.png',z.namelist())
        self.assertIn(text,app.export_book())
        pdf=PdfReader(BytesIO(app.studio.pdf()));alltext='\n'.join(p.extract_text() for p in pdf.pages)
        for word in ['Gras','Donnée','42','citation','littéral']:self.assertIn(word,alltext)
        self.assertNotIn('**Gras**',alltext)
    def test_html_and_unsafe_urls_stay_literal(self):
        markup=render('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![x](file:///secret)')
        self.assertNotIn('<script>',markup);self.assertNotIn('href=',markup);self.assertNotIn('<img',markup)
    def test_editorial_extensions(self):
        text='++souligné++ ==surligné== m^2^ H~2~O ~~barré~~'
        markup=render(text)
        for tag in ['u','mark','sup','sub','s']:self.assertIn('<'+tag+'>',markup)
        self.assertNotIn('<u>',render('`++code++`'))
        book=app.studio.book();book['chapters']=[dict(id='ch',title='Styles',ideas=[],blocks=[dict(id='bl',type='text',text=text)])];app.studio.save_book(book)
        self.assertTrue(app.studio.pdf().startswith(b'%PDF'))
    def test_layout_validation(self):
        for field,value in [('alignment','bogus'),('paragraph_indent',11),('paragraph_spacing',17)]:
            book=app.studio.book();book['layout'][field]=value
            with self.assertRaises(ValueError):app.studio.save_book(book)

if __name__=='__main__':unittest.main()
