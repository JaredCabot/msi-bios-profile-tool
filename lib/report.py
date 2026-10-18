"""Write a decoded set of BIOS settings as a self-contained HTML page (works offline) and as CSV."""
import csv, html, json, re

from .model import classify, sort_key, path_s, row_id


def _range(r):
    if r['type'] != 'Numeric' or r['min'] is None: return ''
    st = f", step {r['step']}" if r.get('step') and r['step'] != 1 else ''
    return f"{r['min']} to {r['max']}{st} (raw units)"


def _item(r, badge=None, note=None):
    p = r['path'] or []
    opts = None
    if r['options']:
        opts = [[t or str(v), v == r['value'], v == r['default']] for v, t in r['options']]
    elif r['type'] == 'CheckBox':
        opts = [['Disabled', r['value'] == 0, r['default'] == 0], ['Enabled', r['value'] == 1, r['default'] == 1]]
    return dict(id=row_id(r['store'], r['offset']), tab=p[0] if p else '(not on a menu page)',
                page=' › '.join(p[1:]) or '(main page)', name=r['prompt'], val=r['value_s'] or '(not readable)',
                dflt=r['default_s'], ch=bool(r['changed']), help=r['help'], opts=opts, rng=_range(r),
                loc=f"{r['store']} +{r['offset']:#x}, {r['size']} byte{'s' if r['size'] > 1 else ''}", badge=badge, note=note)


def _mini(r):
    return dict(path=(path_s(r) or '(not on a menu page)').replace(' > ', ' › '), name=r['prompt'] or f"(unnamed {r['store']} +{r['offset']:#x})",
                val=r['value_s'] or '(not readable)', dflt=r['default_s'])


def write_html(path, rows, title, eyebrow, meta, intro, callouts=(), badges=None, notes=None, storage_key='msibios'):
    """badges / notes: {row id: text} shown against individual settings (used by the converter)."""
    badges, notes = badges or {}, notes or {}
    c = classify(rows)
    rid = lambda r: row_id(r['store'], r['offset'])
    items = [_item(r, badges.get(rid(r)), notes.get(rid(r))) for r in sorted(c['live'], key=sort_key)]
    data = dict(items=items, hidden=[_mini(r) for r in sorted(c['hidden'], key=sort_key)],
                generic=[dict(_item(r), name=' › '.join((r['path'] or [])[1:] + [r['prompt']])) for r in sorted(c['generic'], key=sort_key)],
                internal=[_mini(r) for r in c['internal']], unread=[_mini(r) for r in sorted(c['unread'], key=sort_key)],
                key=storage_key)
    # Settings whose show/hide condition depends on a value the file doesn't hold: listed, but may not be on screen.
    unsure = [r['prompt'] for r in sorted(c['live'], key=sort_key) if r['hidden'] is None]
    vals = dict(TITLE=html.escape(title), EYEBROW=html.escape(eyebrow),
                META=''.join(f'<span>{html.escape(m)}</span>' for m in meta),
                INTRO=''.join(f'<p>{html.escape(p)}</p>' for p in intro),
                CALLOUTS=''.join(f'<div class="callout{" ok" if kind == "ok" else ""}"><b>{html.escape(h)}</b>'
                                 + ''.join(f'<p>{html.escape(x)}</p>' for x in body) + '</div>' for kind, h, body in callouts),
                UNSURE=f'<p>{len(unsure)} settings are listed although the BIOS decides whether to show them from values this '
                       f'file doesn\'t hold, so some may not be on your screen: {html.escape(", ".join(unsure))}.</p>' if unsure else '',
                DATA=json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
    page = re.sub(r'__([A-Z]+)__', lambda m: vals[m[1]], TEMPLATE)      # one pass, so no value is read as a placeholder
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)
    return {k: len(v) for k, v in c.items()}


def write_csv(path, rows):
    c = classify(rows)
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['Menu path', 'Setting', 'Current value', 'Factory default', 'Changed from default', 'Options', 'Help text', 'Store', 'Offset', 'Raw value'])
        for r in sorted(c['live'] + c['generic'], key=sort_key):
            opts = ' | '.join(t for _, t in r['options']) if r['options'] else ''
            w.writerow([path_s(r), r['prompt'], r['value_s'], r['default_s'] or '', 'yes' if r['changed'] else '',
                        opts, r['help'], r['store'], f"{r['offset']:#x}", r['value']])


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --paper: #f5f6f8; --sheet: #ffffff; --ink: #1a1d22; --muted: #5d6470; --rule: #d9dde3;
  --signal: #b4232a; --signal-soft: #f8e3e4; --done: #2f7d4f; --done-soft: #e3f2e8; --warn: #8a5a00; --warn-soft: #fbf0d9;
  --display: "Barlow Semi Condensed", "Arial Narrow", Arial, sans-serif;
  --body: "Segoe UI", system-ui, sans-serif;
  --mono: Consolas, "Cascadia Mono", "Courier New", monospace;
}
@media (prefers-color-scheme: dark) { :root {
  --paper: #121418; --sheet: #1b1e24; --ink: #e8eaee; --muted: #9aa1ad; --rule: #2e333b;
  --signal: #ff6b6f; --signal-soft: #3a1d20; --done: #6fcf97; --done-soft: #17301f; --warn: #f0c060; --warn-soft: #33290f; color-scheme: dark } }
* { box-sizing: border-box }
body { background: var(--paper); color: var(--ink); font: 16px/1.5 var(--body); margin: 0 }
.wrap { max-width: 900px; margin: 0 auto; padding: 28px 16px 64px; display: grid; gap: 22px }
header { display: grid; gap: 8px }
.eyebrow { font: 600 13px/1 var(--display); letter-spacing: .12em; text-transform: uppercase; color: var(--signal) }
h1 { font: 700 clamp(28px, 5vw, 40px)/1.1 var(--display); margin: 0; overflow-wrap: anywhere }
h2 { font: 700 22px/1.2 var(--display); margin: 0; letter-spacing: .02em }
h3 { font: 600 15px/1.3 var(--display); margin: 0; letter-spacing: .06em; text-transform: uppercase; color: var(--muted) }
p { margin: 0; max-width: 72ch }
.meta { font: 14px/1.5 var(--mono); color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 18px }
.callout { border-left: 4px solid var(--warn); background: var(--warn-soft); padding: 12px 14px; border-radius: 0 6px 6px 0; display: grid; gap: 6px }
.ok { border-left-color: var(--done); background: var(--done-soft) }
.bar { position: sticky; top: 0; z-index: 5; background: var(--paper); padding-block: 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; border-bottom: 1px solid var(--rule) }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 4px; overflow: hidden }
.seg button { border: 0; border-radius: 0 }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--paper) }
.progress { font: 600 15px/1 var(--display); letter-spacing: .04em }
.bar label { display: flex; gap: 6px; align-items: center; font-size: 14px; color: var(--muted); cursor: pointer }
input[type=search] { font: 15px var(--body); padding: 6px 8px; border: 1px solid var(--rule); border-radius: 4px; background: var(--sheet); color: var(--ink); min-width: 0; flex: 1 1 180px }
button { font: 600 13px/1 var(--display); letter-spacing: .06em; text-transform: uppercase; color: var(--ink); background: var(--sheet); border: 1px solid var(--rule); border-radius: 4px; padding: 8px 10px; cursor: pointer }
button:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--signal); outline-offset: 2px }
.tab { display: grid; gap: 14px }
.tabhead { display: flex; align-items: baseline; gap: 12px; border-bottom: 3px solid var(--signal); padding-bottom: 6px }
.tabhead .n { font: 500 14px var(--mono); color: var(--muted) }
.group { background: var(--sheet); border: 1px solid var(--rule); border-radius: 6px; overflow: hidden }
.group > h3 { padding: 10px 14px; border-bottom: 1px solid var(--rule) }
.set { border-bottom: 1px solid var(--rule) }
.set:last-child { border-bottom: 0 }
.row { display: grid; grid-template-columns: 28px minmax(0, 1fr) minmax(0, auto); gap: 2px 12px; align-items: start; padding: 10px 14px 4px; cursor: pointer }
.row input { width: 20px; height: 20px; margin: 2px 0 0; accent-color: var(--done); cursor: pointer }
.name { font-weight: 600; min-width: 0; overflow-wrap: anywhere }
.val { font: 500 15px/1.4 var(--mono); text-align: right; min-width: 0; overflow-wrap: anywhere }
.set.ch .val { color: var(--signal) }
.def { grid-column: 2 / -1; font: 13px/1.4 var(--mono); color: var(--muted) }
.badge { display: inline-block; font: 600 11px/1 var(--display); letter-spacing: .06em; text-transform: uppercase; padding: 3px 6px; border-radius: 3px; background: var(--warn-soft); color: var(--warn); margin-left: 8px; vertical-align: 2px }
.rnote { grid-column: 2 / -1; font-size: 14px; color: var(--warn) }
.about { padding: 0 14px 10px 54px }
.about summary { font: 13px var(--body); color: var(--muted); cursor: pointer; width: fit-content }
.about .body { display: grid; gap: 6px; padding-top: 6px; font-size: 14px }
.about ul { margin: 0; padding-left: 18px; font: 13px/1.5 var(--mono) }
.about li.cur { color: var(--signal); font-weight: 600 }
.about .loc { font: 12px var(--mono); color: var(--muted) }
.help { white-space: pre-line }
.set.done { background: var(--done-soft) }
.set.done .val { color: var(--done) }
.set.done .name { text-decoration: line-through; text-decoration-color: var(--muted) }
body.hide-done .set.done { display: none }
details.box { background: var(--sheet); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 14px }
details.box > summary { font: 600 17px/1.3 var(--display); cursor: pointer }
details.box > div { margin-top: 10px; display: grid; gap: 8px }
.mini { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px; font-size: 14px; border-top: 1px solid var(--rule); padding-top: 6px }
.mini .p { color: var(--muted); grid-column: 1 / -1; font: 12px var(--mono) }
.mini code { font: 13px var(--mono); overflow-wrap: anywhere }
.empty { color: var(--muted); font-style: italic }
footer { font-size: 13px; color: var(--muted); display: grid; gap: 6px }
@media (max-width: 560px) { .row { grid-template-columns: 26px minmax(0, 1fr) } .val { grid-column: 2; text-align: left } .about { padding-left: 14px } }
/* Print what the screen shows, on whatever paper the printer uses (A4 or Letter): the tick boxes stay so the
   printout works as a checklist, "About this setting" prints only where it is open, colours stay light.
   The page is laid out as plain blocks for print, because browsers only honour page-break rules reliably in
   block layout: a section of the list then moves whole to the next page instead of splitting, and a heading
   always stays with what follows it. A long section (class "long", more than 10 settings) may split where it
   falls, keeping its heading with its first settings, so it can't leave a big gap at the bottom of a page.
   The whole printout is scaled to 60%, the same as choosing 60% in the print dialog. */
@page { margin: 12mm }
@media print {
  :root { --paper: #fff; --sheet: #fff; --ink: #1a1d22; --muted: #5d6470; --rule: #d9dde3; --signal: #b4232a; --signal-soft: #f8e3e4;
          --done: #2f7d4f; --done-soft: #e3f2e8; --warn: #8a5a00; --warn-soft: #fbf0d9; color-scheme: light }
  html { zoom: .6 }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; font-size: 13px }
  .wrap, header, .tab, .callout, details.box > div { display: block }
  .wrap { max-width: none; padding: 0 }
  .wrap > * + *, .tab > * + *, details.box > div > * + * { margin-top: 12px }
  header > * + *, .callout > * + * { margin-top: 6px }
  .bar, .about:not([open]), .about summary, #reset { display: none }
  .row { padding: 6px 10px 2px }
  .about { padding: 0 10px 6px 50px }
  .tabhead, .group > h3, details.box > summary { break-after: avoid; break-inside: avoid }
  .group, .set, .callout, .mini { break-inside: avoid }
  .group.long { break-inside: auto }
}
</style></head><body>
<div class="wrap">
<header>
  <div class="eyebrow">__EYEBROW__</div>
  <h1>__TITLE__</h1>
  <div class="meta">__META__</div>
  __INTRO__
</header>
__CALLOUTS__
<div class="bar">
  <div class="seg" role="group" aria-label="View">
    <button type="button" id="v-ch" aria-pressed="true">Changed</button><button type="button" id="v-all" aria-pressed="false">All settings</button>
  </div>
  <input type="search" id="q" placeholder="Search settings, values, help text" aria-label="Search">
  <span class="progress" id="prog"></span>
  <label for="hidedone"><input type="checkbox" id="hidedone"> Hide done</label>
  <button type="button" id="reset">Clear ticks</button>
</div>
<div id="list"></div>
<details class="box" id="unreadbox"><summary>On screen but not in this file</summary><div><p>These settings are on a visible page, but the file holds no value for them. Check them by eye.</p><div id="unread"></div></div></details>
<details class="box"><summary>Stored values not on any page shown</summary><div><p>These differ from the factory default, but no page in Advanced mode shows them with these settings and this CPU, so they can't be entered by hand there. A few, such as EZ LED Control, are on the EZ Mode screen instead. Loading a profile restores them all.</p><div id="hidden"></div></div></details>
<details class="box"><summary>AMI's generic menu pages</summary><div><p>The BIOS also holds AMI's own setup pages, including the full AMD CBS menu, which MSI's screens don't show. Many of these settings appear on MSI's pages under another name; the rest can only be restored by loading a profile. They're listed for completeness.</p><div id="generic"></div></div></details>
<details class="box"><summary>Internal values (no action)</summary><div><p>Counters and read-only values the BIOS fills in itself.</p><div id="internal"></div></div></details>
<footer>
  <p>Setting names, menu paths, options and help text come from the menu definitions inside the BIOS file. Factory defaults come from the BIOS file's default settings ("Load Optimized Defaults"). The menus and their order are those of MSI Click BIOS X in Advanced mode; only pages the BIOS shows with these settings and this CPU are listed. Ticks are kept in this browser only.</p>
  __UNSURE__
</footer>
</div>
<script>
const DATA = __DATA__;
const KEY = 'msibios:' + DATA.key;
let done = {};
try { done = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { done = {}; }
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(done)); } catch (e) {} };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let view = DATA.items.some(i => i.ch) ? 'ch' : 'all', query = '';
function about(i) {
  let b = '';
  if (i.help) b += `<p class="help">${esc(i.help)}</p>`;
  if (i.opts) b += '<ul>' + i.opts.map(o => `<li class="${o[1] ? 'cur' : ''}">${esc(o[0])}${o[1] ? '  ← this file' : ''}${o[2] ? '  (default)' : ''}</li>`).join('') + '</ul>';
  if (i.rng) b += `<p>Range: ${esc(i.rng)}</p>`;
  b += `<p class="loc">${esc(i.loc)}</p>`;
  return `<details class="about"><summary>About this setting</summary><div class="body">${b}</div></details>`;
}
function rowHtml(i, tick) {
  const d = !!done[i.id];
  return `<div class="set${i.ch ? ' ch' : ''}${tick && d ? ' done' : ''}" data-id="${esc(i.id)}">
    <label class="row" for="cb-${esc(i.id)}">${tick ? `<input type="checkbox" id="cb-${esc(i.id)}" ${d ? 'checked' : ''}>` : '<span></span>'}
    <span class="name">${esc(i.name)}${i.badge ? `<span class="badge">${esc(i.badge)}</span>` : ''}</span><span class="val">${esc(i.val)}</span>
    <span class="def">default: ${esc(i.dflt ?? 'unknown')}</span>${i.note ? `<span class="rnote">${esc(i.note)}</span>` : ''}</label>${about(i)}</div>`;
}
function match(i) {
  if (!query) return true;
  return [i.name, i.val, i.dflt, i.help, i.page, i.tab].join(' ').toLowerCase().includes(query);
}
function render() {
  const list = document.getElementById('list');
  const items = DATA.items.filter(i => (view === 'all' || i.ch || i.badge) && match(i));
  let h = '';
  for (const tab of new Set(items.map(i => i.tab))) {         // items come in menu order
    const inTab = items.filter(i => i.tab === tab);
    if (!inTab.length) continue;
    h += `<section class="tab"><div class="tabhead"><h2>${esc(tab)}</h2><span class="n">${inTab.length}</span></div>`;
    const groups = new Map();
    for (const i of inTab) { if (!groups.has(i.page)) groups.set(i.page, []); groups.get(i.page).push(i); }
    for (const [g, rows] of groups) h += `<div class="group${rows.length > 10 ? ' long' : ''}"><h3>${esc(g === '(main page)' ? tab : g)}</h3>${rows.map(r => rowHtml(r, true)).join('')}</div>`;
    h += '</section>';
  }
  list.innerHTML = h || '<p class="empty">Nothing matches.</p>';
  document.getElementById('v-ch').setAttribute('aria-pressed', view === 'ch');
  document.getElementById('v-all').setAttribute('aria-pressed', view === 'all');
  document.getElementById('v-ch').textContent = `Changed (${DATA.items.filter(i => i.ch || i.badge).length})`;
  document.getElementById('v-all').textContent = `All settings (${DATA.items.length})`;
  refresh();
}
function refresh() {
  const shown = DATA.items.filter(i => view === 'all' || i.ch || i.badge);
  const n = shown.filter(i => done[i.id]).length;
  document.getElementById('prog').textContent = `${n} of ${shown.length} ticked`;
}
document.getElementById('list').addEventListener('change', e => {
  const set = e.target.closest('.set'); if (!set || e.target.type !== 'checkbox') return;
  const id = set.dataset.id; if (e.target.checked) done[id] = 1; else delete done[id];
  set.classList.toggle('done', e.target.checked); save(); refresh();
});
document.getElementById('v-ch').onclick = () => { view = 'ch'; render(); };
document.getElementById('v-all').onclick = () => { view = 'all'; render(); };
document.getElementById('q').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); render(); });
document.getElementById('hidedone').addEventListener('change', e => document.body.classList.toggle('hide-done', e.target.checked));
const resetBtn = document.getElementById('reset');
resetBtn.addEventListener('click', () => {
  if (resetBtn.dataset.armed !== '1') { resetBtn.dataset.armed = '1'; resetBtn.textContent = 'Tap again to clear'; setTimeout(() => { resetBtn.dataset.armed = ''; resetBtn.textContent = 'Clear ticks'; }, 3000); return; }
  done = {}; save(); resetBtn.dataset.armed = ''; resetBtn.textContent = 'Clear ticks'; render();
});
const mini = m => `<div class="mini"><span class="p">${esc(m.path || '')}</span><b>${esc(m.name)}</b><code>${esc(m.val)}${m.dflt ? '  (default ' + esc(m.dflt) + ')' : ''}</code></div>`;
const fill = (id, arr, f) => { document.getElementById(id).innerHTML = arr.length ? arr.map(f).join('') : '<p class="empty">None.</p>'; };
fill('unread', DATA.unread, mini); fill('hidden', DATA.hidden, mini); fill('internal', DATA.internal, mini);
document.getElementById('generic').innerHTML = DATA.generic.length ? `<div class="group">${DATA.generic.map(i => rowHtml(Object.assign({}, i, {page: i.page}), false)).join('')}</div>` : '<p class="empty">None.</p>';
if (DATA.unread.length) document.getElementById('unreadbox').open = true; else document.getElementById('unreadbox').hidden = true;
render();
</script>
</body></html>
'''
