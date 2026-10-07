"""Indexed source and passage search, maintained by SQLite triggers."""
import json
import re


def init(app):
    with app.connect() as c:
        existing = c.execute("SELECT 1 FROM sqlite_master WHERE name='sources_fts'").fetchone()
        c.executescript('''
        CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(source_id UNINDEXED,title,author,text,tags,tokenize='unicode61 remove_diacritics 2');
        CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(source_id UNINDEXED,segment_index UNINDEXED,text,tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER IF NOT EXISTS search_source_insert AFTER INSERT ON sources BEGIN
          INSERT INTO sources_fts(source_id,title,author,text,tags) VALUES(new.id,json_extract(new.payload,'$.title'),json_extract(new.payload,'$.author'),new.text,coalesce((SELECT json_extract(payload,'$.tags') FROM annotations WHERE id=new.id),''));
          INSERT INTO passages_fts(source_id,segment_index,text) SELECT new.id,key,json_extract(value,'$.text') FROM json_each(new.payload,'$.segments');
        END;
        CREATE TRIGGER IF NOT EXISTS search_source_update AFTER UPDATE ON sources BEGIN
          DELETE FROM sources_fts WHERE source_id=old.id;
          DELETE FROM passages_fts WHERE source_id=old.id;
          INSERT INTO sources_fts(source_id,title,author,text,tags) VALUES(new.id,json_extract(new.payload,'$.title'),json_extract(new.payload,'$.author'),new.text,coalesce((SELECT json_extract(payload,'$.tags') FROM annotations WHERE id=new.id),''));
          INSERT INTO passages_fts(source_id,segment_index,text) SELECT new.id,key,json_extract(value,'$.text') FROM json_each(new.payload,'$.segments');
        END;
        CREATE TRIGGER IF NOT EXISTS search_source_delete AFTER DELETE ON sources BEGIN
          DELETE FROM sources_fts WHERE source_id=old.id;
          DELETE FROM passages_fts WHERE source_id=old.id;
        END;
        CREATE TRIGGER IF NOT EXISTS search_annotation_insert AFTER INSERT ON annotations BEGIN
          UPDATE sources_fts SET tags=json_extract(new.payload,'$.tags') WHERE source_id=new.id;
        END;
        CREATE TRIGGER IF NOT EXISTS search_annotation_update AFTER UPDATE ON annotations BEGIN
          UPDATE sources_fts SET tags=json_extract(new.payload,'$.tags') WHERE source_id=new.id;
        END;
        CREATE TRIGGER IF NOT EXISTS search_annotation_delete AFTER DELETE ON annotations BEGIN
          UPDATE sources_fts SET tags='' WHERE source_id=old.id;
        END;
        ''')
        if not existing:
            c.execute('''INSERT INTO sources_fts(source_id,title,author,text,tags)
              SELECT s.id,json_extract(s.payload,'$.title'),json_extract(s.payload,'$.author'),s.text,
              coalesce(json_extract(a.payload,'$.tags'),'') FROM sources s LEFT JOIN annotations a ON a.id=s.id''')
            c.execute("INSERT INTO passages_fts(source_id,segment_index,text) SELECT s.id,j.key,json_extract(j.value,'$.text') FROM sources s,json_each(s.payload,'$.segments') j")


def expression(query):
    # Literal words only: callers cannot inject FTS operators or column selectors.
    words = list(dict.fromkeys(re.findall(r'[^\W_]+', str(query), re.UNICODE)))[:16]
    return ' AND '.join('"' + word + '"*' for word in words)


def source_ids(app, query):
    match = expression(query)
    if not match: return []
    with app.connect() as c:
        return [row[0] for row in c.execute('SELECT source_id FROM sources_fts WHERE sources_fts MATCH ? ORDER BY bm25(sources_fts,0,5,2,1,3)', (match,))]


def passages(app, query, limit=30, offset=0):
    limit = max(1, min(100, int(limit))); offset = max(0, int(offset))
    match = expression(query)
    if not match: return dict(items=[], total=0, limit=limit, offset=offset)
    with app.connect() as c:
        total = c.execute('SELECT count(*) FROM passages_fts WHERE passages_fts MATCH ?', (match,)).fetchone()[0]
        rows = c.execute('''SELECT p.source_id,p.segment_index,s.payload,
            snippet(passages_fts,2,'','',' … ',35) AS excerpt
            FROM passages_fts p JOIN sources s ON s.id=p.source_id
            WHERE passages_fts MATCH ? ORDER BY bm25(passages_fts),p.source_id,p.segment_index LIMIT ? OFFSET ?''', (match, limit, offset)).fetchall()
    items = []
    for row in rows:
        source = json.loads(row['payload']); index = int(row['segment_index']); segment = source['segments'][index]
        items.append(dict(source_id=source['id'], title=source['title'], author=source['author'], kind=source['kind'],
                          segment_index=index, start=segment.get('start', 0), page=segment.get('page'),
                          section=segment.get('section'), excerpt=row['excerpt']))
    return dict(items=items, total=total, limit=limit, offset=offset)
