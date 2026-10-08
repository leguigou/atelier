"""Durable book versions, file sources and portable publication exports."""
import json, re, mimetypes, hashlib, zipfile, posixpath, html, difflib, threading
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, parse_qs, unquote
from defusedxml import ElementTree as ET
from PIL import Image, ImageOps
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:pass

SOURCE_LINE=re.compile(r'^[ \t]*(Sources?|Références?)\s*:.*$\n?', re.M)
def strip_source_lines(text):
    """Drop the « Sources : … » line that generated paragraphs used to carry into the manuscript."""
    return SOURCE_LINE.sub('', str(text)).strip()

MAX_FILE = 30 * 1024 * 1024
PDF_LOCK = threading.Lock()  # PDFium is not thread-safe.
Image.MAX_IMAGE_PIXELS = 40_000_000

class Conflict(ValueError): pass

def plain(element):
    return ' '.join(' '.join(element.itertext()).split())

def zip_checked(raw):
    z = zipfile.ZipFile(BytesIO(raw))
    if len(z.infolist()) > 6000 or sum(i.file_size for i in z.infolist()) > 100_000_000:
        z.close(); raise ValueError('Archive trop volumineuse une fois décompressée (100 Mo maximum).')
    if any(i.flag_bits & 1 for i in z.infolist()):
        z.close(); raise ValueError('Archive chiffrée non prise en charge.')
    return z

def word_diff(before, after):
    a=re.findall(r'\s+|[^\s]+',str(before)); b=re.findall(r'\s+|[^\s]+',str(after))
    if len(a)+len(b)>30000: return [{'type':'delete','text':str(before)},{'type':'insert','text':str(after)}]
    result=[]
    for tag,i,j,k,l in difflib.SequenceMatcher(None,a,b,autojunk=True).get_opcodes():
        if tag=='equal': result.append({'type':'equal','text':''.join(a[i:j])})
        else:
            if tag in ('delete','replace'):result.append({'type':'delete','text':''.join(a[i:j])})
            if tag in ('insert','replace'):result.append({'type':'insert','text':''.join(b[k:l])})
    return result

class Studio:
    def __init__(self, app): self.a=app
    @property
    def media(self):
        path=self.a.DB.parent/'media'; path.mkdir(exist_ok=True); return path
    def migrate(self):
        with self.a.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, digest TEXT NOT NULL, path TEXT NOT NULL, preview TEXT, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS book_versions(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, created TEXT NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL, changes TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
            ''')
            if 'book_id' not in [r['name'] for r in c.execute('PRAGMA table_info(book_versions)')]:c.execute("ALTER TABLE book_versions ADD COLUMN book_id TEXT NOT NULL DEFAULT 'book-main'")
            c.execute('CREATE INDEX IF NOT EXISTS idx_book_versions_book ON book_versions(book_id,seq)')
            row=c.execute("SELECT payload FROM settings WHERE id='book'").fetchone()
            book=json.loads(row[0]) if row else {'title':'Mon livre','chapters':[]}
            book=self.normalize(book)
            book['_book_id']='book-main'
            if not c.execute('SELECT 1 FROM books LIMIT 1').fetchone():
                book['_revision']=self.a.uid()
                c.execute('INSERT INTO book_versions(id,created,label,payload,changes,book_id) VALUES(?,?,?,?,?,?)',(book['_revision'],self.a.now(),'Point de départ',self.a.dumps(book),'[]','book-main'))
                c.execute("INSERT OR REPLACE INTO settings VALUES('book',?)",(self.a.dumps(book),))
                c.execute('INSERT INTO books VALUES(?,?,?,?)',('book-main',self.a.dumps(book),self.a.now(),self.a.now()))
        from research import migrate
        migrate(self)
    def normalize(self,book):
        book=json.loads(json.dumps(book))
        book.setdefault('author','');book.setdefault('subtitle','')
        book.setdefault('layout',dict(font_size=11,line_height=1.55,margin=17,font='serif'))
        covers=book.setdefault('covers',{})
        covers.setdefault('front','');covers.setdefault('back','')
        covers.setdefault('front_variants',[]);covers.setdefault('back_variants',[])
        for ch in book.get('chapters',[]):
            ch.setdefault('id',self.a.uid());ch.setdefault('ideas',[])
            if 'blocks' not in ch: ch['blocks']=[{'id':self.a.uid(),'type':'text','text':ch.get('notes','')}] if ch.get('notes') else []
        return book
    def book(self,book_id=None):
        with self.a.connect() as c: row=c.execute('SELECT payload FROM books WHERE id=?',(book_id or 'book-main',)).fetchone()
        if not row:raise ValueError('Projet de livre introuvable.')
        return json.loads(row[0])
    def books(self):
        with self.a.connect() as c:rows=c.execute('SELECT * FROM books ORDER BY updated DESC').fetchall()
        result=[]
        for row in rows:
            b=json.loads(row['payload']);r=b.get('research',{})
            result.append(dict(id=row['id'],title=b['title'],author=b.get('author',''),description=b.get('description',''),cover=b.get('covers',{}).get('front',''),project_status=b.get('project_status','writing' if b['chapters'] else 'preparation'),chapters=len(b['chapters']),sources=len(r.get('source_ids',[])),ideas=len(r.get('idea_ids',[])),folders=len(r.get('folders',[])),updated=row['updated']))
        return result
    def create_book(self,data):
        title=self.a.required(data,'title',300);bid=self.a.uid();b=self.normalize(dict(title=title,author=str(data.get('author',''))[:300],chapters=[],_book_id=bid,_revision=self.a.uid()))
        b['description']=str(data.get('description',''))[:6000]
        from research import initial
        b['research']=initial(b)
        with self.a.connect() as c:
            c.execute('INSERT INTO books VALUES(?,?,?,?)',(bid,self.a.dumps(b),self.a.now(),self.a.now()))
            c.execute('INSERT INTO book_versions(id,created,label,payload,changes,book_id) VALUES(?,?,?,?,?,?)',(b['_revision'],self.a.now(),'Création du projet',self.a.dumps(b),'[]',bid))
        return b
    def validate_book(self,b):
        self.a.required(b,'title',300)
        from research import validate
        validate(self.a,b.get('research',{}))
        if not isinstance(b.get('description',''),str) or len(b.get('description',''))>6000:raise ValueError('Description du livre invalide.')
        if b.get('project_status','preparation') not in ('preparation','writing','done'):raise ValueError('État du projet invalide.')
        brief=b.get('brief',{})
        if not isinstance(brief,dict) or any(not isinstance(brief.get(k,''),str) or len(brief.get(k,''))>6000 for k in ('intention','reader','promise','voice')):raise ValueError('Intention du livre invalide.')
        source_ids=b.get('source_ids',[])
        if not isinstance(source_ids,list) or len(source_ids)>60 or any(not isinstance(s,str) for s in source_ids):raise ValueError('Choisissez au maximum 60 sources par livre.')
        for sid in source_ids:self.a.get_source(sid)
        covers=b.get('covers',{})
        if not isinstance(covers,dict):raise ValueError('Couvertures invalides.')
        for side in ('front','back'):
            variants=covers.get(side+'_variants',[])
            if not isinstance(variants,list) or len(variants)>30 or any(not isinstance(x,str) for x in variants):raise ValueError('Variantes de couverture invalides.')
            selected=covers.get(side,'')
            if selected and selected not in variants:raise ValueError('La couverture choisie doit figurer parmi ses variantes.')
            for aid in variants:
                if not self.asset(aid).get('preview'):raise ValueError('Image de couverture indisponible.')
        if not isinstance(b.get('chapters'),list) or len(b['chapters'])>300:raise ValueError('Chapitres invalides (300 maximum).')
        if len(self.a.dumps(b))>5_000_000:raise ValueError('Livre trop volumineux.')
        ids=set()
        for ch in b['chapters']:
            self.a.required(ch,'title',500)
            cid=self.a.required(ch,'id',100)
            if cid in ids:raise ValueError('Identifiant de chapitre dupliqué.')
            ids.add(cid)
            if ch.get('status','draft') not in ('draft','review','done'):raise ValueError('Statut de chapitre invalide.')
            if not isinstance(ch.get('blocks'),list) or len(ch['blocks'])>2000:raise ValueError('Blocs invalides.')
            bid=set()
            for block in ch['blocks']:
                if not isinstance(block.get('source_ids',[]),list) or any(not isinstance(s,str) for s in block.get('source_ids',[])):raise ValueError('Références du paragraphe invalides.')
                if block.get('type') not in ('text','heading','quote','image','pagebreak'):raise ValueError('Type de bloc invalide.')
                key=self.a.required(block,'id',100)
                if key in bid:raise ValueError('Identifiant de bloc dupliqué.')
                bid.add(key)
                if block['type']=='image':
                    if not self.asset(block.get('asset_id','')).get('preview'):raise ValueError('Image indisponible.')
                elif not isinstance(block.get('text',''),str):raise ValueError('Texte invalide.')
            ch['notes']='\n\n'.join(x.get('text','') for x in ch['blocks'] if x['type'] in ('text','heading','quote'))
        reviews=b.get('review_notes',[])
        if not isinstance(reviews,list) or len(reviews)>5000:raise ValueError('Notes de relecture invalides.')
        note_ids=set()
        for note in reviews:
            if not isinstance(note,dict):raise ValueError('Note de relecture invalide.')
            nid=self.a.required(note,'id',100)
            if nid in note_ids:raise ValueError('Identifiant de note dupliqué.')
            note_ids.add(nid)
            for key,limit in [('chapter_id',100),('block_id',100),('text',6000),('excerpt',1000)]:
                if not isinstance(note.get(key,''),str) or len(note.get(key,''))>limit:raise ValueError('Note de relecture invalide.')
            if type(note.get('offset',0)) is not int or not 0<=note.get('offset',0)<=5_000_000 or type(note.get('done',False)) is not bool:raise ValueError('Emplacement de note invalide.')
        layout=b.get('layout',{})
        for key,lo,hi in [('font_size',9,16),('line_height',1.2,2),('margin',10,25)]:
            if not lo<=float(layout.get(key,lo))<=hi:raise ValueError('Réglage de mise en page invalide.')
    def changes(self,old,new):
        out=[]
        def add(path,label,a,b,**extra):
            if a!=b:out.append(dict(path=path,label=label,before=a,after=b,**extra))
        for k,l in [('title','Titre du livre'),('subtitle','Sous-titre'),('author','Auteur'),('covers','Couvertures'),('layout','Mise en page'),('brief','Intention et lecteur'),('source_ids','Sources du projet'),('research','Matière et dossiers du livre'),('description','Description du projet'),('project_status','État du projet'),('editorial_proposal','Proposition de l’accompagnateur')]:add(k,l,old.get(k,''),new.get(k,''))
        oc={x['id']:x for x in old.get('chapters',[])};nc={x['id']:x for x in new.get('chapters',[])}
        add('review_notes','Notes de relecture',old.get('review_notes',[]),new.get('review_notes',[]))
        add('order','Ordre des chapitres',[x['id'] for x in old.get('chapters',[])],[x['id'] for x in new.get('chapters',[])])
        for cid in dict.fromkeys([*oc,*nc]):
            a=oc.get(cid,{});b=nc.get(cid,{})
            label=b.get('title') or a.get('title','Chapitre')
            if not a or not b:
                add('chapter/'+cid,('Chapitre ajouté : ' if b else 'Chapitre retiré : ')+label,a or '',b or '',chapter_id=cid);continue
            add(cid+'/title','Titre · '+label,a['title'],b['title'],chapter_id=cid)
            add(cid+'/purpose','Objectif · '+label,a.get('purpose',''),b.get('purpose',''),chapter_id=cid)
            add(cid+'/status','Statut · '+label,a.get('status','draft'),b.get('status','draft'),chapter_id=cid)
            add(cid+'/ideas','Idées sources · '+label,a.get('ideas',[]),b.get('ideas',[]),chapter_id=cid)
            ab={v['id']:v for v in a['blocks']};bb={v['id']:v for v in b['blocks']}
            add(cid+'/order','Ordre des blocs · '+label,[v['id'] for v in a['blocks']],[v['id'] for v in b['blocks']],chapter_id=cid)
            for bid in dict.fromkeys([*ab,*bb]):
                x=ab.get(bid,{});y=bb.get(bid,{})
                if x==y:continue
                block_type=(y or x)['type']; name={'text':'Paragraphe','heading':'Intertitre','quote':'Citation','image':'Image','pagebreak':'Saut de page'}[block_type]
                content=lambda v: v if block_type=='image' else v.get('text','') if v else ''
                # Store text and formatting changes, and retain the exact block location.
                before=content(x);after=content(y)
                if before==after:before=x;after=y
                add(cid+'/'+bid,name+' · '+label,before,after,chapter_id=cid,block_id=bid)
        return out
    def save_book(self,data,label='Enregistrement',restore=None):
        candidate=self.normalize(data);self.validate_book(candidate)
        bid=data.get('_book_id') or 'book-main'
        with self.a.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT payload FROM books WHERE id=?',(bid,)).fetchone()
            if not row:raise ValueError('Projet de livre introuvable.')
            current=json.loads(row[0])
            if data.get('_revision')!=current.get('_revision'):
                raise Conflict('Le livre a changé sur un autre appareil. Votre brouillon est conservé : rechargez la dernière version avant de le reporter.')
            if 'research' not in candidate and 'research' in current:candidate['research']=current['research']
            # New editorial selections and manuscript ideas join the research space.
            # Removing research membership alone does not remove manuscript references.
            if 'research' in candidate:
                r=candidate['research']
                new_sources=[x for x in candidate.get('source_ids',[]) if x not in current.get('source_ids',[])]
                old_ideas={i for ch in current.get('chapters',[]) for i in ch.get('ideas',[])}
                new_ideas=[i for ch in candidate.get('chapters',[]) for i in ch.get('ideas',[]) if i not in old_ideas]
                r['source_ids']=list(dict.fromkeys([*r.get('source_ids',[]),*new_sources]))
                r['idea_ids']=list(dict.fromkeys([*r.get('idea_ids',[]),*new_ideas]))
            changes=self.changes(current,candidate)
            if not changes and not restore:return current
            candidate['_revision']=self.a.uid()
            candidate['_book_id']=bid
            c.execute('INSERT INTO book_versions(id,created,label,payload,changes,book_id) VALUES(?,?,?,?,?,?)',(candidate['_revision'],self.a.now(),label[:300],self.a.dumps(candidate),self.a.dumps(changes),bid))
            c.execute('UPDATE books SET payload=?,updated=? WHERE id=?',(self.a.dumps(candidate),self.a.now(),bid))
            if bid=='book-main':c.execute("UPDATE settings SET payload=? WHERE id='book'",(self.a.dumps(candidate),))
        return candidate
    def editorial_apply(self,book_id,chapter_id,picked):
        """Fix the retained proposal items straight into the stored manuscript.

        Applied here with the server's own revision, so a browser holding a stale draft
        cannot lose the work to a version conflict: the paragraphs land in the book itself.
        """
        bid=book_id or 'book-main'
        with self.a.connect() as c:row=c.execute('SELECT payload FROM books WHERE id=?',(bid,)).fetchone()
        if not row:raise ValueError('Projet de livre introuvable.')
        book=json.loads(row[0]);book['_book_id']=bid
        proposal=book.get('editorial_proposal') or {}
        if not proposal:raise ValueError('Aucune proposition en attente pour ce livre.')
        if proposal.get('applied_at'):raise ValueError('Cette proposition est déjà ajoutée au manuscrit.')
        plan=proposal.get('mode')=='plan'
        items=(proposal.get('chapters') if plan else proposal.get('paragraphs')) or []
        if not items:raise ValueError('Cette proposition ne contient rien à ajouter.')
        kept=[]
        for value in (picked or []):
            try:index=int(value)
            except (TypeError,ValueError):continue
            if 0<=index<len(items):kept.append(items[index])
        if not kept:raise ValueError('Cochez au moins un élément.')
        evidence={e['id']:e for e in (proposal.get('evidence') or []) if e.get('id')}
        if plan:
            for item in kept:
                book['chapters'].append(dict(id=self.a.uid(),title=str(item.get('title',''))[:500],purpose=str(item.get('purpose',''))[:2500],ideas=[],blocks=[]))
        else:
            chapter=next((c for c in book['chapters'] if c.get('id')==chapter_id),None)
            if not chapter:raise ValueError('Le chapitre a été retiré du livre.')
            linked=[]
            for item in kept:
                refs=[evidence[r] for r in (item.get('evidence_ids') or []) if r in evidence]
                chapter.setdefault('blocks',[]).append(dict(id=self.a.uid(),type='text',text=str(item.get('text',''))[:12000],source_ids=list(dict.fromkeys(r['source_id'] for r in refs if r.get('source_id')))))
                linked+= [r['idea_id'] for r in refs if r.get('idea_id')]
            if linked:chapter['ideas']=list(dict.fromkeys([*(chapter.get('ideas') or []),*linked]))
        book['editorial_proposal']=dict(proposal,applied_at=self.a.now(),applied_count=len(kept))
        return self.save_book(book,'Proposition intégrée au manuscrit')
    def history(self,book_id=None):
        with self.a.connect() as c: rows=c.execute('SELECT seq,id,created,label,changes FROM book_versions WHERE book_id=? ORDER BY seq DESC',(book_id or 'book-main',)).fetchall()
        return [{**dict(r),'changes':[{k:v for k,v in x.items() if k not in ('before','after')} for x in json.loads(r['changes'])]} for r in rows]
    def version(self,vid):
        with self.a.connect() as c: r=c.execute('SELECT * FROM book_versions WHERE id=?',(vid,)).fetchone()
        if not r:raise ValueError('Version introuvable.')
        out=dict(r);out['book']=json.loads(out.pop('payload'));out['book']['_book_id']=out['book_id'];out['changes']=json.loads(out['changes'])
        for ch in out['changes']:
            stringify=lambda v:v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2)
            ch['diff']=word_diff(stringify(ch['before']),stringify(ch['after']))
        return out
    def restore(self,vid,revision):
        b=self.version(vid)['book'];b['_revision']=revision
        return self.save_book(b,'Restauration d’une version',restore=vid)
    def asset(self,aid):
        with self.a.connect() as c:r=c.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone()
        if not r:raise ValueError('Fichier introuvable.')
        return dict(r)
    def assets(self,images_only=False):
        query='SELECT id,name,mime,size,preview,created FROM assets'
        if images_only:query+=' WHERE preview IS NOT NULL'
        query+=' ORDER BY created DESC'
        with self.a.connect() as c:rows=c.execute(query).fetchall()
        return [dict(r) for r in rows]
    def store_asset(self,raw,name,mime=None):
        if not raw or len(raw)>MAX_FILE:raise ValueError('Fichier vide ou supérieur à 30 Mo.')
        name=Path(name.replace('\\','/')).name[:220] or 'document'
        digest=hashlib.sha256(raw).hexdigest()
        with self.a.connect() as c:r=c.execute('SELECT * FROM assets WHERE digest=? AND name=?',(digest,name)).fetchone()
        if r:return dict(r)
        aid=self.a.uid(); path=aid+'.bin';preview=None
        detected=mime or mimetypes.guess_type(name)[0] or 'application/octet-stream'
        if (detected.startswith('image/') and detected!='image/svg+xml') or Path(name).suffix.lower() in ('.jpg','.jpeg','.png','.webp','.gif','.tif','.tiff','.bmp','.heic','.heif'):
            try:
                with Image.open(BytesIO(raw)) as im:
                    im=ImageOps.exif_transpose(im);im.thumbnail((2200,2200))
                    if im.mode not in ('RGB','RGBA'):im=im.convert('RGBA')
                    preview=aid+'.png';im.save(self.media/preview,format='PNG')
                detected='image/'+('jpeg' if Path(name).suffix.lower() in ('.jpg','.jpeg') else 'png')
            except Exception as e:raise ValueError('Image non prise en charge. Utilisez JPEG, PNG, WebP, GIF, BMP, TIFF ou HEIC.') from e
        (self.media/path).write_bytes(raw)
        row=dict(id=aid,name=name,mime=detected,size=len(raw),digest=digest,path=path,preview=preview,created=self.a.now())
        with self.a.connect() as c:c.execute('INSERT INTO assets VALUES(:id,:name,:mime,:size,:digest,:path,:preview,:created)',row)
        return row
    def make_source(self,title,author,kind,segments,asset=None,**extra):
        if sum(len(s.get('text','')) for s in segments)>5_000_000:raise ValueError('Texte extrait trop volumineux (5 millions de caractères maximum).')
        s=dict(id=self.a.uid(),title=title[:1000],author=author[:300] or 'Auteur à préciser',kind=kind,segments=segments,url='',date='',added_at=self.a.now(),duration=0,description='',original_tags=[],chapters=[],status='Importée' if segments else 'Sans texte',automatic=False,language='',provenance='Fichier original conservé',views=0)
        if asset:s['asset_id']=asset['id'];s['filename']=asset['name'];s['preview_id']=asset['id'] if asset['preview'] else None
        s.update(extra)
        with self.a.connect() as c:c.execute('INSERT INTO sources VALUES(?,?,?)',(s['id'],self.a.dumps(s),' '.join(x.get('text','') for x in segments)))
        return s
    def upload(self,raw,name,title='',author='',as_source=True):
        ext=Path(name).suffix.lower();asset=self.store_asset(raw,name)
        if not as_source:return dict(asset_id=asset['id'],name=asset['name'],preview=bool(asset['preview']))
        segments=[];kind='Document';warning='';reading=[];pages=0;detected_title='';detected_author=''
        def seg(text,**kw):
            if text.strip():segments.append(dict(start=0,duration=0,text=text.strip(),**kw))
        try:
            if ext=='.pdf':
                from pypdf import PdfReader
                pdf=PdfReader(BytesIO(raw))
                if pdf.is_encrypted and not pdf.decrypt(''):raise ValueError('PDF protégé : importez une copie déverrouillée.')
                if len(pdf.pages)>1500:raise ValueError('PDF limité à 1 500 pages.')
                pages=len(pdf.pages);kind='PDF';metadata=pdf.metadata or {};detected_title=metadata.get('/Title','') or '';detected_author=metadata.get('/Author','') or ''
                for n,page in enumerate(pdf.pages):seg(page.extract_text() or '',page=n+1)
                if not segments:warning='PDF numérisé sans texte sélectionnable. Les pages sont consultables ; l’OCR n’est pas encore disponible.'
            elif ext=='.epub':
                kind='EPUB'
                with zip_checked(raw) as z:
                    root=ET.fromstring(z.read('META-INF/container.xml'));opf=root.find('.//{*}rootfile').attrib['full-path'];package=ET.fromstring(z.read(opf));base=posixpath.dirname(opf)
                    title_node=package.find('.//{*}metadata/{*}title');author_node=package.find('.//{*}metadata/{*}creator')
                    detected_title=plain(title_node) if title_node is not None else '';detected_author=plain(author_node) if author_node is not None else ''
                    manifest={n.attrib['id']:n.attrib for n in package.findall('.//{*}manifest/{*}item')}
                    for n,item in enumerate(package.findall('.//{*}spine/{*}itemref')):
                        entry=manifest.get(item.attrib.get('idref')); 
                        if not entry:continue
                        filepath=posixpath.normpath(posixpath.join(base,unquote(entry['href']).split('#')[0]))
                        if filepath.startswith('../') or filepath not in z.namelist():continue
                        doc=ET.fromstring(z.read(filepath));body=doc.find('.//{*}body')
                        if body is None:continue
                        section='Section '+str(n+1)
                        for el in body.iter():
                            tag=el.tag.rsplit('}',1)[-1]
                            if tag in ('h1','h2','h3','p','li','blockquote'):
                                text=plain(el)
                                if not text:continue
                                if tag.startswith('h'):section=text
                                seg(text,section=section);reading.append(dict(type='heading' if tag.startswith('h') else 'text',text=text,section=section))
                            elif tag=='img':
                                src=el.attrib.get('src','');path=posixpath.normpath(posixpath.join(posixpath.dirname(filepath),unquote(src).split('#')[0]))
                                if path in z.namelist() and not path.startswith('../'):
                                    try:
                                        image=self.store_asset(z.read(path),Path(path).name)
                                        if image['preview']:reading.append(dict(type='image',asset_id=image['id'],caption=el.attrib.get('alt','')))
                                    except ValueError:pass
                if not segments:warning='Cet EPUB ne contient pas de texte extractible ou est protégé.'
            elif ext in ('.docx','.odt'):
                kind='Document'
                with zip_checked(raw) as z:
                    xml=ET.fromstring(z.read('word/document.xml' if ext=='.docx' else 'content.xml'))
                    for el in xml.iter():
                        if el.tag.rsplit('}',1)[-1] in ('p','h'):seg(plain(el))
            elif asset['preview']:
                kind='Image';warning='Image conservée. Ajoutez une description pour la retrouver par le texte.'
            elif ext in ('.txt','.md','.csv','.srt','.vtt','.json','.html','.htm'):
                text=raw.decode('utf-8-sig',errors='replace')
                if ext in ('.html','.htm'):
                    from html.parser import HTMLParser
                    class TextOnly(HTMLParser):
                        def __init__(self):super().__init__();self.parts=[];self.skip=0
                        def handle_starttag(self,tag,attrs):
                            if tag in ('script','style'):self.skip+=1
                        def handle_endtag(self,tag):
                            if tag in ('script','style'):self.skip=max(0,self.skip-1)
                        def handle_data(self,data):
                            if not self.skip:self.parts.append(data)
                    parser=TextOnly();parser.feed(text);text='\n'.join(parser.parts)
                for line in text.splitlines():seg(line)
            else:warning='Fichier original conservé et téléchargeable. L’extraction de ce format n’est pas prise en charge.'
        except ValueError:raise
        except Exception as e:raise ValueError('Impossible de lire ce document. Vérifiez son format et l’absence de protection.') from e
        if detected_title.lower().strip() in ('untitled','sans titre'):detected_title=''
        if detected_author.lower().strip() in ('anonymous','unknown','anonyme'):detected_author=''
        return self.make_source(title.strip() or detected_title.strip() or Path(name).stem,author.strip() or detected_author.strip(),kind,segments,asset,warning=warning,reading=reading,page_count=pages)
    def pdf_page(self,aid,page):
        asset=self.asset(aid)
        if Path(asset['name']).suffix.lower()!='.pdf':raise ValueError('PDF attendu.')
        cache=self.media/f'{aid}-page-{page}.png'
        if cache.exists():return cache.read_bytes()
        with PDF_LOCK:
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(str(self.media/asset['path'])) as pdf:
                if not 1<=page<=len(pdf):raise ValueError('Page introuvable.')
                p=pdf[page-1];w,h=p.get_size();bitmap=p.render(scale=min(1.8,1600/max(w,h)));im=bitmap.to_pil();im.save(cache);bitmap.close();p.close()
        return cache.read_bytes()
    def youtube_id(self,url):
        u=urlparse(url);host=(u.hostname or '').lower();video=''
        if u.scheme not in ('http','https'):raise ValueError('Lien YouTube HTTP ou HTTPS attendu.')
        if host=='youtu.be':video=u.path.strip('/').split('/')[0]
        elif host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
            video=parse_qs(u.query).get('v',[''])[0] if u.path=='/watch' else u.path.split('/')[2] if u.path.startswith(('/shorts/','/embed/','/live/')) else ''
        if not re.fullmatch(r'[\w-]{11}',video):raise ValueError('Ajoutez un lien vers une vidéo YouTube, pas une chaîne ou une playlist.')
        return video
    def youtube(self,data):
        vid=self.youtube_id(data.get('url',''));url='https://www.youtube.com/watch?v='+vid
        with self.a.connect() as c:
            found=next((json.loads(r[0]) for r in c.execute('SELECT payload FROM sources') if (json.loads(r[0]).get('youtube_id') or json.loads(r[0])['id'])==vid),None)
        if found and found.get('segments'):return dict(source=found,already_present=True)
        s=found or self.make_source(data.get('title') or 'Vidéo YouTube · '+vid,data.get('author') or 'Auteur à récupérer','Vidéo',[],youtube_id=vid,url=url,status='Import en cours',provenance='YouTube')
        if any(j.get('type')=='youtube' and j.get('source_id')==s['id'] and j['status'] in ('queued','running') for j in self.a.JOBS.values()):return dict(source=s)
        job=dict(id=self.a.uid(),type='youtube',source_id=s['id'],status='queued',total=1,done=0,message='Récupération de la vidéo…',created=self.a.now(),errors=[])
        self.a.JOBS[job['id']]=job;self.a.persist_job(job)
        threading.Thread(target=self.fetch_youtube,args=(s,job),daemon=True).start()
        return dict(source=s,job=job)
    def subtitles(self,vid):
        """Sous-titres d'une vidéo : bibliothèque habituelle, puis repli yt-dlp si YouTube la bloque."""
        try:
            import requests
            class TimeoutSession(requests.Session):
                def request(self,*args,**kwargs):kwargs.setdefault('timeout',20);return super().request(*args,**kwargs)
            from youtube_transcript_api import YouTubeTranscriptApi
            candidates=list(YouTubeTranscriptApi(http_client=TimeoutSession()).list(vid))
            chosen=next((t for lang in ('fr','en') for t in candidates if t.language_code.startswith(lang)),candidates[0] if candidates else None)
            if chosen is None:raise ValueError('Aucun sous-titre disponible.')
            result=chosen.fetch()
            return result.to_raw_data(),result.language_code,result.is_generated,'youtube-transcript-api'
        except Exception:
            return self.subtitles_ytdlp(vid)
    def subtitles_ytdlp(self,vid):
        """Repli : yt-dlp récupère les sous-titres quand la bibliothèque se fait refuser par YouTube."""
        import os, sys, shutil, subprocess, tempfile
        tool=shutil.which('yt-dlp') or shutil.which('yt-dlp.exe')
        base=[tool] if tool else [sys.executable,'-m','yt_dlp']
        with tempfile.TemporaryDirectory() as folder:
            target=os.path.join(folder,'subs')
            try:
                done=subprocess.run(base+['--no-update','--skip-download','--write-subs','--write-auto-subs','--sub-langs','fr,en','--sub-format','json3','-o',target,'https://www.youtube.com/watch?v='+vid],capture_output=True,timeout=180)
            except FileNotFoundError:
                raise ValueError('yt-dlp introuvable : installez-le pour récupérer les sous-titres.')
            except subprocess.TimeoutExpired:
                raise ValueError('yt-dlp a dépassé le temps imparti.')
            if done.returncode and b'No module named' in (done.stderr or b''):
                raise ValueError('yt-dlp introuvable : installez-le (pip install yt-dlp) pour récupérer les sous-titres.')
            for lang in ('fr','en'):
                for name in ('subs.%s.json3'%lang,'subs.%s.auto.json3'%lang):
                    path=os.path.join(folder,name)
                    if os.path.exists(path):
                        segments=self.json3_segments(path)
                        if len(segments)>=3:return segments,lang,'auto' in name,'yt-dlp'
        raise ValueError('Sous-titres introuvables : YouTube n’en propose aucune piste exploitable.')
    def json3_segments(self,path):
        """Convertit des sous-titres json3 (yt-dlp) en segments horodatés."""
        segments=[]
        with open(path,encoding='utf-8') as f:events=json.load(f).get('events',[])
        for event in events:
            text=''.join(part.get('utf8','') for part in event.get('segs',[])).replace('\n',' ').strip()
            if text:segments.append(dict(text=text,start=event.get('tStartMs',0)/1000,duration=event.get('dDurationMs',0)/1000))
        return segments
    def fetch_youtube(self,s,job):
        job['status']='running';self.a.persist_job(job);vid=s.get('youtube_id') or s['id']
        try:
            import requests
            class TimeoutSession(requests.Session):
                def request(self,*args,**kwargs):kwargs.setdefault('timeout',20);return super().request(*args,**kwargs)
            try:
                r=TimeoutSession().get('https://www.youtube.com/oembed',params={'url':s['url'],'format':'json'});r.raise_for_status();meta=r.json();s.update(title=meta.get('title') or s['title'],author=meta.get('author_name') or s['author'])
            except Exception:pass
            segments,language,automatic,origin=self.subtitles(vid)
            s['segments']=segments;s['language']=language;s['automatic']=automatic;s['status']='Récupérée'
            s['duration']=max((x['start']+x.get('duration',0) for x in s['segments']),default=0)
            s['warning']='Sous-titres récupérés par yt-dlp : la bibliothèque habituelle avait été refusée.' if origin=='yt-dlp' else ''
            job['message']='Vidéo et transcription importées.'
        except Exception as e:
            s.setdefault('segments',[]);s['status']='Texte non récupéré'
            s['warning']='Le lien vidéo est conservé. La récupération automatique du texte a échoué — %s. Utilisez « Relancer la récupération » plus tard, ou collez une transcription manuellement.'%str(e).rstrip('. ')[:160]
            job['errors']=[dict(source_id=s['id'],message=s['warning'])];job['message']='Vidéo ajoutée, transcription indisponible.'
        with self.a.connect() as c:c.execute('UPDATE sources SET payload=?,text=? WHERE id=?',(self.a.dumps(s),' '.join(x['text'] for x in s['segments']),s['id']))
        job.update(status='finished',done=1);self.a.persist_job(job)
    def refetch_transcript(self,data):
        """Relance la récupération du texte d'une source existante (bouton « Relancer la récupération »)."""
        s=self.a.get_source(str(data.get('id') or ''));vid=s.get('youtube_id') or ''
        if not vid and s.get('url'):
            try:vid=self.youtube_id(s['url'])
            except ValueError:vid=''
        if not vid:raise ValueError('Cette source ne vient pas d’une vidéo YouTube : collez son texte à la place.')
        if any(j.get('type')=='refetch' and j.get('source_id')==s['id'] and j['status'] in ('queued','running') for j in self.a.JOBS.values()):return dict(source=s)
        job=dict(id=self.a.uid(),type='refetch',source_id=s['id'],status='queued',total=1,done=0,message='Nouvelle tentative de récupération…',created=self.a.now(),errors=[])
        self.a.JOBS[job['id']]=job;self.a.persist_job(job)
        threading.Thread(target=self.fetch_youtube,args=(s,job),daemon=True).start()
        return dict(source=s,job=job)
    def book_sections(self,b=None):
        # Reading and export carry the manuscript only: no source list, no reference lines.
        # Sources stay consultable while reviewing, from the chapter editor.
        b=b or self.book();sections=[]
        with self.a.connect() as c:ideas={v['id']:v for v in self.a.objects(c,'ideas')}
        for ch in b['chapters']:
            blocks=[]
            for blk in ch['blocks']:
                blk=dict(blk)
                blk['original_text']=blk.get('text','')
                if blk.get('text'):blk['text']=strip_source_lines(blk['text'])
                blocks.append(blk)
            for iid in ch.get('ideas',[]):
                i=ideas.get(iid)
                if not i:continue
                blocks.append(dict(type='heading',text=i['title']))
                if i.get('notes'):blocks.append(dict(type='text',text=i['notes']))
            sections.append(dict(title=ch['title'],chapter_id=ch['id'],status=ch.get('status','draft'),blocks=blocks))
        return sections
    def pdf(self,book_id=None):
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image as RLImage, KeepTogether
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A5
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab import rl_config
        b=self.book(book_id);buf=BytesIO();margin=float(b['layout']['margin'])*mm;size=float(b['layout']['font_size']);leading=size*float(b['layout']['line_height'])
        fontpath=Path(__file__).parent/'public'/'fonts'/'BookSerif.ttf'
        if not fontpath.exists():fontpath=Path(rl_config.TTFSearchPath[0])/'Vera.ttf'
        # Bundled DejaVu Serif covers French and common multilingual punctuation.
        if fontpath.exists():
            if 'BookSerif' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('BookSerif',str(fontpath)))
            font='BookSerif'
        else:font='Times-Roman'
        styles=getSampleStyleSheet();body=ParagraphStyle('BookBody',fontName=font,fontSize=size,leading=leading,spaceAfter=8,alignment=TA_JUSTIFY,splitLongWords=True)
        heading=ParagraphStyle('BookHeading',parent=body,fontSize=size*1.6,leading=size*2,spaceAfter=18,alignment=0)
        quote=ParagraphStyle('BookQuote',parent=body,leftIndent=12,rightIndent=8,textColor='#596457')
        caption=ParagraphStyle('BookCaption',parent=body,fontSize=9,leading=12,alignment=TA_CENTER)
        clean=lambda s:html.escape(str(s)).replace('\n','<br/>')
        width=A5[0]-2*margin; maxheight=A5[1]-2*margin-40
        def cover_flowable(aid):
            a=self.asset(aid);path=self.media/a['preview']
            with Image.open(path) as im:iw,ih=im.size
            scale=min(width/iw,(A5[1]-2*margin)/ih)
            return RLImage(str(path),width=iw*scale,height=ih*scale)
        front=b.get('covers',{}).get('front','');back=b.get('covers',{}).get('back','')
        if front:story=[cover_flowable(front),PageBreak()]
        else:story=[Spacer(1,35*mm),Paragraph(clean(b['title']),ParagraphStyle('Title',parent=heading,fontSize=26,leading=34,alignment=TA_CENTER)),Paragraph(clean(b.get('subtitle','')),caption),Spacer(1,15*mm),Paragraph(clean(b.get('author','')),caption),PageBreak()]
        for n,ch in enumerate(self.book_sections(b)):
            if n:story.append(PageBreak())
            story.append(Paragraph(clean(ch['title']),heading))
            for block in ch['blocks']:
                typ=block['type']
                if typ=='pagebreak':story.append(PageBreak())
                elif typ=='image':
                    a=self.asset(block['asset_id']);path=self.media/a['preview']
                    with Image.open(path) as im:iw,ih=im.size
                    scale=min(width*float(block.get('width',100))/100/iw,maxheight/ih)
                    picture=RLImage(str(path),width=iw*scale,height=ih*scale)
                    parts=[picture]
                    if block.get('caption'):parts.extend([Spacer(1,7),Paragraph(clean(block['caption']),caption)])
                    story.append(KeepTogether(parts));story.append(Spacer(1,10))
                else:
                    for p in re.split(r'\n\s*\n',block.get('text','')):
                        if p.strip():story.append(Paragraph(clean(p),heading if typ=='heading' else quote if typ=='quote' else body))
        if back:story.extend([PageBreak(),cover_flowable(back)])
        def footer(canvas,doc):
            canvas.setFont(font,8);canvas.setFillColorRGB(.45,.48,.43);canvas.drawCentredString(A5[0]/2,9*mm,str(doc.page))
        SimpleDocTemplate(buf,pagesize=A5,leftMargin=margin,rightMargin=margin,topMargin=margin,bottomMargin=margin,title=b['title'],author=b.get('author','')).build(story,onFirstPage=footer,onLaterPages=footer)
        return buf.getvalue()
    def epub(self,book_id=None):
        b=self.book(book_id);buf=BytesIO();items=[];spine=[];nav=[];pictures={}
        esc=lambda v:html.escape(str(v),quote=True)
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
            z.writestr('META-INF/container.xml','<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
            covers=b.get('covers',{});front=covers.get('front','');back=covers.get('back','')
            sections=[]
            if front:sections.append(dict(title='Couverture',blocks=[dict(type='image',asset_id=front,caption='',alt='Couverture de '+b['title'])],cover=True))
            else:sections.append(dict(title=b['title'],blocks=[dict(type='text',text=b.get('subtitle','')+'\n'+b.get('author',''))]))
            sections+=self.book_sections(b)
            if back:sections.append(dict(title='Quatrième de couverture',blocks=[dict(type='image',asset_id=back,caption='',alt='Quatrième de couverture de '+b['title'])],back_cover=True))
            for n,ch in enumerate(sections):
                is_cover=ch.get('cover') or ch.get('back_cover');content='' if is_cover else '<h1>'+esc(ch['title'])+'</h1>'
                for block in ch['blocks']:
                    typ=block['type']
                    if typ=='image':
                        aid=block['asset_id'];a=self.asset(aid)
                        if aid not in pictures:z.writestr('OEBPS/images/'+aid+'.png',(self.media/a['preview']).read_bytes());pictures[aid]=True
                        content+=f'<figure><img src="images/{aid}.png" alt="{esc(block.get("alt",block.get("caption","")))}"/><figcaption>{esc(block.get("caption",""))}</figcaption></figure>'
                    elif typ=='pagebreak':content+='<hr class="pagebreak"/>'
                    else:
                        tag={'heading':'h2','quote':'blockquote'}.get(typ,'p');content+=f'<{tag}>'+esc(block.get('text','')).replace('\n','<br/>')+f'</{tag}>'
                name=f'ch{n}.xhtml';z.writestr('OEBPS/'+name,'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr"><head><title>'+esc(ch['title'])+'</title><link rel="stylesheet" href="style.css"/></head><body'+(' class="cover"' if is_cover else '')+'>'+content+'</body></html>')
                items.append(f'<item id="ch{n}" href="{name}" media-type="application/xhtml+xml"/>');spine.append(f'<itemref idref="ch{n}"/>');nav.append(f'<li><a href="{name}">{esc(ch["title"])}</a></li>')
            z.writestr('OEBPS/style.css','body{font-family:serif;line-height:1.6;margin:5%;}img{max-width:100%;max-height:80vh;}figure{margin:1em 0;text-align:center;}figcaption{font-size:.85em;}h1,h2{break-after:avoid;}blockquote{margin:1em;color:#455346;}.pagebreak{break-before:page;border:0;}body.cover{margin:0;text-align:center;}body.cover figure{margin:0;}body.cover img{max-height:100vh;}')
            z.writestr('OEBPS/nav.xhtml','<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Sommaire</title></head><body><nav epub:type="toc"><h1>Sommaire</h1><ol>'+''.join(nav)+'</ol></nav></body></html>')
            assets=''.join(f'<item id="img{aid}" href="images/{aid}.png" media-type="image/png"'+(' properties="cover-image"' if aid==front else '')+'/>' for aid in pictures)
            opf='<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:'+esc(b['_revision'])+'</dc:identifier><dc:title>'+esc(b['title'])+'</dc:title><dc:creator>'+esc(b.get('author',''))+'</dc:creator><dc:language>fr</dc:language><meta property="dcterms:modified">'+self.a.now()[:19]+'Z</meta></metadata><manifest>'+''.join(items)+assets+'<item id="style" href="style.css" media-type="text/css"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine>'+''.join(spine)+'</spine></package>'
            z.writestr('OEBPS/book.opf',opf)
        return buf.getvalue()
