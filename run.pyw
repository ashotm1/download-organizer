"""Windowless launcher (pythonw). Used by the startup shortcut."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from organizer.__main__ import main

main()
