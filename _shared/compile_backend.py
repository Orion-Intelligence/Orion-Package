import os
from pathlib import Path
import runpy
import shutil

from Cython.Build import cythonize
from setuptools import Extension, setup

root = Path('/build/app')
os.chdir(root)

runpy.run_path('/build/prepare.py')

modules = sorted(root.rglob('*.py'))
extensions = [Extension('.'.join(p.relative_to(root).with_suffix('').parts), [str(p)],
                        extra_compile_args=['-O2', '-g0', '-fvisibility=hidden'], extra_link_args=['-s'])
              for p in modules]
setup(name='orion-compiled', ext_modules=cythonize(
    extensions, compiler_directives={'language_level': 3, 'annotation_typing': False, 'binding': True}),
    script_args=['build_ext', '--build-lib', '/release', '--parallel', '2'])
assert len(list(Path('/release').rglob('*.so'))) == len(modules), 'Incomplete compilation'


for path in root.rglob('*'):
    if not path.is_file() or path.suffix in {'.py', '.pyc', '.pyo', '.c', '.h', '.o'}:
        continue
    relative = path.relative_to(root)
    if 'build' in relative.parts or '__pycache__' in relative.parts:
        continue
    target = Path('/release') / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
