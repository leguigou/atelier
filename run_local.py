"""Start the password-protected LAN service with private per-machine settings."""
import os, sys, json, runpy
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'.runtime'))
config=json.loads((root/'.local-config.json').read_text(encoding='utf-8'))
os.environ.update(config)
sys.path.insert(0,str(root))
runpy.run_module('server',run_name='__main__',alter_sys=True)
