"""Where the tool keeps its files, run from source or as a built program.

APP_DIR  holds what the tool writes and keeps: settings.json, bin/ (the two downloaded programs) and cache/.
         Run from source, that is the folder with msibios.py; as a built program, the folder with the program
         file, so it stays portable either way.
RES_DIR  holds the files that ship with the tool (lib/biosread.ps1, lib/varlist.txt). For a one-file build
         PyInstaller unpacks them to a temporary folder for as long as the program runs.
"""
import os, sys

FROZEN = bool(getattr(sys, 'frozen', False))
if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_DIR = getattr(sys, '_MEIPASS', APP_DIR)


def resource(*parts):
    return os.path.join(RES_DIR, *parts)


def write_atomic(path, data):
    """Write bytes so that an interrupted write never leaves a half-written file behind."""
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)
