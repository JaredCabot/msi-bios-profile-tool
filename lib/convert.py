"""Move an OC profile from one BIOS version to another.

Each settings store in the profile is rebuilt for the new BIOS:
  1. Settings are matched between the two versions by name and type, in the order they are stored (see match()),
     never by position, so settings that moved inside a store land in the right place.
  2. Bytes that no menu setting covers (detection data, internal values) are carried across where the two BIOS
     versions' factory defaults line up; where a store has no factory defaults, they are carried between the
     matched settings when the gap is the same size in both versions.
  3. Settings that are new in the target BIOS keep its factory default. Settings the target BIOS removed are
     reset to its factory default where it has one, because no menu can change them any more.
  4. A value is carried by what it means: an option is looked up by its text in the new BIOS. A value the target
     doesn't accept is replaced by its default, and every setting whose option text or range changed is flagged.
Stores the menus don't describe are copied unchanged.
"""
import difflib
from collections import defaultdict, namedtuple

from . import model, ocb
from .model import nb, rd

# One reported setting. q: its menu question, loc: (offset, size), value: the raw value, text: what to tell the user.
Note = namedtuple('Note', 'q loc value text')


def layout(bios, name, guid):
    """{(offset, size): [(prompt, type, question) ...]} for one settings store."""
    locs = defaultdict(list)
    for f in bios['menus']:
        for q in f['questions']:
            if q['var_name'] != name or (q['var_guid'] or '').upper() != guid or q['offset'] is None:
                continue
            if q['type'] not in ('OneOf', 'CheckBox', 'Numeric'):
                continue
            locs[(q['offset'], nb(q))].append(((q['prompt'] or '').strip(), q['type'], q))
    return dict(locs)


def best_q(qs):
    return sorted(qs, key=lambda x: (not x[0], x[2]['type'] != 'OneOf'))[0][2]


def token(qs):
    q = best_q(qs)
    return ((q['prompt'] or '').strip(), q['type'])


def match(old, new):
    """{old location: new location}.
    1. Line up both stores' settings in offset order and pair runs that have the same names (difflib), which copes
       with settings inserted or removed in between and with names that repeat (one copy per CPU variant).
    2. Inside the stretches that differ, pair settings whose name and type occur the same number of times.
    3. Pair what is left when a name and type occurs exactly once on each side (settings moved elsewhere).
    4. Unnamed settings left over at exactly the same position, type and size are paired as they are."""
    po, pn = sorted(old), sorted(new)
    to, tn = [token(old[l]) for l in po], [token(new[l]) for l in pn]
    pairs = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, to, tn, autojunk=False).get_opcodes():
        if tag == 'equal':
            pairs.update(zip(po[i1:i2], pn[j1:j2]))
        elif tag == 'replace':
            by_o, by_n = defaultdict(list), defaultdict(list)
            for i in range(i1, i2): by_o[to[i]].append(po[i])
            for j in range(j1, j2): by_n[tn[j]].append(pn[j])
            for k, ol in by_o.items():
                if k[0] and len(by_n.get(k, ())) == len(ol):
                    pairs.update(zip(ol, by_n[k]))
    used = set(pairs.values())
    rest_o, rest_n = defaultdict(list), defaultdict(list)
    for l in po:
        if l not in pairs: rest_o[token(old[l])].append(l)
    for l in pn:
        if l not in used: rest_n[token(new[l])].append(l)
    for k, ol in rest_o.items():
        if k[0] and len(ol) == 1 and len(rest_n.get(k, ())) == 1:
            pairs[ol[0]] = rest_n[k][0]; used.add(rest_n[k][0])
    for l in po:
        if l not in pairs and l in new and l not in used and token(old[l])[1] == token(new[l])[1]:
            pairs[l] = l; used.add(l)
    return pairs


def valid(q, v):
    if q['type'] == 'OneOf':
        return any(ov == v for ov, _ in q['options'])
    if q['type'] == 'CheckBox':
        return v in (0, 1)
    if q.get('min') is not None and q.get('max') is not None and q['max'] >= q['min']:
        return q['min'] <= v <= q['max']
    return True


def ifr_default(q):
    d = q.get('defaults', {})
    for k in ('std', 'opt_std'):
        if k in d: return d[k]
    return None


def option_text(q, v):
    return next(((t or '').strip() for ov, t in q['options'] if ov == v), None)


def carry(qo, qn, v, size):
    """(value to write, note) for a value moving from question qo to qn. Value None means: use the new default."""
    if v >= 1 << (8 * size):
        return None, f'the old value {v} does not fit the new setting; set to the default'
    if qo['type'] == 'OneOf' and qn['type'] == 'OneOf':
        old_t = option_text(qo, v)
        if old_t is None:
            return v, None                       # wasn't an option in the old BIOS either: the BIOS wrote it, keep it
        new_t = option_text(qn, v)
        if new_t == old_t:
            return v, None
        same = [ov for ov, t in qn['options'] if (t or '').strip() == old_t]
        if len(same) == 1:
            return same[0], f'"{old_t}" has a new number in this BIOS ({v} before, {same[0]} now); moved to it'
        if new_t is not None:
            return v, f'"{old_t}" is called "{new_t}" in this BIOS; check that it means the same'
        return None, f'"{old_t}" is not an option any more; set to the default'
    if valid(qo, v) and not valid(qn, v):
        return None, f'the old value {v} is outside what this BIOS accepts; set to the default'
    rng = lambda q: (q.get('min'), q.get('max'), q.get('step'))
    if qn['type'] == 'Numeric' and qo['type'] == 'Numeric' and rng(qo) != rng(qn):
        return v, f'the range changed from {qo.get("min")}-{qo.get("max")} to {qn.get("min")}-{qn.get("max")}; check the value'
    return v, None


def new_info(store, size, mode=''):
    return dict(store=store, old_size=size, matched=0, mode=mode, uncarried=0,
                new=[], removed=[], renamed=[], check=[])


def convert_store(name, guid, data, old_bios, new_bios, log):
    """New bytes for one store, plus a dict describing what happened. log(kind, text) collects report lines."""
    gk = guid.upper()
    ol, nl = layout(old_bios, name, gk), layout(new_bios, name, gk)
    od = {(n, g.upper()): b for (n, g), b in old_bios['defaults'].items()}.get((name, gk))
    nd = {(n, g.upper()): b for (n, g), b in new_bios['defaults'].items()}.get((name, gk))
    declared_old = model.varstores(old_bios).get((name, gk))
    declared_new = model.varstores(new_bios).get((name, gk))
    if nd is not None:
        new_size = len(nd)
    elif declared_new and declared_old == len(data):
        new_size = declared_new          # the menus describe this store's size reliably
    else:
        new_size = len(data)
    info = new_info(name, len(data))
    if not ol and not nl:
        info['mode'] = 'copied (no menu settings)'
        if new_size != len(data):
            log('warn', f'{name}: the new BIOS expects {new_size} bytes but the profile has {len(data)}; copied unchanged.')
        return bytes(data), info
    pairs = match(ol, nl)
    info['matched'] = len(pairs)
    new_locs = set(nl) - set(pairs.values())
    old_gone = set(ol) - set(pairs)
    same_layout = new_size == len(data) and all(a[0] == b[0] for a, b in pairs.items())
    new_cover = {i for (o, sz) in nl for i in range(o, o + sz)}
    if same_layout:
        buf = bytearray(data)
        info['mode'] = 'same layout'
    else:
        info['mode'] = 'rebuilt'
        # start from the new factory defaults, or else from the old bytes as they were (cut or padded to size)
        buf = bytearray(nd) if nd is not None else bytearray(data[:new_size]) + bytearray(max(0, new_size - len(data)))
        if od is not None and nd is not None and len(od) == len(data):
            # carry every byte whose surroundings are the same in both versions' factory defaults
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, od, nd, autojunk=False).get_opcodes():
                if tag == 'equal':
                    buf[j1:j2] = data[i1:i2]
        else:
            # no defaults to line up against: carry the gaps between paired settings when they are the same size
            anchors = sorted((a[0], a[0] + a[1], b[0], b[0] + b[1]) for a, b in pairs.items())
            prev_o = prev_n = 0
            for oa, oe, na, ne in anchors + [(len(data), len(data), new_size, new_size)]:
                if oa >= prev_o and na >= prev_n:
                    go, gn = oa - prev_o, na - prev_n
                    gap = data[prev_o:oa]
                    if go == gn:
                        buf[prev_n:na] = gap
                    elif go > gn and len(set(gap[gn:])) <= 1 and gap[gn:gn + 1] in (b'\x00', b'\xff'):
                        buf[prev_n:na] = gap[:gn]                                         # only padding is lost
                    elif not (len(set(gap)) <= 1 and gap[:1] in (b'', b'\x00')):           # zeros need no carrying
                        info['uncarried'] += go
                prev_o, prev_n = max(prev_o, oe), max(prev_n, ne)
            if info['uncarried']:
                log('warn', f"{name}: {info['uncarried']} bytes that no menu setting covers could not be lined up with the new layout; "
                            "they were kept at their old positions and may be misplaced.")
    # settings present in both versions
    for (oo, os_), (no, ns) in pairs.items():
        qo, qn = best_q(ol[(oo, os_)]), best_q(nl[(no, ns)])
        if token(ol[(oo, os_)])[0] != token(nl[(no, ns)])[0] and qo['prompt'] and qn['prompt']:
            info['renamed'].append(Note(qn, (no, ns), None, f"{qo['prompt'].strip()} is now called {qn['prompt'].strip()}"))
        v = rd(data, oo, os_)
        if v is None:
            info['check'].append(Note(qn, (no, ns), None, 'the profile has no value for this setting; left at the new default'))
            continue
        w, why = carry(qo, qn, v, ns)
        if w is None:
            w = rd(nd, no, ns) if nd is not None else ifr_default(qn)
        if why:
            info['check'].append(Note(qn, (no, ns), w, why))
        if w is not None:
            buf[no:no + ns] = int(w).to_bytes(ns, 'little')
    # settings that are new in the target version take its default
    for loc in sorted(new_locs):
        q = best_q(nl[loc])
        dv = rd(nd, *loc) if nd is not None else ifr_default(q)
        info['new'].append(Note(q, loc, dv, None))
        if dv is not None:
            buf[loc[0]:loc[0] + loc[1]] = int(dv).to_bytes(loc[1], 'little')
    # settings the target version removed: reset to its default where it has one and no new setting uses the bytes
    for loc in sorted(old_gone):
        info['removed'].append(Note(best_q(ol[loc]), loc, rd(data, *loc), None))
        if nd is not None and same_layout:
            for i in range(loc[0], loc[0] + loc[1]):
                if i not in new_cover and i < len(nd):
                    buf[i] = nd[i]
    if name.startswith('AmdSetup'):
        fix_cbs_id(name, buf, old_bios, new_bios, info, log)
    return bytes(buf), info


def fix_cbs_id(name, buf, old_bios, new_bios, info, log):
    """Give an AMD CBS store the layout ID of the target BIOS (see firmware.cbs_ids)."""
    var = name[len('AmdSetup'):]
    pick = lambda ids: next((v for k, v in (ids or {}).items() if var.startswith(k) or k.startswith(var)), None)
    o, n = pick(old_bios.get('cbs_ids')), pick(new_bios.get('cbs_ids'))
    if len(buf) < 12 or not any(buf[:4]):
        return                                           # not the CPU family in use: header is blank
    if not o or not n:
        log('warn', f'{name}: could not find the AMD CBS layout ID in one of the BIOS files; left as it was. '
                    'If it is wrong, the BIOS resets the AMD CBS settings to defaults at the next boot.')
        return
    if buf[0:4].hex() != o[0] or buf[8:12].hex() != o[1]:
        log('warn', f'{name}: the AMD CBS layout ID in the profile does not match the source BIOS; replaced with the target BIOS value anyway.')
    buf[0:4], buf[8:12] = bytes.fromhex(n[0]), bytes.fromhex(n[1])
    info['cbs_id'] = (o, n)


def check_output(src, data, version):
    """Read the new file back and confirm it is the source profile with only the store data and version changed."""
    q = ocb.Profile(data)
    same_entries = [(e.index, e.id, e.attr) for e in q.entries] == [(e.index, e.id, e.attr) for e in src.entries]
    if not (q.checksum_ok and q.version == version and q.oci_version == version and q.board == src.board and same_entries):
        raise ocb.ProfileError('The converted profile did not read back correctly; nothing was written.')
    return q


def convert(profile, old_bios, new_bios, log):
    """Converted profile bytes and a list of per-store info dicts."""
    if profile.version != old_bios['version']:
        raise ocb.ProfileError(f"The profile was saved on BIOS {profile.version} but the source BIOS file is {old_bios['version']}.")
    if old_bios['board'] != new_bios['board'] or profile.board != old_bios['board']:
        raise ocb.ProfileError(f"Board mismatch: profile {profile.board}, source BIOS {old_bios['board']}, target BIOS {new_bios['board']}.")
    infos = []
    ident = model.identify(profile, old_bios)              # one row per entry with data, in entry order
    out = ocb.Profile(profile.raw)
    for (_, n, g, _), e in zip(ident, (e for e in out.entries if e.data)):
        if not n:
            infos.append(new_info(f'entry {e.index}', len(e.data), 'copied (store not identified)'))
            continue
        e.data, info = convert_store(n, g, e.data, old_bios, new_bios, log)
        infos.append(info)
    # The list of entries comes from the old profile. A store the new BIOS added has no entry, so loading the
    # profile leaves it as it is on the board.
    added = sorted({n for n, g in new_bios['defaults']} - {n for n, g in old_bios['defaults']})
    if added:
        log('info', f"The new BIOS has settings stores the old one didn't ({', '.join(added)}). The profile has no entry "
                    'for them, so loading it leaves them as they are on the board.')
    data = out.build(version=new_bios['version'])
    check_output(profile, data, new_bios['version'])
    return data, infos


def summarize(p, q, infos, notes, old_rows, new_rows):
    """(callouts, badges, row notes) for the conversion report. Rows are decoded with the old and new menus."""
    label = ocb.label
    key = lambda r: (r['store'], r['offset'])
    shown = lambda rows: {key(r): r for r in rows if r['reach'] and r['prompt'] and not r['other_cpu'] and not r['internal']}
    vis_old, vis_new = shown(old_rows), shown(new_rows)
    where = lambda r: f"{model.path_s(r).replace(' > ', ' › ')} › {r['prompt']}"
    badges, rnotes = {}, {}
    added, removed, check, renamed, unseen = [], [], [], [], 0
    for i in infos:
        rid = lambda loc: model.row_id(i['store'], loc[0])
        for n in i['new']:
            r = vis_new.get((i['store'], n.loc[0]))
            if r:
                badges[rid(n.loc)] = f'New in {label(q.version)}'
                added.append(f"{where(r)}: {r['value_s']} (the new default)")
        for n in i['removed']:
            r = vis_old.get((i['store'], n.loc[0]))
            if r:
                removed.append(f"{where(r)}: was {r['value_s']}" + (' (default)' if not r['changed'] else ''))
        for n in i['check']:
            badges[rid(n.loc)], rnotes[rid(n.loc)] = 'Check', n.text[0].upper() + n.text[1:] + '.'
            r = vis_new.get((i['store'], n.loc[0]))
            if r:
                check.append(f'{where(r)}: {n.text}')
            else:
                unseen += 1                      # a copy on a hidden page (another CPU family's OC pages, for example)
        renamed += [n.text for n in i['renamed']]
    rebuilt = [i['store'] for i in infos if i['mode'] == 'rebuilt']
    unknown = [i for i in infos if i['mode'] == 'copied (store not identified)']
    summary = [f'Converted from BIOS {label(p.version)} to {label(q.version)}. Settings were matched by name and type, '
               'and options by their text, so values moved inside a store land in the right place.',
               f"{sum(i['matched'] for i in infos):,} setting positions carried across in {sum(1 for i in infos if i['matched'])} settings stores. "
               + (f"Stores with a changed layout, rebuilt for the new BIOS: {', '.join(rebuilt)}." if rebuilt else 'No store changed its layout.')]
    if any(i.get('cbs_id') for i in infos):
        summary.append('AMD CBS layout ID updated to the target BIOS value, so the BIOS accepts the AMD CBS settings.')
    if unknown:
        summary.append(f"{len(unknown)} small entries ({sum(i['old_size'] for i in unknown)} bytes) whose settings store the tool "
                       "can't identify were copied unchanged. MSI's menus don't describe them.")
    warn = [t for k, t in notes if k == 'warn']
    callouts = [('ok' if not warn and not check else 'warn', 'What the conversion did', summary)]
    if unseen:
        check.append(f"{unseen} more were flagged on pages the BIOS doesn't show with these settings and this CPU; nothing to do there.")
    if check:
        callouts.append(('warn', 'Check these settings', check))
    if added:
        callouts.append(('warn', f'New settings in {label(q.version)} (set to the new default)', added[:60] + ([f'... and {len(added) - 60} more'] if len(added) > 60 else [])))
    if removed:
        callouts.append(('warn', f'Settings {label(q.version)} no longer has (set to its factory default where it has one)', removed))
    if renamed:
        callouts.append(('warn', 'Renamed settings', renamed))
    if notes:
        callouts.append(('warn', 'Notes', [t for k, t in notes]))
    callouts.append(('warn', 'Before you save', [
        'The converted file has not been checked by MSI. Load it from OC PROFILE on the new BIOS, go through the changed list '
        'below on the setup screens, and only then press F10. If the BIOS refuses the file, enter the changed list by hand.']))
    return callouts, badges, rnotes
