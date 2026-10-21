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

def boot(p, config=None, pre=None, post_mock=None, before_mock=None, viewport=None, wait_state='visible'):
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
    pg.wait_for_selector('.acu-nav-btn', timeout=5000, state=wait_state)
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

    # T15: no jQuery click/input handler on any ancestor of ST's message edit controls.
    # 泉此方悬浮窗 7.5+ audits these ancestors and blocks native editing if a foreign one exists
    # (V17.7.9 had click.acu_autoclose on body). The outside-click auto-close must still work.
    b, pg, errs = boot(p, {'showDashboard': False})
    open_tab(pg, '背包')
    foreign = pg.evaluate("""() => {
        const mes = document.querySelector('#chat .mes[mesid="1"] .mes_block');
        mes.insertAdjacentHTML('afterbegin', '<div class="mes_buttons"><div class="mes_edit"></div></div><textarea id="curEditTextarea" class="edit_textarea"></textarea>');
        const out = [];
        for (const sel of ['.mes_edit', '#curEditTextarea']) {
          const target = document.querySelector(sel);
          for (let n = target; n && n !== document; n = n.parentNode) {
            for (const type of ['click', 'input']) {
              const list = jQuery._data(n, 'events')?.[type] || [];
              list.forEach((h, i) => {
                const direct = i >= (list.delegateCount || 0);
                let hit = direct;
                for (let el = target; !hit && el && el !== n; el = el.parentNode) if (el.nodeType === 1 && el.matches(h.selector)) hit = true;
                if (hit) out.push(`${sel}<-${n.id || n.className || n.nodeName}:${type}.${h.namespace}`);
              });
            }
          }
        }
        return out; }""")
    vis = "() => !!document.querySelector('#acu-data-area.visible')"
    was_open = pg.evaluate(vis)
    pg.evaluate("() => document.querySelector('#chat .mes[mesid=\"0\"] .mes_text').click()"); pg.wait_for_timeout(300)
    check('T15 no foreign jQuery handler above edit controls; outside click still closes panel',
          not foreign and was_open and not pg.evaluate(vis), f'foreign={foreign} open={was_open}')
    check('T0 no page errors (edit-guard run)', not errs, '; '.join(errs)[:200])
    b.close()

    # T16: floating-ball form (V17.8.1). Nothing is shown under the messages; one draggable ball.
    # Tap → vertical sub-balls (dashboard / tables / action options); each opens its own window.
    # Outside click or tapping the ball (now ×) closes everything; the open table is restored next time.
    # Dragging snaps to an edge and is remembered; switching back to the default form restores the old layout.
    FLOAT_OPTS = "() => { window.__data.sheet_o = { name: '行动选项', orderNo: 2, content: [['row_id','选项一','选项二'], ['1','去酒馆','回家']] }; }"
    FLOAT_CHAT = "() => { window.__stChat = [{ is_user: true, mes: 'hi', send_date: 'u1' }, { is_user: false, mes: 'hello', send_date: 'a1' }]; }"
    ball_box = "() => { const b = document.getElementById('acu-float-ball'); const r = b?.getBoundingClientRect(); return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2, left: r.left, top: r.top, w: r.width, dot: b.classList.contains('acu-float-has-dot') } : null; }"
    shown = "s => { const w = document.querySelector(s); return !!w && getComputedStyle(w).display !== 'none'; }"
    subs = "() => [...document.querySelectorAll('#acu-float-menu.acu-float-open .acu-float-sub')].map(e => { const r = e.getBoundingClientRect(); return { v: e.dataset.view, l: r.left, t: r.top, b: r.bottom }; })"
    def tap_sub(pg, view):
        pg.evaluate("v => { const r = document.querySelector(`#acu-float-menu .acu-float-sub[data-view='${v}'] .acu-float-sub-btn`).getBoundingClientRect(); window.__pt = [r.left + r.width / 2, r.top + r.height / 2]; }", view)
        pt = pg.evaluate("() => window.__pt"); pg.mouse.click(pt[0], pt[1]); pg.wait_for_timeout(300)
    for vp, label in (({'width': 1200, 'height': 900}, 'desktop'), ({'width': 390, 'height': 844}, 'phone')):
        b, pg, errs = boot(p, {'floatBall': True, 'showOptionPanel': True}, viewport=vp, wait_state='attached', before_mock=FLOAT_CHAT, pre=FLOAT_OPTS)
        pg.evaluate("() => window.__notify()"); pg.wait_for_timeout(300)
        bb = pg.evaluate(ball_box)
        place = pg.evaluate("() => ({ onBody: document.querySelector('.acu-wrapper')?.parentNode === document.body, inChat: document.querySelectorAll('#chat .acu-wrapper, #chat .acu-embedded-dashboard-container, #chat .acu-embedded-options-container').length })")
        check(f'T16 [{label}] only a ball: nothing under the messages, panel on body and hidden, option dot shown',
              bool(bb) and place['onBody'] and place['inChat'] == 0 and not pg.evaluate(shown, '.acu-wrapper') and bb['dot'], f'ball={bb} place={place}')
        pg.mouse.click(bb['x'], bb['y']); pg.wait_for_timeout(300)
        items = pg.evaluate(subs)
        views = [i['v'] for i in items]
        check(f'T16 [{label}] tap → sub-balls stacked vertically, on screen, no window yet',
              views == ['dash', 'table', 'options'] and len({round(i['l']) for i in items}) == 1 and all(0 <= i['t'] and i['b'] <= vp['height'] for i in items)
              and not pg.evaluate(shown, '.acu-wrapper') and not pg.evaluate(shown, '#acu-float-options'), json.dumps(items))
        tap_sub(pg, 'table')
        menu_hidden = not pg.evaluate(shown, '#acu-float-menu')
        open_tab(pg, '背包')
        geo = pg.evaluate("""() => { const w = document.querySelector('.acu-wrapper').getBoundingClientRect(); const d = document.querySelector('#acu-data-area.visible')?.getBoundingClientRect();
            return { wl: w.left, wr: w.right, dTop: d ? d.top : null, cards: document.querySelectorAll('#acu-data-area .acu-data-card').length }; }""")
        check(f'T16 [{label}] tables ball opens the panel; table panel fits on screen',
              menu_hidden and geo['dTop'] is not None and geo['dTop'] >= 0 and geo['wl'] >= 0 and geo['wr'] <= vp['width'] and geo['cards'] == 3, json.dumps(geo))
        pg.evaluate("() => document.querySelector('#chat .mes[mesid=\"0\"] .mes_text').click()"); pg.wait_for_timeout(250)
        closed = not pg.evaluate(shown, '.acu-wrapper') and not pg.evaluate(shown, '#acu-float-menu')
        pg.mouse.click(bb['x'], bb['y']); pg.wait_for_timeout(250); tap_sub(pg, 'table')
        restored = pg.evaluate("() => !!document.querySelector('#acu-data-area.visible .acu-data-card')")
        pg.mouse.click(bb['x'], bb['y']); pg.wait_for_timeout(250)
        check(f'T16 [{label}] outside click closes all; tables ball restores the table; tapping the ball (×) closes',
              closed and restored and not pg.evaluate(shown, '.acu-wrapper'), f'closed={closed} restored={restored}')
        pg.mouse.click(bb['x'], bb['y']); pg.wait_for_timeout(250); tap_sub(pg, 'dash')
        dash = pg.evaluate("() => !!document.querySelector('#acu-data-area.visible .acu-dash-container')")
        pg.mouse.click(bb['x'], bb['y']); pg.wait_for_timeout(250)
        check(f'T16 [{label}] dashboard ball shows the dashboard in the panel', dash)
        pg.mouse.click(bb['x'], bb['y']); pg.wait_for_timeout(250); tap_sub(pg, 'options')
        og = pg.evaluate("""() => { const w = document.querySelector('#acu-float-options'); const r = w?.getBoundingClientRect();
            return r ? { shown: getComputedStyle(w).display !== 'none', top: r.top, l: r.left, r: r.right, btns: [...w.querySelectorAll('.acu-opt-btn')].map(b => b.textContent) } : null; }""")
        pg.evaluate("() => document.querySelector('#acu-float-options .acu-opt-btn').click()"); pg.wait_for_timeout(300)
        ta = pg.evaluate("() => document.querySelector('#send_textarea').value")
        check(f'T16 [{label}] options ball opens the options window; picking one fills the input and closes it',
              og and og['shown'] and og['top'] >= 0 and og['r'] <= vp['width'] and og['btns'] == ['去酒馆', '回家'] and ta == '去酒馆'
              and not pg.evaluate(shown, '#acu-float-options'), f'{og} input={ta!r}')
        pg.mouse.move(bb['x'], bb['y']); pg.mouse.down(); pg.mouse.move(bb['x'] - 120, bb['y'] + 40, steps=6); pg.mouse.move(40, 300, steps=6); pg.mouse.up(); pg.wait_for_timeout(350)
        nb = pg.evaluate(ball_box)
        saved = pg.evaluate("() => JSON.parse(localStorage.getItem('acu_float_ball_pos') || 'null')")
        not_toggled = not pg.evaluate(shown, '#acu-float-menu')
        pg.mouse.click(nb['x'], nb['y']); pg.wait_for_timeout(300)
        lab = pg.evaluate("() => { const m = document.getElementById('acu-float-menu'); const l = m.querySelector('.acu-float-sub-label').getBoundingClientRect(); return { left: m.classList.contains('acu-float-side-left'), labelL: l.left }; }")
        check(f'T16 [{label}] drag snaps to the left edge, is remembered, does not toggle; labels move to the right side',
              nb and abs(nb['left'] - 8) < 1 and saved and saved.get('side') == 'left' and not_toggled and lab['left'] and lab['labelL'] > nb['left'] + 40,
              f'ball={nb} saved={saved} label={lab}')
        pg.mouse.click(nb['x'], nb['y']); pg.wait_for_timeout(250)
        if label == 'desktop':
            pg.mouse.click(nb['x'], nb['y']); pg.wait_for_timeout(250); tap_sub(pg, 'table')
            pg.evaluate("() => document.querySelector('#acu-btn-settings').click()"); pg.wait_for_timeout(300)
            pg.evaluate("() => document.querySelector('[data-target=\"sec-layout\"]').click()"); pg.wait_for_timeout(300)
            pg.select_option('#cfg-float-ball', 'default'); pg.wait_for_timeout(300)
            pg.evaluate("() => document.querySelector('#dlg-close').click()"); pg.wait_for_timeout(300)
            back = pg.evaluate("""() => ({ ball: !!document.getElementById('acu-float-ball') || !!document.getElementById('acu-float-menu') || !!document.getElementById('acu-float-options'),
                inChat: !!document.querySelector('#chat > .acu-wrapper'), dash: !!document.querySelector('#chat .acu-embedded-dashboard-container'),
                cfg: JSON.parse(localStorage.getItem('acu_ui_config_v18')).floatBall })""")
            check('T16 switching back to the default form removes the balls and restores the bottom bar and embedded dashboard',
                  not back['ball'] and back['inChat'] and back['dash'] and back['cfg'] is False and pg.evaluate(shown, '.acu-wrapper'), json.dumps(back))
        check(f'T0 no page errors (float-ball {label} run)', not errs, '; '.join(errs)[:200])
        b.close()

    # T17: floating-ball edge cases — chat switch while open (no duplicates, window kept), sort mode
    # (ball and outside click ignored), small viewport (keyboard), a refresh mid-drag keeps the drag state,
    # TauriTavern virtualization (panel stays on body, no TT classes).
    b, pg, errs = boot(p, {'floatBall': True}, wait_state='attached')
    def fball(pg):
        r = pg.evaluate("() => { const r = document.getElementById('acu-float-ball').getBoundingClientRect(); return [r.left + 23, r.top + 23]; }")
        pg.mouse.click(r[0], r[1]); pg.wait_for_timeout(250)
    def fsub(pg, v):
        pg.evaluate("v => document.querySelector(`#acu-float-menu .acu-float-sub[data-view='${v}']`).click()", v); pg.wait_for_timeout(300)
    fball(pg); fsub(pg, 'table'); open_tab(pg, '背包')
    pg.evaluate("() => window.__switchChat('B')"); pg.wait_for_timeout(500)
    st = pg.evaluate("() => ({ balls: document.querySelectorAll('#acu-float-ball').length, wrappers: document.querySelectorAll('.acu-wrapper').length, menus: document.querySelectorAll('#acu-float-menu').length })")
    check('T17 chat switch while open: one ball/panel/menu, window kept', st == {'balls': 1, 'wrappers': 1, 'menus': 1} and pg.evaluate(shown, '.acu-wrapper'), json.dumps(st))
    pg.evaluate("() => document.querySelector('#acu-btn-settings').click()"); pg.wait_for_timeout(300)
    pg.evaluate("() => document.querySelector('#btn-enter-sort').click()"); pg.wait_for_timeout(400)
    fball(pg); pg.evaluate("() => document.querySelector('#chat .mes_text').click()"); pg.wait_for_timeout(300)
    in_sort = pg.evaluate(shown, '.acu-wrapper')
    pg.evaluate("() => document.querySelector('#acu-btn-cancel-mode')?.click()"); pg.wait_for_timeout(400)
    check('T17 sort mode: ball tap and outside click do not close the window', in_sort and pg.evaluate(shown, '.acu-wrapper'))
    pg.set_viewport_size({'width': 1200, 'height': 400}); pg.wait_for_timeout(400)
    g = pg.evaluate("() => { const w = document.querySelector('.acu-wrapper').getBoundingClientRect(); const x = document.getElementById('acu-float-ball').getBoundingClientRect(); return { wt: w.top, wb: w.bottom, bt: x.top, bb: x.bottom }; }")
    check('T17 viewport shrinks (keyboard): ball and window stay on screen', g['bt'] >= 0 and g['bb'] <= 400 and g['wt'] >= 0 and g['wb'] <= 400, json.dumps(g))
    pg.set_viewport_size({'width': 1200, 'height': 900}); pg.wait_for_timeout(300)
    fball(pg)
    r0 = pg.evaluate("() => { const r = document.getElementById('acu-float-ball').getBoundingClientRect(); return [r.left + 23, r.top + 23]; }")
    pg.mouse.move(r0[0], r0[1]); pg.mouse.down(); pg.mouse.move(r0[0] - 50, r0[1] + 50, steps=5)
    pg.evaluate("() => window.__notify()"); pg.wait_for_timeout(200)
    dragging = pg.evaluate("() => document.getElementById('acu-float-ball').classList.contains('dragging')")
    pg.mouse.up(); pg.wait_for_timeout(300)
    check('T17 a table refresh mid-drag keeps the drag state', dragging)
    # second outside click must not forget the open table; a refresh must not replay the open animation
    fball(pg); fsub(pg, 'table')
    if not pg.evaluate("() => !!document.querySelector('#acu-data-area.visible .acu-data-card')"): open_tab(pg, '背包')
    pg.evaluate("() => window.__notify()"); pg.wait_for_timeout(50)
    anim = pg.evaluate("() => getComputedStyle(document.querySelector('.acu-wrapper')).animationName")
    pg.evaluate("() => document.querySelector('#chat .mes_text').click()"); pg.wait_for_timeout(250)
    pg.evaluate("() => document.querySelector('#chat .mes_text').click()"); pg.wait_for_timeout(250)
    fball(pg); fsub(pg, 'table')
    kept = pg.evaluate("() => !!document.querySelector('#acu-data-area.visible .acu-data-card')")
    reanim = pg.evaluate("() => getComputedStyle(document.querySelector('.acu-wrapper')).animationName")
    check('T17 refresh while open does not replay the open animation; reopening does', anim == 'none' and reanim == 'acuFloatIn', f'{anim} / {reanim}')
    check('T17 clicking outside twice still remembers the open table', kept)
    fball(pg)
    check('T0 no page errors (float-ball edge run)', not errs, '; '.join(errs)[:200])
    b.close()
    b, pg, errs = boot(p, {'floatBall': True}, wait_state='attached', before_mock="() => { window.__TAURITAVERN__ = { api: { chatSurface: { isManagedOwnershipRequired: () => true } } }; }")
    fball(pg); fsub(pg, 'table'); open_tab(pg, '背包')
    pg.evaluate("() => { const m = document.createElement('div'); m.className = 'mes'; m.setAttribute('mesid', '2'); m.innerHTML = '<div class=\"mes_block\"><div class=\"mes_text\">x</div></div>'; document.getElementById('chat').appendChild(m); }"); pg.wait_for_timeout(300)
    st = pg.evaluate("() => { const w = document.querySelector('.acu-wrapper'); return { onBody: w.parentNode === document.body, tt: [...w.classList].filter(c => c.startsWith('acu-tt')), cards: document.querySelectorAll('#acu-data-area .acu-data-card').length }; }")
    check('T17 TT virtualization: panel stays on body without TT classes and works', st == {'onBody': True, 'tt': [], 'cards': 3} and not errs, json.dumps(st) + str(errs)[:200])
    b.close()

print(f'\n{sum(results)}/{len(results)} passed')
