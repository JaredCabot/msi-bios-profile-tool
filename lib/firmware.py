"""Read what the tool needs from an MSI (AMI Aptio V) BIOS image: the setup menus and the factory defaults.

The image is unpacked with UEFIExtract ('unpack' mode, which writes one flat folder and keeps Windows paths
short). Modules that carry HII forms are turned into text with IFRExtractor-RS and parsed by ifrparse.
The factory defaults ("Load Optimized Defaults") are read directly from the StdDefaults entry of the NVRAM
store. Results are cached per image in cache/<board>_<version>_<hash>/ so each BIOS is unpacked only once.
"""
import glob, hashlib, json, os, re, shutil, struct, subprocess, tempfile, uuid

from . import VERSION, ifrparse, deps
from .paths import APP_DIR, write_atomic

CACHE = os.path.join(APP_DIR, 'cache')
CACHE_FORMAT = 3       # bump when the parsers change what they read; a new tool version also starts a fresh cache


class FirmwareError(Exception):
    pass


def tool(name):
    p = deps.find(name)
    if not p:
        raise FirmwareError(f'{deps.DEPS[name]["title"]} is not installed. Restart the tool to download it.')
    return p


def image_version(path):
    """('E7E49AMSI', '2A25', 'date string') from the version string inside the image, or None."""
    with open(path, 'rb') as f:
        m = re.search(rb'(E[0-9A-Z]{4,6}[A-Z]{3})\.([0-9A-Z]{4}) (\d\d/\d\d/\d{4})', f.read())
    return tuple(g.decode() for g in m.groups()) if m else None


def find_images(folder):
    """{(board, version): path} for every BIOS image under folder (by MSI's file name pattern, size, then content).
    Folders are walked in name order, so with two copies of one version the same one is always used."""
    found = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d.lower() not in ('cache', 'bin', '__pycache__'))
        for fn in sorted(files):
            p = os.path.join(root, fn)
            try:
                if not re.match(r'^E[0-9A-Z]{4,6}[A-Z]{3}\.[0-9A-Z]{3,4}$', fn, re.I) or os.path.getsize(p) not in (16 << 20, 32 << 20, 64 << 20):
                    continue
                v = image_version(p)
            except OSError:
                continue
            if v:
                found.setdefault(v[:2], p)
    return found


# ---------------------------------------------------------------- NVRAM (NVAR) store

def _guid(b):
    return str(uuid.UUID(bytes_le=bytes(b))).upper()


def parse_nvar(buf, store):
    """Entries of an AMI NVAR store region. store = the whole NVRAM store body (its GUID table is at the end)."""
    out, pos = [], 0
    while pos + 10 <= len(buf) and buf[pos:pos + 4] == b'NVAR':
        size, = struct.unpack_from('<H', buf, pos + 4)
        nxt = int.from_bytes(buf[pos + 6:pos + 9], 'little')
        attr = buf[pos + 9]
        if size < 10 or pos + size > len(buf):
            break
        h, stop = pos + 10, pos + size
        if not attr & 0x08:                                  # not a data-only update
            try:
                if attr & 0x04:
                    guid = _guid(buf[h:h + 16]); h += 16
                else:
                    gi = buf[h]; h += 1
                    guid = _guid(store[len(store) - 16 * (gi + 1):len(store) - 16 * gi])
            except ValueError:                               # GUID cut short: not a usable entry
                pos += size
                continue
            if attr & 0x02:
                end = buf.find(b'\x00', h, stop)
            else:
                end = h
                while end + 1 < stop and buf[end:end + 2] != b'\x00\x00': end += 2
                end = end if end + 1 < stop else -1
            if end < 0:                                      # name runs past the entry: skip it
                pos += size
                continue
            if attr & 0x02:
                name = buf[h:end].decode('ascii', 'replace'); h = end + 1
            else:
                name = buf[h:end].decode('utf-16-le', 'replace'); h = end + 2
            data = buf[h:stop]
            if attr & 0x10 and len(data) >= 2:               # extended header at the end
                ext = struct.unpack_from('<H', data, len(data) - 2)[0]
                data = data[:len(data) - ext] if 0 < ext <= len(data) else data
            # follow the update chain to the newest data
            p2, n2 = pos, nxt
            while n2 not in (0xFFFFFF, 0) and p2 + n2 + 10 <= len(buf) and buf[p2 + n2:p2 + n2 + 4] == b'NVAR':
                p2 += n2
                s2, = struct.unpack_from('<H', buf, p2 + 4)
                a2 = buf[p2 + 9]
                n2 = int.from_bytes(buf[p2 + 6:p2 + 9], 'little')
                if a2 & 0x08:
                    data = buf[p2 + 10:p2 + s2]
            if attr & 0x80:
                out.append((name, guid, bytes(data)))
        pos += size
    return out


def read_defaults(image_path, dumpdir):
    """{(name, GUID): bytes} from StdDefaults. The NVRAM store's position comes from UEFIExtract's info file."""
    infos = glob.glob(os.path.join(dumpdir, 'File_Raw_*_NVAR_store_info.txt'))
    if not infos:
        raise FirmwareError('No NVRAM store found in the image.')
    with open(image_path, 'rb') as f:
        image = f.read()
    for info in infos:
        with open(info, encoding='utf-8', errors='replace') as f:
            t = dict(l.split(': ', 1) for l in f.read().splitlines() if ': ' in l)
        base = int(t['Base'].split('h')[0], 16)
        hdr = int(t['Header size'].split('h')[0], 16)
        body = int(t['Body size'].split('h')[0], 16)
        store = image[base + hdr:base + hdr + body]
        for name, guid, data in parse_nvar(store, store):
            if name == 'StdDefaults':
                return {f'{n}|{g}': d.hex() for n, g, d in parse_nvar(data, data)}   # the defaults carry their own GUID table
    raise FirmwareError('No StdDefaults (factory defaults) entry in the NVRAM store.')


# ---------------------------------------------------------------- AMD CBS layout IDs

CBS_ID = re.compile(rb'\xc7\x01(....)\xc7\x41\x08(....)\x44\x89\x59\x10', re.S)


def cbs_ids(dumpdir):
    """{'RPL': ['d1e4bf25'...]}: the two 32-bit values AMD CBS writes at offsets 0 and 8 of its settings store
    (AmdSetupRPL etc.). They identify the store layout of that BIOS build; a store whose values don't match is
    replaced by CBS defaults at boot, so a converted profile must carry the target BIOS's values."""
    out = {}
    for p in glob.glob(os.path.join(dumpdir, 'Section_PE32_image_*_CbsBaseDxe*_body.bin')):
        m = re.search(r'_CbsBaseDxe(\w+?)(_\d{3})?_body\.bin$', os.path.basename(p))
        with open(p, 'rb') as f:
            hits = {(a.hex(), b.hex()) for a, b in CBS_ID.findall(f.read())}
        if m and len(hits) == 1:
            out[m.group(1)] = list(hits.pop())
    return out


# ---------------------------------------------------------------- unpack + cache

def _run(args, cwd=None):
    r = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    return r.returncode, r.stdout


def load(image_path, log=print):
    """BIOS data for an image: dict(board, version, date, menus=[formsets], defaults={(name,guid): bytes})."""
    v = image_version(image_path)
    if not v:
        raise FirmwareError(f'{image_path} does not look like an MSI BIOS image (no version string found).')
    board, version, date = v
    with open(image_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:12]
    cdir = os.path.join(CACHE, f'{board}_{version}_{digest}')
    cfile = os.path.join(cdir, 'bios.json')
    try:
        with open(cfile, encoding='utf-8') as f:
            d = json.load(f)
        if d.get('format') == CACHE_FORMAT and d.get('tool') == VERSION:
            return _finish(d)
    except (OSError, ValueError):
        pass                                                         # missing, damaged or old: unpack again
    log(f'Unpacking BIOS {version} (first time only, takes about a minute)...')
    work = tempfile.mkdtemp(prefix='msib')
    try:
        img = os.path.join(work, 'b.bin')
        shutil.copyfile(image_path, img)
        rc, out = _run([tool('uefiextract'), img, 'unpack'], cwd=work)
        dump = img + '.dump'
        if not os.path.isdir(dump):
            raise FirmwareError(f'UEFIExtract did not unpack the image (exit code {rc}):\n' + out[-2000:])
        defaults = read_defaults(img, dump)
        ifr = os.path.join(work, 'ifr')
        os.makedirs(ifr)
        mods = {}
        for p in sorted(glob.glob(os.path.join(dump, 'Section_PE32_image_*_body.bin'))):
            m = re.match(r'Section_PE32_image_[0-9A-F-]{36}_(.+?)(_\d{3})?_body\.bin$', os.path.basename(p))
            if not m or m.group(1) in mods:
                continue
            _, out = _run([tool('ifrextractor'), p, 'list'])      # exits with 2 for a module without menus
            if re.search(r'UEFI HII form packages:\s*\n\s*Index', out):
                mods[m.group(1)] = p
        log(f'  {len(mods)} modules with setup menus')
        cbs = cbs_ids(dump)
        unread = []
        for name, p in mods.items():
            shutil.copyfile(p, os.path.join(ifr, name + '.efi'))
            rc, out = _run([tool('ifrextractor'), name + '.efi', 'verbose'], cwd=ifr)
            if rc or not glob.glob(os.path.join(glob.escape(ifr), glob.escape(name) + '.efi.*.ifr.txt')):
                log(f'  WARNING: IFRExtractor could not read the menus in {name} (exit code {rc}): {out.strip()[-300:]}')
                unread.append(name)
        menus = ifrparse.parse_dir(ifr)
        if not menus:
            raise FirmwareError('No setup menus could be read from the image.')
        d = dict(format=CACHE_FORMAT, tool=VERSION, board=board, version=version, date=date,
                 menus=menus, defaults=defaults, cbs_ids=cbs, unread=unread)
        shutil.rmtree(cdir, ignore_errors=True)                      # anything an older version left there
        os.makedirs(cdir)
        write_atomic(cfile, json.dumps(d).encode('utf-8'))
        return _finish(d)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _finish(d):
    d['defaults'] = {tuple(k.split('|', 1)): bytes.fromhex(v) for k, v in d['defaults'].items()}
    return d
