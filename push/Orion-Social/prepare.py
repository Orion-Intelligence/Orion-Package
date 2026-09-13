import json
from pathlib import Path
import shutil
import subprocess

automation = Path('/build/app/social-automation')
subprocess.run(['npm', 'ci', '--prefix', str(automation)], check=True)
for entry in ('publish/post', 'ad-detection/detect-ads'):
    subprocess.run([str(automation / 'node_modules/.bin/esbuild'), f'src/{entry}.ts',
                    '--bundle', '--minify', '--platform=node', '--format=esm',
                    '--packages=external', '--legal-comments=none', f'--outfile=dist/{entry}.js'],
                   cwd=automation, check=True)
manifest = json.loads((automation / 'package.json').read_text())
manifest['scripts'] = {'social:post': 'node dist/publish/post.js',
                       'social:detect-ads': 'node dist/ad-detection/detect-ads.js'}
(automation / 'package.json').write_text(json.dumps(manifest))
subprocess.run(['npm', 'prune', '--omit=dev', '--prefix', str(automation)], check=True)
shutil.rmtree(automation / 'src')
