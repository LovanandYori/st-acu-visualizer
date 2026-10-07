// TauriTavern 聊天 DOM 虚拟化下的嵌入块生命周期
//
// tt-host-coupling 守的是「别让宿主 fault」；这里守的是「不 fault 之后，面板还对不对」。
// 虚拟化下 #chat 只挂视口附近几楼 + 末楼，滚出的楼被拆掉、滚回时重建成**新元素**，
// 且宿主此时不发任何 ST 事件（ChatSurface.md「错误与事件边界」）。由此带来的契约：
//
//   V-1 只有 .mes 增删才算楼层变动；spacer 重插（每次投影提交都有）不算
//   V-2 「最新 AI 楼」按 chat[] 认定；它没挂载时返回 null，不挂到视口里的历史楼上
//   V-3 发送后隐藏选项的锚点按楼层号比较：同一楼被重建（新元素同 mesid）不算换楼
//   V-4 楼层（重新）挂载后补挂嵌入块：缺块才重渲染、同一目标元素只补一次、被隐藏的选项不补
//   V-5 handleChatMutation：虚拟化下 spacer-only 变动零开销；补挂做了重渲染后不再拿旧 wrapper 归位；
//       非虚拟化（ST）保持旧语义
//   V-6 嵌入块插在同楼主面板之上（主面板固定排末位，否则下一次变动面板会跳）
//   V-7 closePanel：虚拟化下不写回 #chat.scrollTop（会打断宿主锚点校正）；非虚拟化保留
'use strict';

const { section, ok, eq, report } = require('./helpers/harness');
const { readSource, sliceConstFn, sliceDecl, sliceRange, buildScope } = require('./helpers/extract');
const vm = require('vm');

const src = readSource(process.argv[2]);

// ── 极简假 DOM + 假 jQuery：只实现被测代码用到的那几个操作 ──
class El {
  constructor(cls = '', attrs = {}) {
    this.cls = new Set(cls.split(/\s+/).filter(Boolean));
    this.attrs = { ...attrs };
    this.children = [];
    this.parent = null;
    this.nodeType = 1;
    this.classList = { contains: (c) => this.cls.has(c) };
    this.offsetParent = {};
  }
  getAttribute(k) { return k in this.attrs ? String(this.attrs[k]) : null; }
  getClientRects() { return [1]; }
  querySelector(sel) { return this.descendants().find(d => d.cls.has(sel.replace(/^\./, ''))) || null; }
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  add(...kids) { for (const k of kids) { k.detach(); k.parent = this; this.children.push(k); } return this; }
  detach() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  insertBefore(node) {
    node.detach();
    const p = this.parent;
    p.children.splice(p.children.indexOf(this), 0, node);
    node.parent = p;
  }
}
const matches = (el, sel) => {
  const m = sel.match(/^\.([\w-]+)(?:\[mesid="(\d+)"\])?$/);
  return m && el.cls.has(m[1]) && (m[2] === undefined || el.getAttribute('mesid') === m[2]);
};
function makeJq(doc) {
  const wrap = (els) => {
    const w = els.filter(Boolean);
    const api = {
      length: w.length,
      get: () => w.slice(),
      first: () => wrap(w.slice(0, 1)),
      last: () => wrap(w.slice(-1)),
      find: (sel) => wrap(w.flatMap(e => e.descendants().filter(d => matches(d, sel)))),
      children: (sel) => wrap(w.flatMap(e => e.children.filter(c => !sel || matches(c, sel)))),
      closest: (sel) => {
        let e = w[0];
        while (e && !matches(e, sel)) e = e.parent;
        return wrap([e]);
      },
      parent: () => wrap(w.map(e => e.parent)),
      attr: (k) => (w[0] ? w[0].getAttribute(k) : undefined),
      hasClass: (c) => w.some(e => e.cls.has(c)),
      append: (x) => { w[0].add(...(x.get ? x.get() : [x])); return api; },
      before: (x) => { for (const n of (x.get ? x.get() : [x])) w[0].insertBefore(n); return api; },
    };
    w.forEach((e, i) => { api[i] = e; });
    return api;
  };
  const $ = (sel) => {
    if (sel instanceof El) return wrap([sel]);
    $.queries.push(sel);
    const all = doc.descendants();
    if (sel === '#chat') return wrap([doc.chat]);
    let m = sel.match(/^#chat > (.+)$/);
    if (m) return wrap(doc.chat.children.filter(c => matches(c, m[1])));
    if (sel === '#form_sheld, #send_form') return wrap([doc.form]);
    return wrap(all.filter(e => matches(e, sel)));
  };
  $.queries = [];
  return $;
}
// 一条消息：.mes > .mes_block > .mes_text
const mes = (mesid, attrs = {}) => {
  const block = new El('mes_block').add(new El('mes_text'));
  return new El('mes', { mesid, ...attrs }).add(block);
};
const makeDoc = () => {
  const doc = new El('root');
  doc.chat = new El('chat');
  doc.form = new El('form_sheld');
  doc.add(doc.chat, doc.form);
  return doc;
};

// 依赖统一经 __deps 注入：漏注入的标识符在 strict 作用域里会真的 ReferenceError
const fwd = (name) => `const ${name} = (...a) => __deps.${name}(...a);`;
const run = (parts, ret, deps) => vm.runInNewContext(buildScope(parts, ret), { __deps: deps, Array, String, Number });

const decl = {
  touches: sliceDecl(src, 'const mutationTouchesMessages = (records) =>', 'mutationTouchesMessages'),
  adds: sliceDecl(src, 'const mutationAddsMessages = (records) =>', 'mutationAddsMessages'),
  isEmbeddable: sliceConstFn(src, 'const isEmbeddableAiMes = (el) => {', 'isEmbeddableAiMes'),
  blockOf: sliceConstFn(src, 'const blockOfMes = ($mes) => {', 'blockOfMes'),
  latestAi: sliceConstFn(src, 'const getLatestAiMesidFromChat = () => {', 'getLatestAiMesidFromChat'),
  target: sliceConstFn(src, 'const getEmbeddedTargetBlock = () => {', 'getEmbeddedTargetBlock'),
  mesidOf: sliceDecl(src, 'const mesidOfBlock = ($block) =>', 'mesidOfBlock'),
  above: sliceConstFn(src, 'const appendAboveWrapper = ($block, $el) => {', 'appendAboveWrapper'),
  reattach: sliceConstFn(src, 'const reattachEmbedsAfterRemount = () => {', 'reattachEmbedsAfterRemount'),
  handle: sliceConstFn(src, 'const handleChatMutation = (records) => {', 'handleChatMutation'),
  close: sliceConstFn(src, 'const closePanel = () => {', 'closePanel'),
  hideCheck: sliceRange(src, 'if (hideOptionsUntilUpdate && hiddenOptionsAnchorMesid != null) {',
    'if (optionStr !== lastOptionDataCheck)', 'hideCheck'),
};

const rec = (added = [], removed = []) => ({ addedNodes: added, removedNodes: removed });
const spacer = () => new El('tt-chat-spacer');
const text = () => ({ nodeType: 3 });

section('[V-1] 只有 .mes 增删才算楼层变动');
{
  const f = run([decl.touches, decl.adds], '{ touches: mutationTouchesMessages, adds: mutationAddsMessages }', {});
  ok(!f.touches([rec([spacer()], [spacer()])]), 'spacer 重插（投影提交常态）→ 不算');
  ok(!f.touches([rec([text()])]), '文本节点 → 不算（不因 classList 缺失而抛）');
  ok(f.touches([rec([spacer()]), rec([mes(5)])]) && f.adds([rec([mes(5)])]), '新增 .mes → 算变动且算新增');
  ok(f.touches([rec([], [mes(5)])]) && !f.adds([rec([], [mes(5)])]), '移除 .mes → 算变动但不算新增');
}

// 一段聊天：0=AI 1=用户 2=AI 3=用户（末楼）
const CHAT = [{ name: 'A' }, { is_user: true }, { name: 'A' }, { is_user: true }];
const targetScope = (doc, { bounded, chat }) => run(
  [fwd('getCore'), fwd('detectTTBounded'), fwd('getHostChat'),
    decl.isEmbeddable, decl.blockOf, decl.latestAi, decl.target, decl.mesidOf],
  '{ target: getEmbeddedTargetBlock, mesidOf: mesidOfBlock }',
  { getCore: () => ({ $: makeJq(doc) }), detectTTBounded: () => bounded, getHostChat: () => chat },
);

section('[V-2] 最新 AI 楼按 chat[] 认定；没挂载就返回 null');
{
  // 用户往上翻：DOM 只挂着视口里的 0 号楼和末楼 3（用户楼），真正的最新 AI 楼 2 未挂载
  const doc = makeDoc();
  doc.chat.add(mes(0), spacer(), mes(3, { is_user: 'true' }));
  const native = targetScope(doc, { bounded: false, chat: CHAT });
  eq(native.mesidOf(native.target()), '0', '对照组：DOM 倒序法会挑中视口里的历史楼 0（即本次要修的错楼）');
  const b = targetScope(doc, { bounded: true, chat: CHAT });
  ok(b.target() === null, '虚拟化：最新 AI 楼 2 未挂载 → null（不挂到错楼）');

  doc.chat.add(mes(2));
  const t = b.target();
  eq(b.mesidOf(t), '2', '楼 2 挂载后 → 命中楼 2');
  ok(t && t[0].cls.has('mes_block'), '返回的是 .mes_block（与 DOM 法同一挂点）');

  const sys = [...CHAT.slice(0, 3), { name: 'System' }, { is_system: true }, { is_user: true }];
  const sysScope = targetScope(doc, { bounded: true, chat: sys });
  eq(sysScope.mesidOf(sysScope.target()), '2', '末尾是名为 System / is_system 的楼 → 跳过，仍认定楼 2');
  ok(targetScope(doc, { bounded: true, chat: [{ is_user: true }] }).target() === null, '聊天里没有 AI 楼 → null');
  const noChat = targetScope(doc, { bounded: true, chat: null });
  eq(noChat.mesidOf(noChat.target()), '2', '拿不到 chat[] → 退回 DOM 倒序法（不因此什么都不显示）');
}

section('[V-3] 隐藏选项的锚点按楼层号比较');
{
  const check = (anchorMesid, currentMesid) => run(
    ['let hideOptionsUntilUpdate = true;', `let hiddenOptionsAnchorMesid = ${JSON.stringify(anchorMesid)};`,
      fwd('getEmbeddedTargetBlock'), fwd('mesidOfBlock'), decl.hideCheck],
    'hideOptionsUntilUpdate',
    { getEmbeddedTargetBlock: () => ({ mesid: currentMesid }), mesidOfBlock: (b) => b.mesid },
  );
  ok(check('4', '4') === true, '同一楼被虚拟化重建（新元素、同 mesid）→ 仍保持隐藏');
  ok(check('4', '6') === false, '最新 AI 楼换成新楼 → 解除隐藏');
  ok(check('4', undefined) === true, '最新 AI 楼当前未挂载 → 保持隐藏，不误解除');
}

section('[V-4] 楼层重新挂载后补挂嵌入块');
{
  const setup = ({ wanted, hidden = false, repBoxEnabled = true }) => {
    const calls = { render: 0, rep: 0 };
    const deps = {
      getConfig: () => ({ repBoxEnabled }),
      injectReplacedContentBox: () => { calls.rep++; },
      getEmbeddedTargetBlock: () => deps.$target,
      renderInterface: () => { calls.render++; },
    };
    const f = run(
      [fwd('getConfig'), fwd('injectReplacedContentBox'), fwd('getEmbeddedTargetBlock'), fwd('renderInterface'),
        `let embedWanted = ${JSON.stringify(wanted)};`, 'let lastEmbedReattachTarget = null;',
        `let hideOptionsUntilUpdate = ${hidden};`, decl.reattach],
      'reattachEmbedsAfterRemount', deps);
    return { f, calls, deps };
  };
  const blockWith = (...cls) => {
    const el = new El('mes_block');
    cls.forEach(c => el.add(new El(c)));
    return makeJq(new El())(el);
  };

  const s = setup({ wanted: { dashboard: true, options: false } });
  s.deps.$target = blockWith('mes_text');
  ok(s.f() === true && s.calls.render === 1, '想要仪表盘、目标楼里没有 → 重渲染一次并返回 true');
  ok(s.f() === false && s.calls.render === 1, '同一目标元素再次触发 → 不再重渲染（防注入失败时反复重渲染）');
  s.deps.$target = blockWith('mes_text');
  ok(s.f() === true && s.calls.render === 2, '该楼又被重建（新元素）→ 再补一次');
  ok(s.calls.rep === 3, '每次都重跑被替换正文框注入（它自带事件绑定，无需整体重渲染）');

  const present = setup({ wanted: { dashboard: true, options: true } });
  present.deps.$target = blockWith('acu-embedded-dashboard-container', 'acu-embedded-options-container');
  ok(present.f() === false && present.calls.render === 0, '嵌入块都在 → 不重渲染');

  const hidden = setup({ wanted: { dashboard: false, options: true }, hidden: true });
  hidden.deps.$target = blockWith('mes_text');
  ok(hidden.f() === false && hidden.calls.render === 0, '选项处于「发送后隐藏」→ 不为它补挂');

  const none = setup({ wanted: { dashboard: true, options: true }, repBoxEnabled: false });
  none.deps.$target = null;
  ok(none.f() === false && none.calls.render === 0, '目标楼未挂载 → 什么都不做');
  ok(none.calls.rep === 0, '被替换正文框关闭时不重跑其注入');
}

section('[V-5] handleChatMutation：只在楼层变动时干活');
{
  const setup = ({ bounded, reattachRenders = false, mode = 'fixed' }) => {
    const doc = makeDoc();
    doc.chat.add(mes(0), mes(1));
    const wrapper = new El('acu-wrapper');
    doc.add(wrapper);
    const calls = { align: 0, reattach: 0, render: [] };
    const $ = makeJq(doc);
    const deps = {
      getConfig: () => ({ ttPanelMode: mode, frontendPosition: 'bottom' }),
      renderInterface: (f) => { calls.render.push(f); },
      detectTTBounded: () => bounded,
      reattachEmbedsAfterRemount: () => { calls.reattach++; return reattachRenders; },
      alignWrapperToMessageColumnNow: () => { calls.align++; },
      requestAnimationFrame: (cb) => cb(),
    };
    const h = run(
      [fwd('getConfig'), fwd('renderInterface'), fwd('detectTTBounded'), fwd('reattachEmbedsAfterRemount'),
        fwd('alignWrapperToMessageColumnNow'), fwd('requestAnimationFrame'), 'const $ = __deps.$;',
        'let chatObsRafPending = false;', decl.touches, decl.adds,
        'let chatMutationTouchedMes = false;', 'let chatMutationAddedMes = false;', decl.handle],
      'handleChatMutation', { ...deps, $ });
    return { h, calls, doc, wrapper };
  };

  const a = setup({ bounded: true });
  a.h([rec([spacer()], [spacer()])]);
  ok(a.calls.align === 0 && a.calls.reattach === 0, '虚拟化 + 只有 spacer 变动 → 不测量、不补挂');
  ok(a.doc.children[a.doc.children.length - 1] === a.wrapper, '且不挪 wrapper');

  const b = setup({ bounded: true, reattachRenders: true });
  b.h([rec([mes(2)])]);
  ok(b.calls.reattach === 1, '虚拟化 + 新挂载楼层 → 触发补挂');
  ok(b.calls.align === 0 && b.doc.form.parent.children.indexOf(b.wrapper) === b.doc.form.parent.children.length - 1,
    '补挂做了整体重渲染 → 立即返回，不再拿旧 wrapper 归位（否则会插回一份已脱离的旧面板）');

  const c = setup({ bounded: true });
  c.h([rec([mes(2)])]);
  const kids = c.doc.form.parent.children;
  ok(kids.indexOf(c.wrapper) === kids.indexOf(c.doc.form) - 1 && c.calls.align === 1,
    '补挂没重渲染 → 照常把固定模式面板归位到输入框上方并对齐');

  const d = setup({ bounded: true });
  d.h([rec([], [mes(1)])]);
  ok(d.calls.reattach === 0 && d.calls.align === 1, '只移除楼层 → 不补挂，但仍归位/对齐');

  const st = setup({ bounded: false });
  st.h([rec([spacer()])]);
  ok(st.calls.align === 1 && st.calls.reattach === 0, '非虚拟化（ST）→ 任何子节点变动都照旧处理');

  const gone = setup({ bounded: true });
  gone.wrapper.detach();
  gone.h([rec([spacer()])]);
  eq(gone.calls.render, [true], 'wrapper 不见了 → 照旧整体重建（先于 spacer 过滤）');
}

section('[V-6] 嵌入块插在同楼主面板之上');
{
  const f = run([decl.above], 'appendAboveWrapper', {});
  const $ = makeJq(new El());
  const block = new El('mes_block').add(new El('mes_text'), new El('acu-wrapper'));
  const box = new El('acu-embedded-options-container');
  f($(block), $(box));
  eq(block.children.map(c => [...c.cls][0]), ['mes_text', 'acu-embedded-options-container', 'acu-wrapper'],
    '同楼有主面板 → 插在它前面（主面板保持末位，handleChatMutation 不会再挪它）');
  const plain = new El('mes_block').add(new El('mes_text'));
  f($(plain), $(new El('acu-embedded-dashboard-container')));
  eq(plain.children.map(c => [...c.cls][0]), ['mes_text', 'acu-embedded-dashboard-container'], '没有主面板 → 追加到末尾');
}

section('[V-7] closePanel：虚拟化下不写回 #chat.scrollTop');
{
  const runClose = (bounded) => {
    const timers = [];
    const writes = [];
    const chain = new Proxy(function () {}, {
      get: (t, k) => (k === 'length' ? 1 : k === 'scrollTop' ? (v) => (v === undefined ? 120 : writes.push(v)) : () => chain),
    });
    const set = { clear() {} };
    run([fwd('getCore'), fwd('getConfig'), fwd('detectTTBounded'), fwd('saveActiveTabState'), fwd('setTimeout'),
      'let isMultiSelectMode = true;', 'const selectedRows = __deps.set, pendingDeletes = __deps.set, pendingDeleteRowIds = __deps.set;',
      'const updateDynamicActionButton = undefined;', decl.close], 'closePanel', {
      getCore: () => ({ $: () => chain }), getConfig: () => ({}), detectTTBounded: () => bounded,
      saveActiveTabState() {}, setTimeout: (cb) => { timers.push(cb); }, set,
    })();
    timers.forEach(cb => cb());
    return writes;
  };
  eq(runClose(true), [], '虚拟化 → 不写回（宿主自己做锚点校正）');
  eq(runClose(false), [120], '非虚拟化 → 照旧写回关闭前的位置');
}

report('tt-virtualization');
