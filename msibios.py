#!/usr/bin/env python3
"""MSI BIOS profile tool: read MSI OC profiles (.ocb), explain every setting, and move a profile to another BIOS version.

Run the built program from the Releases page, or start this file with Python: double-click it on Windows, or run
`python3 msibios.py` (or `./msibios.py`) on Linux. It looks for profiles and BIOS files in the library folder it
asks for on first run, and writes reports to the library's 'reports' folder.
"""
import sys

if sys.version_info < (3, 9):
    print('MSI BIOS Profile Tool needs Python 3.9 or later; this is Python %d.%d.' % sys.version_info[:2])
    input('Press Enter to close.')
    sys.exit(1)

import glob, json, os, re, subprocess, traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import VERSION, firmware, ocb, model, convert, report, deps, paths   # noqa: E402

HERE = paths.APP_DIR          # where settings.json, bin/ and cache/ live
SETTINGS_FILE = os.path.join(HERE, 'settings.json')
label = ocb.label

try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass
if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW('MSI BIOS Profile Tool')
    except Exception:
        pass


# ------------------------------------------------------------------ settings and small helpers

def load_settings():
    s = dict(library='')
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    paths.write_atomic(SETTINGS_FILE, json.dumps(s, indent=1).encode('utf-8'))


def store_path(p):
    """Keep folders next to the tool as relative paths, so the whole folder can be moved or copied to a USB stick."""
    p = os.path.abspath(p)
    try:
        rel = os.path.relpath(p, HERE)
        if not rel.startswith('..' + os.sep + '..' + os.sep + '..'):
            return rel
    except ValueError:                       # another drive
        pass
    return p


def full_path(p):
    return os.path.normpath(os.path.join(HERE, p)) if p and not os.path.isabs(p) else p


S = load_settings()


def library():
    return full_path(S['library'])


def reports_dir():
    d = os.path.join(library(), 'reports')
    os.makedirs(d, exist_ok=True)
    return d


def say(*a):
    print(*a, flush=True)


def ask(prompt, default=''):
    try:
        v = input(f'{prompt}{f" [{default}]" if default else ""}: ').strip().strip('"')
    except EOFError:
        # No console to answer from (input piped or redirected): stop rather than guess an answer.
        raise SystemExit(f'\nNo answer to "{prompt}": the tool needs a console to ask its questions.')
    return v or default


def yes(prompt, default='n'):
    return ask(prompt + ' (y/n)', default).lower().startswith('y')


def pick(title, options, allow_path=False):
    """Numbered choice. options = [(label, value)]. Returns value, a typed path, or None."""
    say(f'\n{title}')
    for i, (text, _) in enumerate(options, 1):
        say(f'  {i:2}. {text}')
    hint = 'number' + (', or a full path' if allow_path else '') + ', Enter to go back'
    v = ask(f'Choose ({hint})')
    if not v:
        return None
    if v.isdigit() and 1 <= int(v) <= len(options):
        return options[int(v) - 1][1]
    if allow_path and os.path.isfile(v):
        return v
    say('  Not a valid choice.')
    return None


def find_profiles():
    out = []
    for root, dirs, files in os.walk(library()):
        dirs[:] = [d for d in dirs if d.lower() not in ('cache', 'bin', '__pycache__')]
        out += [os.path.join(root, fn) for fn in files if fn.lower().endswith('.ocb')]
    return sorted(out, key=os.path.getmtime, reverse=True)


def choose_profile(title='Profiles (.ocb) in the library, newest first:'):
    opts = []
    for p in find_profiles():
        try:
            pr = ocb.Profile.load(p)
            opts.append((f'{os.path.relpath(p, library())}   (BIOS {label(pr.version)}, saved {pr.saved})', p))
        except Exception as e:
            opts.append((f'{os.path.relpath(p, library())}   (unreadable: {e})', p))
    if not opts:
        say(f'\nNo .ocb files found under {library()}.')
    return pick(title, opts, allow_path=True)


_images = None


def images(refresh=False):
    global _images
    if _images is None or refresh:
        _images = firmware.find_images(library())
    return _images


def bios_for(board, version, purpose):
    p = images().get((board, version))
    if not p:
        say(f'\nNo BIOS file for {board} {label(version)} was found under {library()}.')
        p = ask(f'Path to the {label(version)} BIOS file ({purpose}), or Enter to cancel')
        if not p or not os.path.isfile(p):
            return None
        v = firmware.image_version(p)
        if not v or (v[0], v[1]) != (board, version):
            say(f'  That file is {v[0] + " " + label(v[1]) if v else "not an MSI BIOS image"}, not {board} {label(version)}.')
            return None
    return firmware.load(p, log=say)


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', '_', s)


def open_file(path):
    if os.name == 'nt' and yes('Open it now?', 'y'):
        os.startfile(path)


def write_reports(out, bios, rows, quiet=False, **html):
    """The HTML report and the CSV beside it; returns the report path."""
    problems = model.layout_problems(bios)
    for t in problems:
        say(f'\nWARNING: {t}')
    if problems:
        html['callouts'] = [('warn', 'Menu layout not recognised', problems)] + list(html.get('callouts', ()))
    counts = report.write_html(out, rows, **html)
    csv_path = os.path.splitext(out)[0] + '.csv'
    report.write_csv(csv_path, rows)
    say(f"\n{counts['changed']} settings differ from default, out of {counts['live']} on MSI's pages.")
    say(f'Report: {out}')
    say(f'Table:  {csv_path}')
    if not quiet:
        open_file(out)
    return out


# ------------------------------------------------------------------ actions

def decode_profile(path=None, quiet=False):
    path = path or choose_profile()
    if not path:
        return None
    p = ocb.Profile.load(path)
    say('\n' + ocb.describe(p))
    if not p.checksum_ok:
        say('WARNING: the checksum does not match; the file may be damaged.')
    bios = bios_for(p.board, p.version, 'the BIOS the profile was saved on')
    if not bios:
        return None
    rows = model.decode(bios, model.stores_from_profile(p, bios))
    stem = safe_name(os.path.splitext(os.path.basename(path))[0])
    return write_reports(
        os.path.join(reports_dir(), f'{stem} - settings.html'), bios, rows, quiet,
        title=os.path.basename(path), eyebrow=f'MSI {p.board} · BIOS settings',
        meta=[f'BIOS {label(p.version)} ({bios["date"]})', f'Saved {p.saved}', p.cpu],
        intro=['Every setting stored in this profile, decoded with the menus of the BIOS it was saved on. '
               '"Changed" lists the settings that differ from the factory defaults: after "Load Optimized Defaults", '
               'these are the ones to set by hand. Open "About this setting" for MSI\'s help text and the options.'],
        storage_key=f'{stem}|{p.version}')


def decode_windows_read(path):
    cur, meta = model.stores_from_vars(path)
    ver = (meta.get('bios') or '').replace('.', '')
    board = meta.get('board') or 'this board'
    code = re.search(r'MS-([0-9A-Z]{4})', board, re.I)           # "MPG X870E CARBON MAX WIFI (MS-7E49)"
    boards = sorted({b for b, v in images() if v == ver and (not code or code.group(1).upper() in b)})
    if not boards:
        say(f'No BIOS file for {board}, version {meta.get("bios")}, was found in the library. Add it and try again.'); return
    if len(boards) > 1:
        say(f'The library has BIOS {meta.get("bios")} for several boards ({", ".join(boards)}) and the read does not say '
            'which board this is. Move the ones for other boards out of the library and try again.'); return
    bios = bios_for(boards[0], ver, 'the BIOS that was running')
    if not bios:
        return
    rows = model.decode(bios, cur)
    taken = meta.get('taken', '').replace('T', ' ')
    stem = 'Windows read ' + safe_name(taken.replace(':', '-'))
    write_reports(os.path.join(reports_dir(), f'{stem} - settings.html'), bios, rows,
                  title=f'Settings read {taken}', eyebrow=f'MSI {boards[0]} · BIOS settings',
                  meta=[f'BIOS {meta.get("bios")}', meta.get('board', ''), f'Read {taken}'],
                  intro=['Settings read through Windows, decoded with the menus of the BIOS that was running. '
                         'Windows cannot read every settings store; settings it could not read are listed separately.'],
                  storage_key=stem)


def run_reader(outdir, listfile):
    """Run lib/biosread.ps1 in an administrator PowerShell (Windows shows its UAC prompt) and wait for it."""
    ps = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    q = lambda p: "'\"" + p.replace("'", "''") + "\"'"           # PowerShell single-quoted, with inner double quotes
    ps1 = paths.resource('lib', 'biosread.ps1')
    cmd = (f"Start-Process -FilePath {q(ps)} -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
           f"'-NoProfile','-ExecutionPolicy','Bypass','-File',{q(ps1)},'-OutDir',{q(outdir)},'-ListFile',{q(listfile)}")
    return subprocess.run([ps, '-NoProfile', '-Command', cmd])


def read_this_pc():
    """Read the live settings through Windows (administrator prompt), then decode them."""
    if os.name != 'nt':
        say('\nReading the live settings works on Windows only.'); return
    names = set()
    with open(paths.resource('lib', 'varlist.txt'), encoding='ascii') as f:
        names |= {tuple(l.strip().split('|')) for l in f if '|' in l}
    for cf in glob.glob(os.path.join(firmware.CACHE, '*', 'bios.json')):    # stores named by any BIOS used so far
        try:
            with open(cf, encoding='utf-8') as f:
                d = json.load(f)
            names |= {tuple(k.split('|', 1)) for k in d['defaults']}
            names |= {(v['name'], v['guid'].upper()) for fs in d['menus'] for v in fs['varstores'].values() if v['name'] and v['guid']}
        except (OSError, ValueError, KeyError):
            pass
    # A new folder for every read, so a read that fails can never leave an older result looking like its own.
    outdir = os.path.join(reports_dir(), 'Windows read ' + datetime.now().strftime('%Y-%m-%d %H-%M-%S'))
    os.makedirs(outdir)
    listfile = os.path.join(outdir, 'varlist.txt')
    with open(listfile, 'w', encoding='ascii', errors='ignore') as f:
        f.write('\n'.join(f'{n}|{g}' for n, g in sorted(names)) + '\n')
    say(f'\nReading {len(names)} settings stores. Windows asks for administrator rights; the script only reads.')
    r = run_reader(outdir, listfile)
    js = os.path.join(outdir, 'uefi-vars.json')
    if r.returncode != 0 or not os.path.exists(js):
        say('The read did not finish (the administrator prompt may have been declined).'); return
    say(f'Saved: {js}')
    decode_windows_read(js)


def convert_profile():
    path = choose_profile('Which profile do you want to convert?')
    if not path:
        return
    p = ocb.Profile.load(path)
    say('\n' + ocb.describe(p))
    if not p.checksum_ok and not yes('The checksum does not match. Continue anyway?'):
        return
    targets = sorted((v, img) for (b, v), img in images(refresh=True).items() if b == p.board and v != p.version)
    if not targets:
        say(f'\nNo other {p.board} BIOS versions found under {library()}. Add the new BIOS file there first.')
        return
    tv = pick('Convert to which BIOS version?', [(f'{label(v)}   ({os.path.relpath(img, library())})', v) for v, img in targets])
    if not tv:
        return
    old_bios = bios_for(p.board, p.version, 'source')
    new_bios = bios_for(p.board, tv, 'target')
    if not old_bios or not new_bios:
        return
    notes = []
    data, infos = convert.convert(p, old_bios, new_bios, lambda kind, text: notes.append((kind, text)))
    for kind, text in notes:
        say(f'\n{kind.upper()}: {text}')
    if any(kind == 'warn' for kind, _ in notes) and not yes('\nThe conversion needs checking (see above). Write the converted profile anyway?'):
        say('Nothing was written.')
        return
    base = os.path.basename(path)
    name = base.replace(p.version, tv) if p.version in base else os.path.splitext(base)[0] + f' {tv}.ocb'
    out = os.path.join(os.path.dirname(path), name)
    if os.path.abspath(out) == os.path.abspath(path):
        out = os.path.splitext(path)[0] + f' {tv}.ocb'
    if os.path.exists(out) and not yes(f'\n{name} already exists. Replace it?'):
        out = os.path.splitext(out)[0] + datetime.now().strftime(' %Y%m%d-%H%M%S') + '.ocb'
    paths.write_atomic(out, data)
    say(f'\nWrote {out}')
    q = ocb.Profile(data)
    old_rows = model.decode(old_bios, model.stores_from_profile(p, old_bios))
    new_rows = model.decode(new_bios, model.stores_from_profile(q, new_bios))
    callouts, badges, rnotes = convert.summarize(p, q, infos, notes, old_rows, new_rows)
    stem = safe_name(os.path.splitext(os.path.basename(out))[0])
    write_reports(os.path.join(reports_dir(), f'{stem} - conversion report.html'), new_bios, new_rows,
                  title=os.path.basename(out), eyebrow=f'MSI {q.board} · converted profile',
                  meta=[f'BIOS {label(q.version)} ({new_bios["date"]})', f'From {base}', f'Originally saved {p.saved}', q.cpu],
                  intro=['The converted profile decoded with the new BIOS menus. "Changed" lists the settings that differ from '
                         'the new factory defaults, plus anything the conversion flagged.'],
                  callouts=callouts, badges=badges, notes=rnotes, storage_key=f'{stem}|{q.version}')


def compare_profiles():
    a = choose_profile('First profile:')
    if not a: return
    b = choose_profile('Second profile:')
    if not b: return
    sets = []
    for path in (a, b):
        p = ocb.Profile.load(path)
        bios = bios_for(p.board, p.version, 'the BIOS the profile was saved on')
        if not bios: return
        rows = [r for r in model.decode(bios, model.stores_from_profile(p, bios)) if r['prompt'] and not r['other_cpu'] and not r['internal']]
        by = {}
        for r in sorted(rows, key=lambda r: (not r['reach'], r['offset'])):
            by.setdefault((r['store'], r['prompt'], model.path_s(r)), r)
        sets.append((p, by))
    (pa, A), (pb, B) = sets
    where = lambda k: f'{(k[2] or "(not on a menu page)").replace(" > ", " › ")} › {k[1]}'
    lines = [f'A: {os.path.basename(a)} (BIOS {label(pa.version)}, saved {pa.saved})',
             f'B: {os.path.basename(b)} (BIOS {label(pb.version)}, saved {pb.saved})', '']
    # Compared by what the setting shows, not the raw number: across BIOS versions the same number can mean
    # a different option.
    diff = [(k, A[k], B[k]) for k in A if k in B and A[k]['value_s'] != B[k]['value_s'] and (A[k]['reach'] or B[k]['reach'])]
    lines.append(f'{len(diff)} settings on screen differ:')
    lines += [f'  {where(k)}:  A = {ra["value_s"]}   B = {rb["value_s"]}' for k, ra, rb in sorted(diff, key=lambda x: x[0][2] or '')]
    for name, X, Y in (('A', A, B), ('B', B, A)):
        only = [k for k in X if k not in Y and X[k]['reach']]
        if only:
            lines += ['', f'Only in {name} ({len(only)}):'] + [f'  {where(k)} = {X[k]["value_s"]}' for k in only]
    text = '\n'.join(lines)
    say('\n' + text)
    out = os.path.join(reports_dir(), safe_name(f'compare {os.path.splitext(os.path.basename(a))[0]} vs {os.path.splitext(os.path.basename(b))[0]}.txt'))
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text + '\n')
    say(f'\nSaved to {out}')


def first_run():
    """Ask where the BIOS files and profiles are. The folder the tool is in is offered first."""
    say('\nFirst run. The tool keeps your BIOS files and profiles (.ocb) in one library folder, searched with its')
    say('subfolders, and writes reports to a "reports" folder inside it. Press Enter to use the folder the tool is in.')
    while True:
        v = ask('Library folder', HERE)
        if os.path.isdir(v):
            break
        if yes(f'{v} does not exist. Create it?', 'y'):
            try:
                os.makedirs(v); break
            except OSError as e:
                say(f'  Could not create it: {e}')
    S['library'] = store_path(v)
    save_settings(S)
    say('Saved in settings.json. To change it later, start the tool with --library "<folder>", or delete settings.json.')


def ensure_programs():
    """Offer to download UEFIExtract and IFRExtractor-RS when either is missing."""
    miss = deps.missing()
    if not miss:
        return
    say('\nPrograms the tool uses to unpack BIOS files:')
    say(deps.describe())
    say(f"\nMissing: {', '.join(deps.DEPS[d]['title'] for d in miss)}. The tool cannot read BIOS files without them.")
    say('They are free (BSD licence) and come from their official GitHub release pages; each download is checked')
    say('against the SHA-256 value published there. About 2 MB in total.')
    if yes('Download them now?', 'y'):
        for d in miss:
            try:
                deps.download(d, log=say)
            except deps.DependencyError as e:
                say(f'  {e}')
        say(deps.describe())
    else:
        say(f'Not downloaded. The tool asks again next time, or put the programs in {deps.platform_dir()} yourself.')


MENU = [
    ('Decode a profile into a readable report', decode_profile),
    ('Convert a profile to another BIOS version', convert_profile),
    ('Compare two profiles', compare_profiles),
    ('Read the settings from this PC (Windows, administrator)', read_this_pc),
]


def self_check():
    """For the release build: the bundle starts, knows its version and carries its own files."""
    need = [('lib', 'varlist.txt'), ('lib', 'biosread.ps1')]
    missing = [os.path.join(*f) for f in need if not os.path.isfile(paths.resource(*f))]
    say(f'MSI BIOS Profile Tool {VERSION} ({"built" if paths.FROZEN else "source"}), files: {"missing " + ", ".join(missing) if missing else "all present"}')
    return 1 if missing else 0


def main():
    args = sys.argv[1:]
    if args[:1] in (['--version'], ['-V']):
        say(f'MSI BIOS Profile Tool {VERSION}'); return
    if args[:1] == ['--check']:
        sys.exit(self_check())
    if '--library' in args:                                   # msibios.py --library "<folder>"
        i = args.index('--library')
        if i + 1 < len(args) and os.path.isdir(args[i + 1]):
            S['library'] = store_path(args[i + 1]); save_settings(S)
        del args[i:i + 2]
    if not S['library'] or not os.path.isdir(library()):
        first_run()
    if len(args) == 2 and args[0] == 'decode':                # non-interactive: msibios.py decode file.ocb
        if not os.path.isfile(args[1]):
            sys.exit(f'No such file: {args[1]}')
        ensure_programs()
        sys.exit(0 if decode_profile(args[1], quiet=True) else 1)
    say(f'MSI BIOS Profile Tool {VERSION}')
    ensure_programs()
    while True:
        say(f'\nMSI BIOS Profile Tool {VERSION}    library: {library()}')
        for i, (text, _) in enumerate(MENU, 1):
            say(f'  {i}. {text}')
        say('  0. Exit')
        c = ask('Choose')
        if c in ('0', 'q', 'Q', 'exit'):
            return
        if c.isdigit() and 1 <= int(c) <= len(MENU):
            try:
                MENU[int(c) - 1][1]()
            except KeyboardInterrupt:
                say('\nCancelled.')
            except (ocb.ProfileError, firmware.FirmwareError, deps.DependencyError) as e:
                say(f'\nStopped: {e}')
            except Exception:
                say('\nSomething went wrong:\n' + traceback.format_exc())


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        # Started by a double-click, the window would close before the error could be read.
        print('\nThe tool stopped with an error:\n' + traceback.format_exc())
        try:
            input('Press Enter to close.')
        except EOFError:
            pass
        sys.exit(1)
