"""The two outside programs the tool needs, where to find them, and how to fetch them.

Both are downloaded from their official GitHub releases. The versions are fixed and every download is checked
against the SHA-256 value published on the release page before anything is unpacked.
"""
import hashlib, io, os, platform, shutil, stat, sys, urllib.request, zipfile

from .paths import APP_DIR

BIN = os.path.join(APP_DIR, 'bin')

DEPS = {
    'uefiextract': dict(
        title='UEFIExtract (UEFITool NE A75)', licence='BSD 2-clause',
        page='https://github.com/LongSoft/UEFITool/releases/tag/A75',
        assets={
            'windows': ('https://github.com/LongSoft/UEFITool/releases/download/A75/UEFIExtract_NE_A75_win64.zip',
                        '20ff18208913d32c99e3b002717abeddaa3b6509ac62e6699e462b0f533be646', 'UEFIExtract.exe'),
            'linux': ('https://github.com/LongSoft/UEFITool/releases/download/A75/UEFIExtract_NE_A75_x64_linux.zip',
                      '5ee05d0da0c235626de67959d6cd97767e0d7ac67d42c8839e5972e8c23fd5a5', 'uefiextract'),
        }),
    'ifrextractor': dict(
        title='IFRExtractor-RS 1.6.1', licence='BSD 2-clause',
        page='https://github.com/LongSoft/IFRExtractor-RS/releases/tag/v1.6.1',
        assets={
            'windows': ('https://github.com/LongSoft/IFRExtractor-RS/releases/download/v1.6.1/ifrextractor_1.6.1_windows.zip',
                        '3a0d93ecd3a4cb092d210c499d125ffd782982311f5f8dc40a8b180b58c4ffe7', 'ifrextractor.exe'),
            'linux': ('https://github.com/LongSoft/IFRExtractor-RS/releases/download/v1.6.1/ifrextractor_1.6.1_linux.zip',
                      '5a18e253e560270387657d0165f317d7319cf6296cd5e58b1f13074557514c57', 'ifrextractor'),
        }),
}


class DependencyError(Exception):
    pass


def os_key():
    if os.name == 'nt':
        return 'windows'
    if sys.platform.startswith('linux') and platform.machine().lower() in ('x86_64', 'amd64'):
        return 'linux'
    return None


def platform_dir():
    """bin/<windows|linux>, so one copy of the tool can carry the programs for several systems."""
    return os.path.join(BIN, os_key() or 'other')


def exe_name(dep):
    k = os_key()
    if k:
        return DEPS[dep]['assets'][k][2]
    return dep


def find(dep):
    """Path of the program in bin/<system>/, or None. The system PATH is not searched: a copy found there could be
    any version, and its output decides where every setting is stored."""
    p = os.path.join(platform_dir(), exe_name(dep))
    return p if os.path.isfile(p) else None


def missing():
    return [d for d in DEPS if not find(d)]


def _install_zip(dep, blob, expect_sha):
    got = hashlib.sha256(blob).hexdigest()
    if got != expect_sha:
        raise DependencyError(f'{DEPS[dep]["title"]}: the download does not match the published SHA-256 '
                              f'(expected {expect_sha[:16]}..., got {got[:16]}...). Nothing was installed.')
    name = exe_name(dep)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        member = next((m for m in z.namelist() if os.path.basename(m) == name), None)
        if not member:
            raise DependencyError(f'{name} is not in the downloaded archive.')
        os.makedirs(platform_dir(), exist_ok=True)
        dst = os.path.join(platform_dir(), name)
        with z.open(member) as src, open(dst, 'wb') as out:
            shutil.copyfileobj(src, out)
    if os.name != 'nt':
        os.chmod(dst, os.stat(dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def download(dep, log=print):
    k = os_key()
    if not k:
        raise DependencyError(f'No ready-made {DEPS[dep]["title"]} for this system ({sys.platform} {platform.machine()}). '
                              f'Build it from source ({DEPS[dep]["page"]}) and put it in {platform_dir()}.')
    url, sha, _ = DEPS[dep]['assets'][k]
    log(f'  Downloading {DEPS[dep]["title"]} from {url.split("/download/")[0]} ...')
    req = urllib.request.Request(url, headers={'User-Agent': 'msi-bios-tool'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read(50 << 20)
    except Exception as e:
        raise DependencyError(f'Download failed ({e}). You can download {os.path.basename(url)} yourself from '
                              f'{DEPS[dep]["page"]} , check it against the SHA-256 there and put the program in {platform_dir()}.')
    dst = _install_zip(dep, blob, sha)
    log(f'  Checked (SHA-256 matches the release page) and installed: {dst}')
    return dst


def describe():
    return '\n'.join(f'  {info["title"]:34} {find(d) or "MISSING"}' for d, info in DEPS.items())
