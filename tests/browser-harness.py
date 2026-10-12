"""Offline regression harness: mock SillyTavern page + mock database 1.2.9 public API.

Usage: python3 -I harness.py <index.js>
Each test prints PASS/FAIL. Database behaviour mirrors upstream AlbusKen/shujuku 1.2.9:
- exportTableAsJson returns the live runtime object (no getCurrentData)
- CRUD awaits and notifies table-update callbacks before resolving
- automatic fills notify table-update but NOT fill-start (planManaged path, 1.2.7+;
  the default storage mode never sent it)
- chat messages that hold saved tables carry TavernDB_ACU_* fields (T11-T13)
Manual table editing is off by default since V17.6.9, so every run enables it.
"""
import json, sys
from playwright.sync_api import sync_playwright

SCRIPT = open(sys.argv[1], encoding='utf-8').read()
JQUERY = open('/usr/share/javascript/jquery/jquery.min.js', encoding='utf-8').read()

MOCK = r"""
window.toastr = { info(){}, success(){}, error(m){ (window.__toastErr ||= []).push(m); }, warning(){} };
const mk = (chat) => ({
  mate: { type: 'chatSheets', version: 1 },
  sheet_a: { name: '主角信息', orderNo: 0, content: [['row_id','姓名','等级'], ['1', chat === 'A' ? '张三' : '李四', '5']] },
  sheet_b: { name: '背包', orderNo: 1, content: [['row_id','物品','数量'], ['1','药水','2'], ['2','长剑','3'], ['3','盾牌','5']] },
});
window.__chat = 'A';
window.__data = mk('A');
window.__mk = mk;
window.__stChat = window.__stChat || [];
const upd = [], fill = [];
window.__calls = [];
window.__notify = () => upd.forEach(cb => cb(window.__data, { persisted: true }));
window.__fillStart = () => fill.forEach(cb => cb());
const sheetByName = n => Object.values(window.__data).find(s => s && s.name === n);
window.AutoCardUpdaterAPI = {
  exportTableAsJson: () => window.__data,
  registerTableUpdateCallback: cb => upd.push(cb),
  unregisterTableUpdateCallback: cb => { const i = upd.indexOf(cb); if (i > -1) upd.splice(i, 1); },
  registerTableFillStartCallback: cb => fill.push(cb),
  updateCell: async (t, r, c, v) => { window.__calls.push(['updateCell', t, r, c, v]); sheetByName(t).content[r][c] = v; window.__notify(); return true; },
  updateRow: async (t, r, o) => { window.__calls.push(['updateRow', t, r, o]); return true; },
  insertRow: async (t, o) => { window.__calls.push(['insertRow', t, o]); return -1; },
  deleteRow: async (t, r) => { window.__calls.push(['deleteRow', t, r]); sheetByName(t).content.splice(r, 1); window.__notify(); return true; },
};
const listeners = {};
const bus = { on: (e, f) => (listeners[e] ||= []).push(f), removeListener: (e, f) => { listeners[e] = (listeners[e] || []).filter(x => x !== f); } };
window.SillyTavern = { getContext: () => ({
  getCurrentChatId: () => window.__chat, characterId: 0, groupId: null, chat: window.__stChat,
  eventTypes: { CHAT_CHANGED: 'chat_changed', MESSAGE_UPDATED: 'message_updated' },
  eventSource: bus,
}) };
window.__switchChat = (id) => { window.__chat = id; window.__data = mk(id); (listeners.chat_changed || []).forEach(f => f()); window.__notify(); };
"""

HEADER_ONLY = r"""
window.__data = {
  mate: { type: 'chatSheets', version: 1 },
  sheet_g: { name: '全局数据表', orderNo: 0, content: [['row_id','时间','地点']] },
  sheet_p: { name: '主角信息表', orderNo: 1, content: [['row_id','姓名','等级']] },
  sheet_i: { name: '背包物品表', orderNo: 2, content: [['row_id','物品','数量']] },
};
"""

PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="chat">
  <div class="mes" mesid="0" is_user="true"><div class="mes_block"><span class="name_text">User</span><div class="mes_text">hi</div></div></div>
  <div class="mes" mesid="1" is_user="false"><div class="mes_block"><span class="name_text">Bot</span><div class="mes_text">hello</div></div></div>
</div><textarea id="send_textarea"></textarea></body></html>"""

results = []
def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail else ''))

def boot(p, config=None, pre=None, post_mock=None, before_mock=None, viewport=None):
    b = p.chromium.launch()
    pg = b.new_page(viewport=viewport or {'width': 1200, 'height': 900})
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.route('http://tavern.test/**', lambda r: r.fulfill(status=200, content_type='text/html; charset=utf-8', body=PAGE))
    pg.goto('http://tavern.test/')
    pg.add_script_tag(content=JQUERY)
    cfg = {'allowTableEdit': True, **(config or {})}
    pg.evaluate("c => localStorage.setItem('acu_ui_config_v18', JSON.stringify(c))", cfg)
    if before_mock: pg.evaluate(before_mock)
    pg.add_script_tag(content=MOCK)
    if post_mock: pg.add_script_tag(content=post_mock)
    if pre: pg.evaluate(pre)
    pg.add_script_tag(content=SCRIPT)
    pg.wait_for_selector('.acu-nav-btn', timeout=5000)
    pg.wait_for_timeout(300)
    return b, pg, errors

def open_tab(pg, name):
    pg.evaluate("n => [...document.querySelectorAll('.acu-nav-btn')].find(b => b.dataset.table === n).click()", name)
    pg.wait_for_timeout(250)

def dash_text(pg):
    pg.evaluate("() => { const b = document.querySelector('.acu-dash-ctrl-bar'); const w = document.querySelector('.acu-dash-content-wrapper'); if (b && w && getComputedStyle(w).opacity === '0') b.click(); }")
    pg.wait_for_timeout(200)
    return pg.evaluate("() => document.querySelector('.acu-embedded-dashboard-container .acu-dash-content-wrapper')?.textContent || ''")

def settings_tables(pg):
    pg.evaluate("() => document.querySelector('#acu-btn-settings').click()"); pg.wait_for_timeout(300)
    pg.evaluate("() => document.querySelector('[data-target=\"sec-table-mgmt\"]').click()"); pg.wait_for_timeout(300)
    return pg.evaluate("""() => ({ hint: document.querySelector('.acu-table-empty-hint')?.textContent || '',
        report: document.querySelector('.acu-read-report')?.textContent || '',
        open: !!document.querySelector('.acu-read-diagnostics')?.open,
        labels: [...document.querySelectorAll('#sec-table-mgmt .acu-label-main')].map(e => e.textContent.trim()) })""")

STORED_CHAT = "() => { window.__stChat = [{ is_user: true, mes: 'hi' }, { is_user: false, mes: 'hello', TavernDB_ACU_IsolatedData: { 'k': { independentData: {} } } }]; }"

with sync_playwright() as p:
    # T1/T2: auto-fill (no fill-start) highlights only what this fill changed; unchanged notify keeps them.
    b, pg, errs = boot(p, {'highlightNew': True, 'showDashboard': False})
    pg.evaluate("() => window.__notify()"); pg.wait_for_timeout(300)  # the database notifies once after loading the chat
    pg.evaluate("() => { window.__data.sheet_b.content[2][2] = '9'; window.__notify(); }")
    pg.wait_for_timeout(400); open_tab(pg, '背包')
    n = pg.evaluate("() => document.querySelectorAll('#acu-data-area .acu-highlight-changed').length")
    check('T1 auto-fill without fill-start highlights changed cell', n > 0, f'highlights={n}')
    pg.evaluate("() => window.__notify()"); pg.wait_for_timeout(400)
    if not pg.evaluate("() => !!document.querySelector('#acu-data-area.visible')"): open_tab(pg, '背包')
    n2 = pg.evaluate("() => document.querySelectorAll('#acu-data-area .acu-highlight-changed').length")
    check('T2 unchanged notification keeps highlights', n2 > 0, f'highlights={n2}')
    # T2b: a second auto-fill highlights only its own change, not the earlier one.
    pg.evaluate("() => { window.__data.sheet_b.content[3][2] = '7'; window.__notify(); }"); pg.wait_for_timeout(400)
    if not pg.evaluate("() => !!document.querySelector('#acu-data-area.visible')"): open_tab(pg, '背包')
    cards = pg.evaluate("""() => [...document.querySelectorAll('#acu-data-area .acu-data-card')].map(c => ({
        idx: c.querySelector('.acu-card-index')?.textContent, hl: !!c.querySelector('.acu-highlight-changed') || c.classList.contains('acu-highlight-changed') }))""")
    hl = sorted(c['idx'] for c in cards if c['hl'])
    check('T2b second auto-fill highlights only its own row', hl == ['#3'], json.dumps(cards, ensure_ascii=False))
    check('T0 no page errors (highlight run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T3: highlight OFF -> changed rows must not jump to the top.
    b, pg, errs = boot(p, {'highlightNew': False, 'showDashboard': False})
    pg.evaluate("() => { window.__fillStart(); window.__data.sheet_b.content[3][2] = '8'; window.__notify(); }")
    pg.wait_for_timeout(400); open_tab(pg, '背包')
    first = pg.evaluate("() => document.querySelector('#acu-data-area .acu-card-index')?.textContent")
    check('T3 highlight off keeps original row order', first == '#1', f'first card={first}')
    # T6: search ignores hidden row_id column.
    pg.evaluate("() => document.querySelector('#acu-btn-search-toggle')?.click()")
    pg.evaluate("() => { const i = document.querySelector('#acu-search-input'); i.style.display=''; i.value = '1'; i.dispatchEvent(new Event('input', { bubbles: true })); }"); pg.wait_for_timeout(500)
    cards = pg.evaluate("() => document.querySelectorAll('#acu-data-area .acu-data-card').length")
    check('T6 search does not match hidden row_id', cards == 0, f'cards={cards}')
    # T5: drag-select from inside dialog to backdrop must not close it; a real backdrop click does.
    pg.evaluate("() => document.querySelector('#acu-btn-settings').click()"); pg.wait_for_timeout(300)
    pg.evaluate("""() => { const o = document.querySelector('.acu-edit-overlay'); const inner = o.querySelector('.acu-edit-dialog') || o.firstElementChild;
        inner.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
        o.dispatchEvent(new MouseEvent('click', { bubbles: true })); }""")
    still = pg.evaluate("() => !!document.querySelector('.acu-edit-overlay')")
    check('T5a drag out of dialog keeps it open', still)
    pg.evaluate("""() => { const o = document.querySelector('.acu-edit-overlay'); if (!o) return;
        o.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
        o.dispatchEvent(new MouseEvent('click', { bubbles: true })); }""")
    gone = pg.evaluate("() => !document.querySelector('.acu-edit-overlay')")
    check('T5b real backdrop click closes it', gone)
    check('T0 no page errors (order/search/dialog run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T4: auto-configured 主角信息 dashboard slot follows the first row in another chat.
    b, pg, errs = boot(p, {'showDashboard': True, 'dashboardPosition': 'embedded'})
    pg.evaluate("() => window.__switchChat('B')"); pg.wait_for_timeout(600)
    txt = dash_text(pg)
    cfg = pg.evaluate("() => JSON.parse(localStorage.getItem('acu_dash_config_v1') || '{}').slot_2_1 || null")
    check('T4 dashboard slot follows first row after chat switch', '李四' in txt and (cfg or {}).get('card') is None, f'{txt.strip()[:60]} cfg={cfg}')
    # T8: dashboard open state survives a new reply (container re-created on a new message).
    pg.evaluate("""() => { const m = document.createElement('div'); m.className = 'mes'; m.setAttribute('is_user','false'); m.setAttribute('mesid','2');
        m.innerHTML = '<div class="mes_block"><span class="name_text">Bot</span><div class="mes_text">next</div></div>';
        document.querySelector('#chat').appendChild(m); window.__stChat.push({ is_user: false, mes: 'next' }); window.__notify(); }""")
    pg.wait_for_timeout(1900)
    op = pg.evaluate("() => { const w = document.querySelector('.acu-embedded-dashboard-container .acu-dash-content-wrapper'); return w ? getComputedStyle(w).opacity : 'none'; }")
    moved = pg.evaluate("() => [...document.querySelectorAll('#chat > .mes')].pop().querySelector('.acu-embedded-dashboard-container') !== null")
    check('T8 opened dashboard stays open on the new reply', moved and op == '1', f'moved={moved} opacity={op}')
    check('T0 no page errors (dashboard run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T9: batch delete via multi-select deletes the right row and leaves no false "changed" highlights.
    b, pg, errs = boot(p, {'highlightNew': True, 'showDashboard': False})
    pg.evaluate("() => { window.__fillStart(); window.__notify(); }"); pg.wait_for_timeout(300)
    open_tab(pg, '背包')
    pg.evaluate("() => document.querySelector('#acu-btn-multiselect').click()"); pg.wait_for_timeout(150)
    pg.evaluate("() => { const c = document.querySelector('#acu-data-area .acu-card-checkbox'); c.checked = true; c.dispatchEvent(new Event('change', { bubbles: true })); }")
    pg.evaluate("() => document.querySelector('#acu-btn-refresh').click()"); pg.wait_for_timeout(300)
    pg.evaluate("() => document.querySelector('.acu-custom-confirm-ok, [data-confirm=\"ok\"], .acu-confirm-ok')?.click()"); pg.wait_for_timeout(700)
    calls = pg.evaluate("() => window.__calls")
    left = pg.evaluate("() => window.__data.sheet_b.content.map(r => r[1])")
    check('T9a multi-select delete removes 背包 row 1', calls == [['deleteRow', '背包', 1]] and left == ['物品', '长剑', '盾牌'], json.dumps([calls, left], ensure_ascii=False))
    if not pg.evaluate("() => !!document.querySelector('#acu-data-area.visible')"): open_tab(pg, '背包')
    n = pg.evaluate("() => document.querySelectorAll('#acu-data-area .acu-highlight-changed').length")
    check('T9b no false highlights after delete', n == 0, f'highlights={n}')
    check('T0 no page errors (delete run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T10: phone width smoke test.
    b, pg, errs = boot(p, {}, viewport={'width': 390, 'height': 844})
    open_tab(pg, '背包')
    pg.evaluate("() => document.querySelector('#acu-btn-settings').click()"); pg.wait_for_timeout(300)
    over = pg.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    check('T10 390px: no errors, no horizontal overflow', not errs and not over, f'errors={errs[:1]} overflow={over}')
    b.close()

    # T11: header-only tables while the chat has saved table data (frontend attached to an empty database copy).
    b, pg, errs = boot(p, {'showDashboard': True, 'dashboardPosition': 'embedded'}, before_mock=STORED_CHAT, post_mock=HEADER_ONLY)
    txt = dash_text(pg)
    check('T11a dashboard explains empty read instead of "未找到表格"', '未找到表格' not in txt and '读到的是空表' in txt, txt.strip()[:90])
    open_tab(pg, '背包物品表')
    panel = pg.evaluate("() => document.querySelector('#acu-data-area .acu-panel-content')?.textContent || ''")
    check('T11b empty table panel shows the duplicate-database hint', '装了两份' in panel, panel.strip()[:60])
    s = settings_tables(pg)
    check('T11c settings: red hint, diagnostics open, row counts', '装了两份' in s['hint'] and s['open'] and '数据行：共 0 行' in s['report']
          and '保存过表格的楼层：1' in s['report'] and any(l.endswith('0 行') for l in s['labels']), json.dumps(s, ensure_ascii=False)[:240])
    check('T0 no page errors (empty-read run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T12: genuinely new chat (nothing saved yet) — plain "暂无数据", no false duplicate warning.
    b, pg, errs = boot(p, {'showDashboard': True, 'dashboardPosition': 'embedded'}, post_mock=HEADER_ONLY)
    txt = dash_text(pg)
    open_tab(pg, '背包物品表')
    panel = pg.evaluate("() => document.querySelector('#acu-data-area .acu-panel-content')?.textContent || ''")
    s = settings_tables(pg)
    check('T12 new empty chat: "暂无数据" without duplicate warning', '暂无数据' in txt and '装了两份' not in panel + s['hint'] and '还没有数据' in s['hint'],
          json.dumps([txt.strip()[:60], panel.strip()[:30], s['hint'][:40]], ensure_ascii=False))
    check('T0 no page errors (new-chat run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T13: an old slot config with no table name is treated as unconfigured, not "未找到表格:".
    b, pg, errs = boot(p, {'showDashboard': True, 'dashboardPosition': 'embedded'},
                       before_mock="() => localStorage.setItem('acu_dash_config_v1', JSON.stringify({ slot_1_1: { isEmpty: false, title: '', text: '', rule: 'kv' } }))")
    txt = dash_text(pg)
    check('T13 slot without table name is not shown as "未找到表格:"', '未找到表格' not in txt and '张三' in txt, txt.strip()[:80])
    check('T0 no page errors (blank-slot run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T14: chat switch the way the database does it (cleared notify, CHAT_CHANGED, load notify), then an auto-fill.
    b, pg, errs = boot(p, {'highlightNew': True, 'showDashboard': False})
    pg.evaluate("() => window.__notify()"); pg.wait_for_timeout(300)
    pg.evaluate("() => { window.__data.sheet_b.content[1][2] = '6'; window.__notify(); }"); pg.wait_for_timeout(300)
    pg.evaluate("() => { window.__chat = 'B'; window.__data = {}; window.__notify(); }")  # database clears its runtime first
    pg.evaluate("() => { window.__switchChat('B'); }"); pg.wait_for_timeout(500)
    open_tab(pg, '背包')
    n0 = pg.evaluate("() => document.querySelectorAll('#acu-data-area .acu-highlight-changed').length")
    pg.evaluate("() => { window.__data.sheet_b.content[2][2] = '4'; window.__notify(); }"); pg.wait_for_timeout(400)
    if not pg.evaluate("() => !!document.querySelector('#acu-data-area.visible')"): open_tab(pg, '背包')
    n1 = pg.evaluate("() => document.querySelectorAll('#acu-data-area .acu-highlight-changed').length")
    check('T14 after chat switch: no stale highlights, next fill highlighted', n0 == 0 and n1 == 1, f'after switch={n0} after fill={n1}')
    check('T0 no page errors (chat-switch run)', not errs, '; '.join(errs)[:200])
    b.close()

print(f'\n{sum(results)}/{len(results)} passed')
