"""Check application startup with the modules actually copied into the image."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DeploymentTests(unittest.TestCase):
    def test_docker_copy_starts_in_an_isolated_directory(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            for line in (root/'Dockerfile').read_text().splitlines():
                if not line.startswith('COPY '):continue
                sources=line.split()[1:-1]
                for name in sources:
                    source=root/name
                    if source.is_dir():shutil.copytree(source,target/name)
                    else:shutil.copy2(source,target/source.name)
            env={**os.environ,'PYTHONPATH':str(root/'.runtime'),'ATELIER_DATA':str(target/'data'),'ADMIN_PASSWORD':'','ATELIER_ENCRYPTION_KEY':'','DEEPSEEK_API_KEY':''}
            result=subprocess.run([sys.executable,'-c','import server; server.init(); assert server.studio.books(); print("isolated startup OK")'],cwd=target,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('isolated startup OK',result.stdout)


if __name__=='__main__':unittest.main()
