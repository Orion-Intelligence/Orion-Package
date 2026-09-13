from pathlib import Path
import ast



path = Path('/build/app/orion/api/server/entity_manager/entity_manager.py')
source = path.read_text()
before = '            for field, additions in (merge_arrays or {}).items():\n'
after = ('            _compiled_merge_arrays = merge_arrays or {}\n'
         '            for field, additions in _compiled_merge_arrays.items():\n')
if source.count(before) != 1:
    raise RuntimeError('Review compiled graph iterator: upstream source changed')
path.write_text(source.replace(before, after))



path = Path('/build/app/orion/services/mongo_manager/shared_model/db_auth_models.py')
source = path.read_text()
model = next(node for node in ast.parse(source).body
             if isinstance(node, ast.ClassDef) and node.name == 'db_user_account')
methods = [node for node in model.body if isinstance(node, ast.FunctionDef)
           and not node.decorator_list and not node.name.startswith('__')]
if {node.name for node in methods} != {'is_admin', 'is_crawler', 'is_demo', 'verify_2fa', 'provisioning_uri'}:
    raise RuntimeError('Review compiled ODMantic model methods: upstream source changed')
lines = source.splitlines(keepends=True)
for node in reversed(methods):
    lines.insert(node.lineno - 1, '    @_native_model_method\n')
source = ''.join(lines)
bridge = '''
from functools import wraps

def _native_model_method(method):
    namespace = {'compiled': method}
    exec('def bridge(self, *args, **kwargs):\\n    return compiled(self, *args, **kwargs)', namespace)
    return wraps(method)(namespace['bridge'])

'''
path.write_text(source.replace('class db_user_account(Model):', bridge + 'class db_user_account(Model):'))

path = Path('/build/app/routes/crawl_routes.py')
source = path.read_text()
before = 'from orion.api.server.crawl_manager.class_model.__init__ import *'
if source.count(before) != 1:
    raise RuntimeError('Review compiled crawl-model package import: upstream source changed')
path.write_text(source.replace(before, 'from orion.api.server.crawl_manager.class_model import *'))
