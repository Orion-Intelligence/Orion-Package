from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.environment import cli

if __name__ == '__main__':
    cli('Orion-mail')
