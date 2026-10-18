# -*- mode: python ; coding: utf-8 -*-
# Builds the tool as one self-contained program, so a user needs no Python.
#
#   pyinstaller --noconfirm --clean "MSI BIOS Profile Tool.spec"
#
# The result is dist/MSI BIOS Profile Tool.exe on Windows and
# dist/MSI BIOS Profile Tool on Linux. PyInstaller cannot cross-compile, so
# each is built on the system it is for (see .github/workflows/release.yml).
import sys

# Files the tool reads at run time. In a one-file build they are unpacked to a
# temporary folder while the program runs; lib/paths.py finds them there.
datas = [('lib/biosread.ps1', 'lib'), ('lib/varlist.txt', 'lib')]

a = Analysis(
    ['msibios.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here draws a window; leaving Tk out keeps the program small.
    excludes=['tkinter', '_tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MSI BIOS Profile Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed programs are flagged by more virus scanners, and the saving
    # is small for a program this size.
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt' if sys.platform == 'win32' else None,
)
