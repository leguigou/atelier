"""Build portable initial data from the original files, never from personal notes."""
import json, os, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    os.environ['ATELIER_DATA']=tmp
    import server
    server.init()
    out=Path(__file__).parent/'corpus'
    out.mkdir(exist_ok=True)
    with server.connect() as c:
        for table in ('sources','ideas'):
            values=server.objects(c,table)
            (out/(table+'.json')).write_text(json.dumps(values,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
            print(f'{table}: {len(values)}')
