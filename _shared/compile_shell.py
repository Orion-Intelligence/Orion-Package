import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile


def encode(source):
    payload = source.read_bytes()
    key = hashlib.sha256(payload).digest()
    encoded = bytes(value ^ key[index % len(key)] for index, value in enumerate(payload))
    values = ','.join(str(value) for value in encoded)
    secret = ','.join(str(value) for value in key)
    return f'''#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
static unsigned char payload[] = {{{values},0}};
static const unsigned char key[] = {{{secret}}};
int main(int argc, char **argv) {{
    size_t size = sizeof(payload) - 1;
    for (size_t index = 0; index < size; ++index) payload[index] ^= key[index % sizeof(key)];
    char **args = calloc((size_t)argc + 4, sizeof(char *));
    if (!args) return 111;
    args[0] = "/bin/sh";
    args[1] = "-c";
    args[2] = (char *)payload;
    args[3] = argv[0];
    for (int index = 1; index < argc; ++index) args[index + 3] = argv[index];
    execv(args[0], args);
    perror("execv");
    return 111;
}}
'''


def compile_script(source, destination):
    with tempfile.TemporaryDirectory() as directory:
        generated = Path(directory) / 'launcher.c'
        generated.write_text(encode(source))
        subprocess.run(('gcc', '-O2', '-fno-ident', '-fvisibility=hidden', '-s',
                        str(generated), '-o', str(destination)), check=True)


if __name__ == '__main__':
    arguments = sys.argv[1:]
    if not arguments or len(arguments) % 2:
        raise SystemExit('usage: compile_shell.py SOURCE DESTINATION [...]')
    for offset in range(0, len(arguments), 2):
        compile_script(Path(arguments[offset]), Path(arguments[offset + 1]))
