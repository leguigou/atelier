"""Portable content archives. Credentials stay on the current installation."""
import hashlib
import json
import re
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from studio import Studio

MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
TABLES = ('sources', 'annotations', 'ideas', 'folders', 'assets', 'books', 'book_versions', 'agent_threads')


def media_path(app, name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
        raise ValueError('Nom de fichier de sauvegarde invalide.')
    root = app.studio.media.resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise ValueError('Fichier hors de la médiathèque.')
    return path


def create(app, connection=None):
    if connection is None:
        with app.connect() as c:
            c.execute('BEGIN')
            return create(app, c)
    tables = {table: [dict(row) for row in connection.execute('SELECT * FROM ' + table)] for table in TABLES}
    prompts = [dict(row) for row in connection.execute("SELECT * FROM settings WHERE id LIKE 'prompt:%'")]
    manifest = dict(format='atelier-backup', version=1, created=app.now(), tables=tables, prompts=prompts, files={})
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        total = 0
        for asset in tables['assets']:
            for key in ('path', 'preview'):
                name = asset[key]
                if not name or name in manifest['files']:
                    continue
                path = media_path(app, name)
                if not path.is_file():
                    raise ValueError('Sauvegarde incomplète : fichier manquant dans la médiathèque.')
                total += path.stat().st_size
                if total > MAX_EXPANDED:
                    raise ValueError('Médiathèque supérieure à 512 Mo : utilisez une sauvegarde du volume.')
                raw = path.read_bytes()
                manifest['files'][name] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                archive.writestr('media/' + name, raw)
        archive.writestr('manifest.json', app.dumps(manifest).encode('utf-8'))
    raw = buffer.getvalue()
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('Archive supérieure à 256 Mo : utilisez une sauvegarde du volume.')
    return raw


def inspect(app, raw):
    if not 0 < len(raw) <= MAX_ARCHIVE:
        raise ValueError('Archive limitée à 256 Mo.')
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(entries) > 20000 or len(set(names)) != len(names) or sum(item.file_size for item in entries) > MAX_EXPANDED:
                raise ValueError('Archive trop volumineuse ou fichiers dupliqués.')
            if any(item.flag_bits & 1 for item in entries):
                raise ValueError('Les archives chiffrées ne sont pas prises en charge.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'atelier-backup' or manifest.get('version') != 1:
                raise ValueError('Format de sauvegarde Atelier inconnu.')
            if not isinstance(manifest.get('created'), str):
                raise ValueError('Date de sauvegarde invalide.')
            tables = manifest['tables']
            if set(tables) != set(TABLES) or not tables['books']:
                raise ValueError('Sauvegarde sans livre ou tables incomplètes.')
            files = manifest['files']
            expected = {'manifest.json'}
            needed = {asset[key] for asset in tables['assets'] for key in ('path', 'preview') if asset[key]}
            if set(files) != needed:
                raise ValueError('Fichiers de la médiathèque incomplets.')
            for name, metadata in files.items():
                media_path(app, name)
                entry = 'media/' + name
                expected.add(entry)
                contents = archive.read(entry)
                if len(contents) != metadata['size'] or hashlib.sha256(contents).hexdigest() != metadata['sha256']:
                    raise ValueError('Un fichier de la sauvegarde est endommagé.')
            if set(names) != expected:
                raise ValueError('L’archive contient des fichiers inattendus.')
            validate_tables(app, tables, manifest.get('prompts', []))
            for asset in tables['assets']:
                metadata = files[asset['path']]
                if asset['digest'] != metadata['sha256'] or asset['size'] != metadata['size']:
                    raise ValueError('Original de la médiathèque endommagé.')
            return manifest
    except (zipfile.BadZipFile, KeyError, TypeError, AttributeError, json.JSONDecodeError, UnicodeError, sqlite3.Error, RuntimeError) as exc:
        raise ValueError('Sauvegarde invalide ou incomplète.') from exc


def validate_tables(app, tables, prompts):
    # Validate rows and uniqueness in an isolated database before touching live data.
    with app.connect() as c:
        schemas = {table: c.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0] for table in TABLES}
        columns = {table: [row['name'] for row in c.execute('PRAGMA table_info(' + table + ')')] for table in TABLES}
    with sqlite3.connect(':memory:') as scratch:
        scratch.row_factory = sqlite3.Row
        scratch.execute('PRAGMA foreign_keys=ON')
        for table in TABLES:
            scratch.execute(schemas[table])
        for table in TABLES:
            if not isinstance(tables[table], list):
                raise ValueError('Table de sauvegarde invalide.')
            for row in tables[table]:
                if not isinstance(row, dict) or set(row) != set(columns[table]):
                    raise ValueError('Schéma de sauvegarde incompatible.')
                for key in ('payload', 'messages', 'actions', 'changes'):
                    if key in row:
                        value = json.loads(row[key])
                        if not isinstance(value, (dict, list)):
                            raise ValueError('Contenu de sauvegarde invalide.')
                scratch.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in columns[table])+')', [row[key] for key in columns[table]])
        def get_source(sid):
            row = scratch.execute('SELECT payload FROM sources WHERE id=?', (sid,)).fetchone()
            if not row: raise ValueError('Source du livre manquante.')
            return json.loads(row[0])
        isolated = Studio(SimpleNamespace(connect=lambda: scratch, required=app.required, dumps=app.dumps, get_source=get_source))
        for row in tables['books']:
            isolated.validate_book(json.loads(row['payload']))
    books = {row['id']: json.loads(row['payload']) for row in tables['books']}
    if 'book-main' not in books or any(book.get('_book_id') != bid or not isinstance(book.get('chapters'), list) or not book.get('title') for bid, book in books.items()):
        raise ValueError('Projets de livre invalides.')
    sources = {row['id'] for row in tables['sources']}
    assets = {row['id'] for row in tables['assets']}
    for row in tables['sources']:
        source = json.loads(row['payload'])
        if source.get('id') != row['id'] or not isinstance(source.get('segments'), list) or not isinstance(source.get('title'), str) or not source['title'] or not isinstance(source.get('author'), str) or not source['author']:
            raise ValueError('Source invalide.')
        if source.get('asset_id') and source['asset_id'] not in assets:
            raise ValueError('Pièce jointe manquante.')
        if any(not isinstance(segment, dict) or not isinstance(segment.get('text'), str) for segment in source['segments']):
            raise ValueError('Transcription invalide.')
    for book in books.values():
        if any(sid not in sources for sid in book.get('source_ids', [])):
            raise ValueError('Source du livre manquante.')
        for chapter in book['chapters']:
            if not chapter.get('id') or not chapter.get('title') or not isinstance(chapter.get('blocks'), list):
                raise ValueError('Chapitre invalide.')
            for block in chapter['blocks']:
                if block.get('type') == 'image' and block.get('asset_id') not in assets:
                    raise ValueError('Image du livre manquante.')
        for side in ('front', 'back'):
            if any(aid not in assets for aid in book.get('covers', {}).get(side+'_variants', [])):
                raise ValueError('Couverture manquante.')
    if not isinstance(prompts, list) or any(set(row) != {'id', 'payload'} or not row['id'].startswith('prompt:') or row['id'][7:] not in app.PROMPT_MISSIONS or not isinstance(json.loads(row['payload']).get('text'), str) for row in prompts):
        raise ValueError('Prompts invalides.')


def summary(manifest):
    return dict(created=manifest['created'], sources=len(manifest['tables']['sources']), books=len(manifest['tables']['books']), ideas=len(manifest['tables']['ideas']), assets=len(manifest['tables']['assets']))


def restore(app, raw):
    manifest = inspect(app, raw)
    with app.LOCK:
        if any(job.get('status') in ('queued', 'running') for jobs in (app.JOBS, app.EDITORIAL_JOBS, app.AGENT_JOBS) for job in jobs.values()):
            raise ValueError('Attendez la fin des travaux en cours avant de restaurer.')
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # A full safety copy is written before any content is replaced.
            safety = app.DB.parent / 'backups'
            safety.mkdir(exist_ok=True)
            filename = 'avant-restauration-' + app.uid() + '.zip'
            (safety / filename).write_bytes(create(app, c))
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                replacements = {}
                for name, meta in manifest['files'].items():
                    # Content-addressed names never overwrite current media.
                    new_name = 'restored-' + meta['sha256'] + Path(name).suffix
                    target = media_path(app, new_name)
                    if not target.exists():
                        target.write_bytes(archive.read('media/' + name))
                    elif hashlib.sha256(target.read_bytes()).hexdigest() != meta['sha256']:
                        raise ValueError('Un fichier restauré existant est endommagé.')
                    replacements[name] = new_name
                for asset in manifest['tables']['assets']:
                    asset['path'] = replacements[asset['path']]
                    if asset['preview']: asset['preview'] = replacements[asset['preview']]
            for table in reversed(TABLES): c.execute('DELETE FROM ' + table)
            for table in TABLES:
                for row in manifest['tables'][table]:
                    if table == 'books':
                        book = json.loads(row['payload']); book['_revision'] = app.uid()
                        row['payload'] = app.dumps(book)
                    columns = list(row)
                    c.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')', [row[key] for key in columns])
            for row in manifest['tables']['books']:
                book = json.loads(row['payload'])
                c.execute('INSERT INTO book_versions(id,created,label,payload,changes,book_id) VALUES(?,?,?,?,?,?)',
                          (book['_revision'], app.now(), 'Restauration de la sauvegarde', row['payload'], '[]', row['id']))
            c.execute("DELETE FROM settings WHERE id LIKE 'prompt:%' OR id LIKE 'job:%' OR id LIKE 'editorial-job:%' OR id LIKE 'agent-job:%' OR id LIKE 'rewrite-draft:%'")
            for row in manifest.get('prompts', []): c.execute('INSERT INTO settings VALUES(?,?)', (row['id'], row['payload']))
            main = c.execute("SELECT payload FROM books WHERE id='book-main'").fetchone()[0]
            c.execute("INSERT OR REPLACE INTO settings VALUES('book',?)", (main,))
            c.execute("INSERT OR REPLACE INTO settings VALUES('seeded','true')")
        app.JOBS.clear(); app.EDITORIAL_JOBS.clear(); app.AGENT_JOBS.clear()
    return dict(restored=True, safety_backup=filename, **summary(manifest))
