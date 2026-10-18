"""Decode settings stores against a BIOS's setup menus: which settings are on screen, their values and defaults."""
import base64, json, re
from collections import defaultdict

# Profile entry id -> settings store. The ids are the same in 2.A20 and 2.A22 profiles; stores not listed here are
# matched by size against the BIOS's own stores (see identify()).
KNOWN_STORES = {
    0x417276EE: ('Setup', 'EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9'),
    0xFFFCC9C3: ('PlatformLang', '8BE4DF61-93CA-11D2-AA0D-00E098032B8C'),
    0x5BE4FD77: ('Timeout', '8BE4DF61-93CA-11D2-AA0D-00E098032B8C'),
    0x769DC2FB: ('AMITSESetup', 'C811FA38-42C8-4579-A9BB-60E94EDDFB34'),
    0xDA6C8969: ('MsiOcInfoFlag', '48419251-DD85-4597-84B4-11182014ADDE'),
    0x24ACE52B: ('UsbSupport', 'EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9'),
    0xFF1F5B74: ('NetworkStackVar', 'D1405D16-7AFC-4695-BB12-41459D3695A2'),
    0x6B6125A9: ('MemoryZCoreSetupData', '521EA100-F3B7-4BDD-9193-57F917D6FE79'),
    0x4E602232: ('HwmSetupData', 'B4B6D1E7-039D-4CEF-8742-BA34DA443ECE'),
    0x538A16BC: ('IpConfiguration', '6E049A5E-0EED-4ABF-A39F-8ABB159EE7E7'),
    0x3EB725D4: ('SecureBootSetup', '7B59104A-C00D-4158-87FF-F04D6396A915'),
    0x5C69FAA8: ('ROM_CMN', '97CDC6BE-7792-4782-BA6D-E6E3BB56ACD8'),
    0x1A34E05A: ('AmdSetupPHX', '3A997502-647A-4C82-998E-52EF9486A247'),
    0x53496D3C: ('AmdSetupRPL', '3A997502-647A-4C82-998E-52EF9486A247'),
    0x5AE4D5E9: ('AmdSetupSTXKRK', '3A997502-647A-4C82-998E-52EF9486A247'),
    0x291DC81E: ('FixedBoot', 'DE8AB926-EFDA-4C23-BBC4-98FD29AA0069'),
    0x49C58225: ('AMD_PBS_SETUP', 'A339D746-F678-49B3-9FC7-54CE0F9DF226'),
    0x6467632A: ('AodSetupRpl', '5ED15DC0-EDEF-4161-9151-6014C4CC630C'),
}

GENERIC = '(AMI generic menu)'
INTERNAL_PROMPTS = {'BOM ID', 'Voltage Amount', 'Temperature Amount', 'Fan Amount', 'NewRecordOffset', 'Combo CBS'}


def truth(v):
    """An IFR condition result: None when it can't be worked out, else True or False (a constant 1 counts as True)."""
    return None if v is None else bool(v)


def nb(q):
    return max(1, (q.get('bits') or 8) // 8)


def rd(buf, off, n):
    if buf is None or off is None or off + n > len(buf):
        return None
    return int.from_bytes(buf[off:off + n], 'little')


def varstores(bios):
    """{(name, GUID): size} for every settings store the menus use."""
    out = {}
    for f in bios['menus']:
        for v in f['varstores'].values():
            if v['name'] and v['guid']:
                out.setdefault((v['name'], v['guid'].upper()), v['size'])
    return out


def identify(profile, bios):
    """[(entry, name, GUID, how)] for profile entries with data. how = 'known', 'size' or None (unidentified)."""
    sizes = defaultdict(set)
    for (n, g), s in varstores(bios).items():
        sizes[s].add((n, g))
    defaults = {(n, g.upper()): b for (n, g), b in bios['defaults'].items()}
    for k, b in defaults.items():
        sizes[len(b)].add(k)
    taken, out = set(), []
    for e in profile.entries:
        if not e.data:
            continue
        if e.id in KNOWN_STORES:
            n, g = KNOWN_STORES[e.id]
            out.append([e, n, g, 'known']); taken.add((n, g))
        else:
            out.append([e, None, None, None])
    # Unknown entries: match by size. Where the BIOS has a factory default for the candidate store, the entry
    # whose bytes look most like it wins (and must be clearly ahead); otherwise size must be unique on both sides.
    unknown = [r for r in out if not r[3]]
    for size in sorted({len(r[0].data) for r in unknown}):
        ents = [r for r in unknown if len(r[0].data) == size and not r[3]]
        cands = [k for k in sizes.get(size, ()) if k not in taken]
        for k in sorted(cands, key=lambda k: k not in defaults):
            ents = [r for r in ents if not r[3]]
            if not ents: break
            d = defaults.get(k)
            if d is not None:
                sc = sorted(((sum(a == b for a, b in zip(d, r[0].data)) / size, i) for i, r in enumerate(ents)), reverse=True)
                best, i = sc[0]
                if best >= 0.6 and (len(sc) == 1 or sc[1][0] < best):
                    ents[i][1], ents[i][2], ents[i][3] = k[0], k[1], 'size'; taken.add(k)
            elif len(ents) == 1 and len([c for c in cands if c not in taken]) == 1:
                ents[0][1], ents[0][2], ents[0][3] = k[0], k[1], 'size'; taken.add(k)
    return [tuple(r) for r in out]


def stores_from_profile(profile, bios):
    return {(n, g.upper()): e.data for e, n, g, how in identify(profile, bios) if n}


def stores_from_vars(path):
    """Settings read through Windows by biosread.ps1 (uefi-vars.json)."""
    with open(path, encoding='utf-8-sig') as f:
        snap = json.load(f)
    return {(v['name'], v['guid'].upper()): base64.b64decode(v['data']) for v in snap['vars'] if v.get('len', 0) > 0}, snap.get('meta', {})


class Model:
    def __init__(self, bios, cur):
        self.fs = bios['menus']
        self.std = {(n, g.upper()): b for (n, g), b in bios['defaults'].items()}
        self.cur = cur
        self.byguid = {f['guid']: f for f in self.fs}
        self.qidmap = {}
        for f in self.fs:
            m = {}
            for q in f['questions']:
                if q['var_name'] and q['qid'] not in m:
                    m[q['qid']] = q
            self.qidmap[id(f)] = m

    def qval(self, f, qid):
        q = self.qidmap[id(f)].get(qid)
        if q is None:
            return None
        return rd(self.cur.get((q['var_name'], (q['var_guid'] or '').upper())), q['offset'], nb(q))

    def ev(self, f, tokens):
        st = []
        try:
            for t in tokens:
                op = t[0]
                if op == 'True': st.append(True)
                elif op == 'False': st.append(False)
                elif op == 'Const': st.append(t[1])
                elif op == 'EqIdVal':
                    v = self.qval(f, t[1]); st.append(None if v is None else v == t[2])
                elif op == 'EqIdValList':
                    v = self.qval(f, t[1]); st.append(None if v is None else v in t[2])
                elif op == 'EqIdId':
                    a, b = self.qval(f, t[1]), self.qval(f, t[2]); st.append(None if a is None or b is None else a == b)
                elif op == 'QuestionRef1': st.append(self.qval(f, t[1]))
                elif op == 'Not':
                    a = st.pop(); st.append(None if a is None else not a)
                elif op in ('And', 'Or'):
                    b, a = st.pop(), st.pop()
                    if op == 'And': st.append(False if (a is False or b is False) else (None if a is None or b is None else True))
                    else: st.append(True if (a is True or b is True) else (None if a is None or b is None else False))
                elif op in ('Equal', 'NotEqual', 'LessThan', 'LessEqual', 'GreaterThan', 'GreaterEqual'):
                    b, a = st.pop(), st.pop()
                    if a is None or b is None: st.append(None)
                    else: st.append({'Equal': a == b, 'NotEqual': a != b, 'LessThan': a < b, 'LessEqual': a <= b,
                                     'GreaterThan': a > b, 'GreaterEqual': a >= b}[op])
                else: st.append(None)
            return st[-1] if st else None
        except IndexError:
            return None

    def hidden(self, f, conds):
        """True when a SuppressIf or DisableIf hides it, None when one of them can't be worked out (the value it
        depends on isn't in the file), else False. GrayOutIf only greys a setting out; it stays on the page."""
        hid = False
        for c in conds:
            if c['kind'] in ('SuppressIf', 'DisableIf'):
                r = truth(self.ev(f, c['tokens']))
                if r is True:
                    return True
                if r is None:
                    hid = None
        return hid

    def root_form(self, g):
        f = self.byguid[g]
        refd = {r['dst'] for r in f['refs'] if not r['dst_fs']}
        roots = [int(k) for k in f['forms'] if int(k) not in refd]
        return roots[0] if roots else int(next(iter(f['forms'])))

    def setup(self):
        return next((f for f in self.fs if f['module'] == 'Setup'), None)

    def tabs(self):
        """{menu: form id, or None when it isn't found} for the menus of MSI Click BIOS X in Advanced mode, in their
        order on screen: the left-hand menu, then the Hardware Monitor button in the top bar. The menus are found by
        MSI's page titles, checked on the MS-7E49 (2.A20 to 2.A25); a BIOS with another layout won't have them."""
        names = ['System Status', 'Advanced', 'Overclocking', 'Security', 'Boot', 'Hardware Monitor']
        setup = self.setup()
        if setup is None:
            return dict.fromkeys(names)
        forms = setup['forms']
        def form(title, skip=()):
            return next((int(k) for k, t in forms.items() if t == title and int(k) not in skip), None)
        # System Status, Advanced and Boot are the pages the "Settings" form links to; Security is MSI's own
        # page of that name (not AMI's generic one, which the generic Setup form links to).
        settings = {r['prompt']: r['dst'] for r in setup['refs'] if r['src'] == form('Settings') and not r['dst_fs']}
        amis = {r['dst'] for r in setup['refs'] if r['src'] == form('Setup')}
        found = dict(zip(names, (settings.get('System Status'), settings.get('Advanced'), form('Overclocking'),
                                 form('Security', skip=amis), settings.get('Boot'))))
        found['Hardware Monitor'] = next((int(k) for k, t in forms.items() if t == 'Hardware Monitor'
                                          and any(r['src'] == int(k) for r in setup['refs'])), None)
        return found

    def amd_oc(self):
        """The AMD Overclocking formset (AodDxe) for the CPU in use, or None. There is one per CPU family, each with
        its own settings store; a profile holds only the one in use, but a read through Windows may hold several."""
        aod = [f for f in self.fs if f['module'] == 'AodDxe' and stores_of(f) & set(self.cur)]
        if len(aod) > 1:            # keep the one that goes with the AMD CBS store in use (AodSetupRpl with AmdSetupRPL)
            fam = {n[8:11].lower() for n, g in set(self.cur) - inactive_variants(self.cur) if n.startswith('AmdSetup')}
            aod = [f for f in aod if any(n[8:11].lower() in fam for n, _ in stores_of(f))] or aod
        return aod[0] if aod else None

    def starts(self):
        """[(node, path)]: where each menu starts, in the order the BIOS lists them."""
        setup = self.setup()
        if setup is None:
            return []
        out = [((setup['guid'], fid), [name]) for name, fid in self.tabs().items() if fid is not None]
        aod = self.amd_oc()             # Click BIOS X adds AMD Overclocking to the end of Advanced
        if aod:
            out.append(((aod['guid'], self.root_form(aod['guid'])), ['Advanced', aod['title']]))
        generic = next((int(k) for k, t in setup['forms'].items() if t == 'Setup'), None)
        if generic is not None:
            out.append(((setup['guid'], generic), [GENERIC]))
        return out

    def paths(self):
        """{(formset GUID, form id): (menu path, position)}, walking the menus depth first in the order the BIOS
        lists them, so the position sorts pages as they appear on screen. Pages are named by their title, as the
        BIOS's path line shows them ("Accept" leads to "AMD Overclocking")."""
        starts = self.starts()
        top = {p[0]: n for n, p in starts if len(p) == 1}
        under = defaultdict(list)                       # AMD Overclocking comes last in Advanced
        for n, p in starts:
            if len(p) > 1:
                under[top.get(p[0])].append((n, p))
        out = {}

        def walk(n, path):
            if n in out:
                return
            out[n] = (path, len(out))
            g, fid = n
            f = self.byguid[g]
            for r in f['refs']:
                dg = r['dst_fs'] or g
                if r['src'] != fid or dg not in self.byguid or self.hidden(f, r['conds']) is True:
                    continue
                if r['dst_fs']:
                    dst, title = (dg, self.root_form(dg)), self.byguid[dg]['title']
                else:
                    dst, title = (g, r['dst']), f['forms'].get(str(r['dst']))
                walk(dst, path + [(title or r['prompt'] or '?').strip()])
            for n2, p2 in under.pop(n, ()):
                walk(n2, p2)
        for n, p in starts:
            walk(n, p)
        return out

    def locations(self):
        """storage location (store, GUID, offset, size) -> the best question for it (visible ones first)."""
        nodes = self.paths()
        locs = {}
        for f in self.fs:
            for qi, q in enumerate(f['questions']):
                if not q['var_name'] or q['type'] not in ('OneOf', 'CheckBox', 'Numeric') or q['offset'] is None:
                    continue
                key = (q['var_name'], q['var_guid'].upper(), q['offset'], nb(q))
                hid = self.hidden(f, q['conds'])
                p, pos = nodes.get((f['guid'], q['form']), (None, None))
                rec = dict(q=q, hidden=hid, path=p, reach=p is not None and hid is not True,
                           form=f['forms'].get(str(q['form'])), order=(pos, qi) if p else None)
                score = (not rec['reach'], hid is not False, not q['prompt'], len(p) if p else 99)
                if key not in locs or score < locs[key][0]:
                    locs[key] = (score, rec)
        return {k: v[1] for k, v in locs.items()}


def show(q, v):
    if v is None: return None
    if q['type'] == 'CheckBox': return 'Enabled' if v else 'Disabled'
    if q['type'] == 'OneOf':
        for ov, ot in q['options']:
            if ov == v: return (ot or '').strip() or str(v)
        return f'{v} (not one of the options)'
    if q.get('display_hex'): return hex(v)
    return str(v)


def fmt(q, v):
    """Value as MSI shows it, with units for voltages, temperatures and fan speeds. The rules were checked against
    the setup screens of the MS-7E49 (2.A22); other boards may show some values differently."""
    s = show(q, v)
    if s is None or q['type'] != 'Numeric': return s
    if v == 0 and q['var_name'] == 'Setup' and (q.get('bits') or 8) >= 16:
        return 'Auto'          # MSI's own wider settings (timings, ratios, voltages) show 0 as Auto; 8-bit ones show 0
    if re.search(r'Range:\s*\d+\s*~\s*\d+\s*T\b', q.get('help') or ''):
        return f'{s} T'        # DRAM timings in clock cycles, as MSI writes them ("60 T")
    p = (q['prompt'] or '').lower(); mx = q.get('max') or 0
    if 'fan speed (v)' in p: return f'{v / 100:.2f} V'
    if 'fan speed' in p: return f'{v} %'
    if 'temperature' in p and 'source' not in p: return f'{v} °C'
    if 'voltage' in p or p.strip().startswith('soc voltage'):
        if v == 0: return '0'
        if mx >= 10000: return f'{v / 10000:.4f} V'
        return f'{v / 1000:.3f} V ({v} mV)'
    return s


def default_of(model, key, q):
    """The factory default, or the menu's own default where the BIOS has no factory defaults for the store."""
    var = (key[0], key[1])
    if var in model.std: return rd(model.std[var], key[2], key[3])
    d = q.get('defaults', {})
    return next((d[k] for k in ('std', 'opt_std') if k in d), None)


def inactive_variants(cur):
    """AMD CBS stores of other CPU families (AmdSetupPHX/RPL/STXKRK ...): only the one in use has a filled-in
    header. Returns the set of (name, GUID) to leave out, empty when unsure."""
    cbs = {k: b for k, b in cur.items() if k[0].startswith('AmdSetup')}
    active = [k for k, b in cbs.items() if any(b[:4])]
    return set(cbs) - set(active) if len(active) == 1 else set()


def stores_of(f):
    return {(v['name'], (v['guid'] or '').upper()) for v in f['varstores'].values() if v['name']}


def row_id(store, offset):
    """How the reports refer to one setting."""
    return f'{store}+{offset:x}'


def layout_problems(bios):
    """Sentences for the report when this BIOS's menus aren't laid out the way the tool expects."""
    out = []
    missing = [t for t, fid in Model(bios, {}).tabs().items() if fid is None]
    if missing:
        names = ' and '.join(filter(None, (', '.join(missing[:-1]), missing[-1])))
        out.append(f"The tool did not find the {names} menu{'s' * (len(missing) > 1)} of MSI Click BIOS X in this "
                   'BIOS. Settings on those menus are missing from the list below (the changed ones are under "Stored values '
                   'not on any page shown"), and the order may differ from the screen. This happens with a BIOS that lays '
                   'out its menus differently, such as Click BIOS 5.')
    if bios.get('unread'):
        out.append(f"The menus in {', '.join(bios['unread'])} could not be read from the BIOS file, so their settings "
                   'are missing from this report.')
    return out


def decode(bios, cur):
    """Every storage location of the menus, decoded. Returns a list of row dicts."""
    m = Model(bios, cur)
    L = m.locations()
    aod = m.amd_oc()
    inactive = inactive_variants(cur) | {k for f in m.fs if f['module'] == 'AodDxe' and f is not aod for k in stores_of(f)}
    fam_guids = {g for (_, g) in inactive}
    rows = []
    for key, r in L.items():
        q = r['q']; var = (key[0], key[1])
        cv = rd(cur.get(var), key[2], key[3])
        dv = default_of(m, key, q)
        prompt = (q['prompt'] or '').strip()
        internal = (not prompt) or prompt in INTERNAL_PROMPTS or prompt.startswith(('Adjusted ', '[*]'))   # [*]: a fold-out group heading
        other_cpu = var in inactive or (var[1] in fam_guids and var not in cur)
        rows.append(dict(
            store=key[0], guid=key[1], offset=key[2], size=key[3], module=q['module'], type=q['type'],
            prompt=prompt, help=(q['help'] or '').strip(), path=r['path'], form=r['form'], order=r['order'],
            reach=r['reach'], hidden=r['hidden'], readable=var in cur,
            value=cv, value_s=fmt(q, cv), default=dv, default_s=fmt(q, dv),
            options=[(v, (t or '').strip()) for v, t in q['options']] if q['type'] == 'OneOf' else None,
            min=q.get('min'), max=q.get('max'), step=q.get('step'),
            internal=internal, other_cpu=other_cpu,
            changed=cv is not None and dv is not None and cv != dv))
    return rows


def path_s(row):
    return ' > '.join(row['path']) if row['path'] else None


def classify(rows):
    """Split rows into the groups the report shows."""
    live = [r for r in rows if r['reach'] and r['readable'] and not r['other_cpu'] and r['prompt']
            and not (r['path'] and r['path'][0] == GENERIC)]
    changed = [r for r in live if r['changed'] and not r['internal']]
    internal = [r for r in rows if r['reach'] and r['readable'] and r['changed'] and r['internal'] and not r['other_cpu']]
    hidden = [r for r in rows if not r['reach'] and r['readable'] and r['changed'] and not r['internal'] and not r['other_cpu']]
    generic = [r for r in rows if r['reach'] and r['readable'] and r['path'] and r['path'][0] == GENERIC and r['prompt']
               and not r['other_cpu']]
    unread = [r for r in rows if r['reach'] and not r['readable'] and r['prompt'] and not r['other_cpu']
              and not (r['path'] and r['path'][0] == GENERIC)]
    return dict(live=[r for r in live if not r['internal']], changed=changed, internal=internal, hidden=hidden,
                generic=generic, unread=unread)


def sort_key(r):
    """Menu order: the order of the menus, then of the pages in them, then of the settings on each page."""
    if r.get('order'):
        return (0,) + tuple(r['order']) + ('', 0)
    return (1, 0, 0, r['store'], r['offset'])
