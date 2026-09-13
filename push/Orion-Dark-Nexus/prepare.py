import ast
from pathlib import Path
import zlib

manager = Path('/build/app/dark_nexus_sandbox')
payloads = {p.name: zlib.compress(memoryview(p.read_bytes()), 9)
            for p in (manager / 'worker_scripts').glob('*.py')}
constants = manager / 'sandbox_constants/worker_constants.py'
payloads[constants.name] = zlib.compress(memoryview(constants.read_bytes()), 9)
(manager / '_worker_payloads.py').write_text(
    'import zlib\nPAYLOADS = ' + repr(payloads) + '\ndef read(name):\n    return zlib.decompress(PAYLOADS[name])\n')
service = manager / 'sandbox_services/workspace_service.py'
source = service.read_text()
method = next(node for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.FunctionDef) and node.name == '_worker_files')
assert isinstance(method, ast.FunctionDef) and method.end_lineno is not None, 'Review worker method: source changed'
lines = source.splitlines(keepends=True)
lines[method.lineno - 1:method.end_lineno] = [
    '    def _worker_files(self, name):\n'
    '        from dark_nexus_sandbox._worker_payloads import read\n'
    '        files = {str(WORKER_SCRIPT_DIRECTORY / name): read(name),\n'
    '                 str(WORKER_CONSTANTS_DIRECTORY / "worker_constants.py"): read("worker_constants.py")}\n'
    '        if name == "import_repository.py":\n'
    '            files[str(WORKER_SCRIPT_DIRECTORY / "safe_redirect_handler.py")] = read("safe_redirect_handler.py")\n'
    '        return files\n'
]
service.write_text(''.join(lines))
server = Path('/build/app/api/mcp2/server.py')
source = server.read_text()
guard = 'if __name__ == "__main__":'
assert source.count(guard) == 1, 'Review MCP entrypoint: source changed'
source = source.replace(guard, 'def main():')


bridge = '''
import inspect
from typing import get_type_hints

def _native_callback(function):
    original = inspect.unwrap(function)
    namespace = dict(original.__globals__, _compiled_callback=function)
    annotations = get_type_hints(original)
    signature = inspect.signature(function)
    signature = signature.replace(
        parameters=[parameter.replace(annotation=annotations.get(name, parameter.annotation))
                    for name, parameter in signature.parameters.items()],
        return_annotation=annotations.get('return', signature.return_annotation))
    asynchronous = inspect.iscoroutinefunction(function)
    prefix, awaiter = ('async ', 'await ') if asynchronous else ('', '')
    exec(prefix + 'def callback(*args, **kwargs):\\n    return ' + awaiter + '_compiled_callback(*args, **kwargs)', namespace)
    callback = namespace['callback']
    callback.__signature__ = signature
    callback.__annotations__ = annotations
    callback.__name__ = function.__name__
    callback.__module__ = function.__module__
    callback.__doc__ = function.__doc__
    return callback

class _CompiledMCPServer(MCPServer):
    def resource(self, *args, **kwargs):
        decorator = super().resource(*args, **kwargs)
        return lambda function: decorator(_native_callback(function))

    def prompt(self, *args, **kwargs):
        decorator = super().prompt(*args, **kwargs)
        return lambda function: decorator(_native_callback(function))

    def tool(self, *args, **kwargs):
        decorator = super().tool(*args, **kwargs)
        return lambda function: decorator(_native_callback(function))

'''
assert source.count('mcp = MCPServer(') == 1, 'Review MCP registration: source changed'
server.write_text(source.replace('mcp = MCPServer(', bridge + 'mcp = _CompiledMCPServer('))


chat = Path('/build/app/api/mcp2/orion/llm_core/llm_bridge/chat_model.py')
source = chat.read_text()
declaration = 'class OrionChatOllama(ChatOllama):\n'
assert source.count(declaration) == 1, 'Review compiled chat model: source changed'
chat.write_text(source.replace(declaration, declaration + '    model_config = {"ignored_types": (type(lambda: None),)}\n'))


model = Path('/build/app/api/mcp2/orion/shared/pentest/javascript_secret_scan/javascript_secret_scan_model.py')
source = model.read_text()
if 'from urllib.parse import urlsplit' not in source:
    assert source.count('import re\n') == 1, 'Review JavaScript model imports: source changed'
    model.write_text(source.replace('import re\n', 'import re\nfrom urllib.parse import urlsplit\n'))
