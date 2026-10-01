#!/usr/bin/env python3
"""
StudyFlow package entry point (for python -m studyflow).
"""
import sys
from pathlib import Path

# Ensure root directory is in sys.path
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from study_timer import main

if __name__ == "__main__":
    main()
