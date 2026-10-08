"""Book-owned research membership; shared originals are never copied or deleted."""
import json
from studio import Conflict


def initial(book):
    return dict(source_ids=list(book.get('source_ids', [])),
                idea_ids=list(dict.fromkeys(i for ch in book.get('chapters', []) for i in ch.get('ideas', []))),
                folders=[], source_notes={}, idea_notes={})


def validate(app, value):
    if not isinstance(value, dict): raise ValueError('Matière du livre invalide.')
    for key, table in [('source_ids', 'sources'), ('idea_ids', 'ideas')]:
        ids = value.get(key, [])
        if not isinstance(ids, list) or len(ids) > 10000 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('Liste de matière invalide.')
        # Deleted shared items may remain in historical books; API additions are checked separately.
    folders = value.get('folders', [])
    if not isinstance(folders, list) or len(folders) > 500: raise ValueError('Dossiers du livre invalides.')
    seen = set()
    for f in folders:
        if not isinstance(f, dict): raise ValueError('Dossier invalide.')
        fid = app.required(f, 'id', 100); app.required(f, 'name', 150)
        if fid in seen: raise ValueError('Identifiant de dossier dupliqué.')
        seen.add(fid)
        for key in ('source_ids', 'idea_ids'):
            ids = f.get(key, [])
            if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids) or not set(ids) <= set(value.get(key, [])):
                raise ValueError('Le contenu du dossier doit appartenir au livre.')
    for key in ('source_notes', 'idea_notes'):
        notes = value.get(key, {})
        if not isinstance(notes, dict) or len(notes) > 10000 or any(not isinstance(v, str) or len(v) > 6000 for v in notes.values()):
            raise ValueError('Notes de travail invalides.')


def migrate(studio):
    """Keep the legacy library and its folders available in the original project."""
    with studio.a.connect() as c:
        for row in c.execute('SELECT id,payload FROM books').fetchall():
            b = json.loads(row['payload'])
            if 'research' in b: continue
            r = initial(b)
            if row['id'] == 'book-main':
                r['source_ids'] = [x[0] for x in c.execute('SELECT id FROM sources')]
                r['idea_ids'] = [x[0] for x in c.execute('SELECT id FROM ideas')]
                annotations = {x['id']: json.loads(x['payload']) for x in c.execute('SELECT * FROM annotations')}
                ideas = {x['id']: json.loads(x['payload']) for x in c.execute('SELECT * FROM ideas')}
                for f in c.execute('SELECT * FROM folders ORDER BY name'):
                    r['folders'].append(dict(id=f['id'], name=f['name'],
                        source_ids=[sid for sid, a in annotations.items() if a.get('folder') == f['id']],
                        idea_ids=[iid for iid, i in ideas.items() if i.get('folder') == f['id']]))
            b['research'] = r
            c.execute('UPDATE books SET payload=? WHERE id=?', (studio.a.dumps(b), row['id']))
            if row['id'] == 'book-main': c.execute("UPDATE settings SET payload=? WHERE id='book'", (studio.a.dumps(b),))


def update(studio, bid, data):
    b = studio.book(bid)
    if data.get('revision') != b.get('_revision'): raise Conflict('Le livre a changé sur un autre appareil. Rechargez sa matière avant de continuer.')
    r = b.setdefault('research', initial(b)); action = data.get('action')
    folders = r['folders']; fid = data.get('folder_id')
    f = next((x for x in folders if x['id'] == fid), None)
    if action in ('folder-rename', 'folder-delete') and not f: raise ValueError('Dossier du livre introuvable.')
    if action == 'folder-create':
        folders.append(dict(id=studio.a.uid(), name=studio.a.required(data, 'name', 150), source_ids=[], idea_ids=[]))
    elif action == 'folder-rename': f['name'] = studio.a.required(data, 'name', 150)
    elif action == 'folder-delete': folders.remove(f)
    elif action in ('add', 'remove', 'classify', 'notes'):
        targets = {key: data.get(key, []) for key in ('source_ids', 'idea_ids')}
        for key, ids in targets.items():
            if not isinstance(ids, list) or len(ids) > 200 or any(not isinstance(x, str) for x in ids): raise ValueError('Choisissez au maximum 200 éléments par opération.')
            if ids:
                with studio.a.connect() as c:
                    table = 'sources' if key == 'source_ids' else 'ideas'
                    existing = {x[0] for x in c.execute(f'SELECT id FROM {table}')}
                if not set(ids) <= existing: raise ValueError('Élément de bibliothèque introuvable.')
        if not any(targets.values()): raise ValueError('Choisissez une source ou une idée.')
        chosen = data.get('folder_ids', [])
        if not isinstance(chosen, list) or any(not isinstance(x, str) for x in chosen) or not set(chosen) <= {x['id'] for x in folders}: raise ValueError('Dossier du livre introuvable.')
        mode = data.get('mode', 'replace')
        if mode not in ('add', 'remove', 'replace'): raise ValueError('Mode de classement invalide.')
        for key, ids in targets.items():
            note_key = 'source_notes' if key == 'source_ids' else 'idea_notes'
            if action in ('add', 'classify'):
                r[key] = list(dict.fromkeys([*r[key], *ids]))
            elif not set(ids) <= set(r[key]): raise ValueError('Cet élément ne fait pas partie du livre.')
            if action == 'remove':
                r[key] = [x for x in r[key] if x not in ids]
                if key == 'source_ids':b['source_ids']=[x for x in b.get('source_ids',[]) if x not in ids]
                for folder in folders: folder[key] = [x for x in folder[key] if x not in ids]
                for x in ids: r[note_key].pop(x, None)
            if action == 'classify' or (action == 'add' and chosen):
                for folder in folders:
                    selected = folder['id'] in chosen
                    if mode == 'replace' or (mode == 'remove' and selected): folder[key] = [x for x in folder[key] if x not in ids]
                    if selected and mode != 'remove': folder[key] = list(dict.fromkeys([*folder[key], *ids]))
            if action == 'notes':
                note = data.get('note', '')
                if not isinstance(note, str) or len(note) > 6000: raise ValueError('Note invalide (6000 caractères maximum).')
                for x in ids: r[note_key][x] = note
    else: raise ValueError('Action de classement inconnue.')
    return studio.save_book(b, 'Organisation de la matière · ' + action)


def filter_items(studio, items, query, key):
    bid = query.get('book_id', [''])[0]; fid = query.get('folder_id', [''])[0]
    unfiled = query.get('unfiled', ['false'])[0] in ('true', '1')
    if fid or unfiled:
        if not bid: raise ValueError('book_id est requis pour filtrer un dossier du livre.')
    if bid:
        b = studio.book(bid); r = b.get('research', initial(b)); ids = set(r[key])
        if fid:
            f = next((f for f in r['folders'] if f['id'] == fid), None)
            if not f: raise ValueError('Dossier du livre introuvable.')
            ids &= set(f[key])
        if unfiled: ids -= {x for f in r['folders'] for x in f[key]}
        items = [x for x in items if x['id'] in ids]
    sort = query.get('sort', ['recent'])[0]; order = query.get('order', [''])[0]
    if sort not in ('recent', 'added', 'title', 'duration') or order not in ('', 'asc', 'desc'): raise ValueError('Tri invalide.')
    field = {'recent': 'date' if key == 'source_ids' else 'created', 'added': 'added_at' if key == 'source_ids' else 'created', 'title': 'title', 'duration': 'duration'}[sort]
    items.sort(key=lambda x: (float(x.get(field, 0) or 0) if field == 'duration' else str(x.get(field, '')).casefold(), x['id']), reverse=(order == 'desc' if order else sort != 'title'))
    return items
