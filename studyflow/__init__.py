"""
StudyFlow — Minimalist Study Timer & Session Tracker
"""

__version__ = "1.0.0"
__author__ = "Shubbo"

import sys
from pathlib import Path

# Ensure package root is resolvable
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from study_timer import main

__all__ = ["main", "__version__", "__author__"]
