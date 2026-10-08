"""Isolated HTTP app for the author reading workflow browser test."""
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / '.runtime')]
import server as app

with tempfile.TemporaryDirectory() as directory:
    app.DB = Path(directory) / 'test.sqlite'
    app.PASSWORD_HASH = b''
    app.SECRET = app.VAULT_KEY = ''
    app.init()
    source = app.studio.make_source('Source de vérification', 'Auteur test', 'Document', [
        dict(start=0, duration=0, text='Le passage original de la source.', page=3)])
    book = app.studio.book()
    book['chapters'] = [dict(id='chapter-test', title='Chapitre de vérification', ideas=[], blocks=[
        dict(id='block-test', type='text', source_ids=[source['id']], text='Introduction conservée.\n\n' + 'Le passage à modifier pendant la lecture. ' * 180 + '\n\nConclusion conservée.')]),
        dict(id='chapter-two', title='Deuxième chapitre', ideas=[], blocks=[dict(id='block-two', type='text', text='Le second chapitre. ' * 80)])]
    app.studio.save_book(book)
    from waitress import create_server
    server = create_server(app.application, host='127.0.0.1', port=0, threads=8,
                           channel_timeout=60, expose_tracebacks=False)
    app.PORT = int(server.effective_port)
    app.APP_URL = f'http://127.0.0.1:{app.PORT}'
    print(app.APP_URL, flush=True)
    try:
        server.run()
    finally:
        server.close()
