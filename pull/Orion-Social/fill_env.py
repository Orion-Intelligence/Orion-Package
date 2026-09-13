#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared.env_filler import main

if __name__ == '__main__':
    main('Orion-Social')
