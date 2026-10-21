// 行动选项的归属与显隐
//
// 用户拍板的规则（V17.7.5）：选项只属于「填出它的那一楼」。
// **当且仅当最新楼层是 AI 楼、且这一楼有自己的选项时才显示**；AI 楼一旦不再是最新楼层，它的选项就不出现。
//
// 此前的实现是「发送时藏起，最新 AI 楼一换就解除」——而新 AI 楼在**开始生成**那一刻就出现了，
// 于是第 3 个 AI 楼刚开始生成就把第 2 楼的旧选项挂上来，一直挂到新选项填完（用户实报）。
//
// 守的契约：
//   O-1 最新楼层身份：跳过隐藏/系统楼；用户楼 → null；含 swipe_id 与 send_date（滑新回复 / 删楼重生成都算另一楼）
//   O-2 用户实报场景逐步回放：发送 → 用户楼入楼 → 新 AI 楼生成中 → 生成中 DB 回退数据 → 生成结束 → 填表完成
//   O-3 滑动生成新回复 / 滑回已有回复 / 删楼后同楼号重新生成
//   O-4 后台（quiet / dryRun）生成不影响归属；生成被停止时撤销「发送时先藏」
//   O-5 拿不到聊天数据时保持旧行为（显示）
//   O-6 syncOptionsVisibility：该藏立刻拿掉、该显才重渲染（编辑中/目标楼未挂载时不打扰）
//   O-7 renderInterface 真的走这套规则（源码顺序检查：renderInterface 体量太大无法整体进 vm，如实标注）
'use strict';

const { section, ok, eq, report } = require('./helpers/harness');
const { readSource, sliceConstFn, buildScope } = require('./helpers/extract');
const vm = require('vm');

const src = readSource(process.argv[2]);

const decl = {
  latestKey: sliceConstFn(src, 'const getLatestFloorKey = () => {', 'getLatestFloorKey'),
  note: sliceConstFn(src, 'const noteOptionDataChange = (optionStr) => {', 'noteOptionDataChange'),
  show: sliceConstFn(src, 'const shouldShowOptions = () => {', 'shouldShowOptions'),
  sync: sliceConstFn(src, 'const syncOptionsVisibility = () => {', 'syncOptionsVisibility'),
  suppress: sliceConstFn(src, 'const suppressOptionsForSend = () => {', 'suppressOptionsForSend'),
  floorEvents: sliceConstFn(src, 'const trySubscribeFloorEvents = () => {', 'trySubscribeFloorEvents'),
};

const fwd = (name) => `const ${name} = (...a) => __deps.${name}(...a);`;

/**
 * 把真实源码装进同一个 strict 作用域：状态变量与生产代码同名，
 * 宿主事件通过真实的 trySubscribeFloorEvents 订阅到假事件总线上。
 */
function makeWorld({ chat = [], noChat = false } = {}) {
  const handlers = {};
  const timers = [];
  const evTypes = Object.fromEntries(['GENERATION_STARTED', 'GENERATION_ENDED', 'GENERATION_STOPPED',
    'MESSAGE_SENT', 'MESSAGE_RECEIVED', 'MESSAGE_SWIPED', 'MESSAGE_DELETED'].map(n => [n, n]));
  const dom = { optionsPresent: false, removed: 0, renders: 0, editing: false, targetMounted: true };
  const $ = (sel) => {
    if (sel !== '.acu-embedded-options-container') throw new Error('unexpected selector ' + sel);
    return { length: dom.optionsPresent ? 1 : 0, remove() { if (dom.optionsPresent) dom.removed++; dom.optionsPresent = false; } };
  };
  const deps = {
    getHostChat: () => (noChat ? null : chat),
    getCore: () => ({ $ }),
    inEditingContext: () => dom.editing,
    getEmbeddedTargetBlock: () => (dom.targetMounted ? {} : null),
    // 真实 renderInterface 会按 shouldShowOptions 决定是否注入选项；这里只模拟这一条
    renderInterface: () => { dom.renders++; dom.optionsPresent = api.shouldShow(); },
    getHostEventBus: () => ({ evSrc: { on: (n, fn) => { handlers[n] = fn; } }, evTypes }),
    // 与浏览器一样异步：先排队，事件处理返回后再统一执行（同步执行会让「已排程」标记永远清不掉）
    setTimeout: (cb) => { timers.push(cb); return timers.length; },
  };
  const api = vm.runInNewContext(buildScope([
    fwd('getHostChat'), fwd('getCore'), fwd('inEditingContext'), fwd('getEmbeddedTargetBlock'),
    fwd('renderInterface'), fwd('getHostEventBus'), fwd('setTimeout'),
    'const $ = (...a) => __deps.getCore().$(...a);',
    "let lastOptionDataCheck = '';", 'let optionsOwnerFloorKey = null;',
    'let hostGenerating = false;', 'let optionsSendSuppressedKey = null;',
    // 悬浮球形态（V17.8.1）另有分支，这里测的是默认形态
    'const isFloatMode = () => false;',
    decl.latestKey, decl.note, decl.show, decl.sync, decl.suppress, decl.floorEvents,
  ], `{
    latestKey: getLatestFloorKey, note: noteOptionDataChange, shouldShow: shouldShowOptions,
    sync: syncOptionsVisibility, suppress: suppressOptionsForSend, subscribe: trySubscribeFloorEvents,
    state: () => ({ owner: optionsOwnerFloorKey, generating: hostGenerating, suppressed: optionsSendSuppressedKey }),
  }`), { __deps: deps, Array, String, Number, Object, console });
  api.subscribe();
  // 一次渲染 = 记下选项数据 + 按规则决定挂不挂（与 renderInterface 中的调用顺序一致）
  const render = (optionStr) => { api.note(optionStr); dom.optionsPresent = api.shouldShow(); };
  const emit = (name, ...args) => {
    if (handlers[name]) handlers[name](...args);
    while (timers.length) timers.shift()();
  };
  return { api, chat, dom, render, emit, visible: () => dom.optionsPresent };
}

let clock = 1000;
const ai = (extra = {}) => ({ name: 'A', mes: 'x', send_date: String(clock++), ...extra });
const user = () => ({ is_user: true, mes: 'u', send_date: String(clock++) });

section('[O-1] 最新楼层身份');
{
  const w = makeWorld({ chat: [user(), ai({ swipe_id: 0, send_date: 'd1' })] });
  eq(w.api.latestKey(), '1|0|d1', 'AI 楼 → 楼号|swipe_id|send_date');
  w.chat.push(user());
  eq(w.api.latestKey(), null, '最新是用户楼 → null（不显示）');
  w.chat.push({ is_system: true, mes: 'note', send_date: 'sys' });
  eq(w.api.latestKey(), null, '末尾的隐藏/系统楼被跳过，看的是它前面那楼（用户楼 → null）');
  w.chat.splice(2);
  w.chat.push({ is_system: true, mes: 'note', send_date: 'sys' });
  eq(w.api.latestKey(), '1|0|d1', 'AI 楼后面跟一条隐藏/系统楼 → 仍认这个 AI 楼');
  w.chat.splice(2);
  w.chat[1].swipe_id = undefined;
  eq(w.api.latestKey(), '1|0|d1', '新楼尚无 swipe_id → 按 0 计（与生成结束后补上的 0 同一身份）');
  ok(makeWorld({ chat: [] }).api.latestKey() === null, '空聊天 → null');
}

section('[O-2] 用户实报场景：新 AI 楼开始生成时不得显示上一楼的选项');
{
  const w = makeWorld({ chat: [user(), ai(), user(), ai()] }); // 第 2 个 AI 楼是最新楼
  w.render('O2');
  ok(w.visible(), '第 2 个 AI 楼是最新楼且有选项 → 显示');

  w.api.suppress();
  ok(!w.visible(), '点发送（或点选项自动发送）→ 立即藏起');
  w.render('O2');
  ok(!w.visible(), '用户楼尚未入楼期间（剧情推进等）有渲染 → 仍藏着');

  w.chat.push(user()); w.emit('MESSAGE_SENT', 4);
  ok(!w.visible(), '用户楼入楼 → 最新楼不是 AI 楼 → 不显示');

  w.emit('GENERATION_STARTED', 'normal', {}, false);
  w.chat.push(ai());
  w.render('O2');
  ok(!w.visible(), '第 3 个 AI 楼开始生成 → 不显示第 2 楼的选项（本次修复的核心）');

  w.render('O2-rollback');
  ok(!w.visible(), '生成中 DB 发来的数据变化（回退/重放）→ 不认领，仍不显示');
  ok(w.api.state().owner !== w.api.latestKey(), '且归属没有被挪给正在生成的新楼');

  w.emit('GENERATION_ENDED', 5);
  w.render('O2-rollback');
  ok(!w.visible(), '生成结束但新选项还没填 → 仍不显示');

  w.render('O3');
  ok(w.visible(), '填表写入新选项 → 归属第 3 个 AI 楼并显示');
  eq(w.api.state().suppressed, null, '「发送时先藏」已随生成结束撤销');
}

section('[O-3] 滑动 / 滑回 / 删楼后重新生成');
{
  const w = makeWorld({ chat: [user(), ai({ swipe_id: 0 })] });
  w.render('S0');
  ok(w.visible(), '起点：最新 AI 楼有选项');

  w.chat[1].swipe_id = 1; w.emit('MESSAGE_SWIPED', 1);
  ok(!w.visible(), '滑到新回复 → 这一版还没有选项 → 立即撤掉');
  w.emit('GENERATION_STARTED', 'swipe', {}, false);
  w.render('S-prev-floor');
  ok(!w.visible(), '生成中 DB 回退到上一楼的选项 → 不显示');
  w.emit('GENERATION_ENDED', 1);
  w.render('S1');
  ok(w.visible(), '新回复填完选项 → 显示');

  w.chat[1].swipe_id = 0; w.emit('MESSAGE_SWIPED', 1);
  ok(!w.visible(), '滑回旧回复（不生成）→ 先撤掉');
  w.render('S0');
  ok(w.visible(), 'DB 换回该回复的数据 → 归属它并显示');

  const r = makeWorld({ chat: [user(), ai({ swipe_id: 0 })] });
  r.render('R0');
  const sameIndex = '1|0|';
  r.chat.splice(1, 1); r.emit('MESSAGE_DELETED', 1);
  r.emit('GENERATION_STARTED', 'regenerate', {}, false);
  r.chat.push(ai({ swipe_id: 0 }));
  ok(r.api.latestKey().startsWith(sameIndex) && !r.visible(), '删楼后同楼号重新生成 → 视为另一楼，不显示旧选项');
}

section('[O-4] 后台生成不影响归属；停止生成撤销「先藏」');
{
  const w = makeWorld({ chat: [user(), ai()] });
  w.emit('GENERATION_STARTED', 'quiet', {}, false);
  w.emit('GENERATION_STARTED', 'normal', {}, true);
  w.emit('GENERATION_STARTED', 'normal', { quiet_prompt: 'x' }, false);
  ok(w.api.state().generating === false, 'quiet / dryRun / quiet_prompt 都不算前台生成');
  w.render('Q1');
  ok(w.visible(), '因而此时的数据变化照常认领');

  w.api.suppress();
  ok(!w.visible(), '点了发送 → 藏起');
  w.emit('GENERATION_STOPPED');
  ok(w.api.shouldShow(), '生成被停止、最新楼没变 → 撤销「先藏」，原选项可再显示');
  ok(w.dom.renders === 1 && w.visible(), '并通过一次常规渲染挂回来');
}

section('[O-5] 拿不到聊天数据时保持旧行为');
{
  const w = makeWorld({ noChat: true });
  w.render('X');
  ok(w.visible(), 'getHostChat 为 null → 无从判断，照常显示');
}

section('[O-6] syncOptionsVisibility：该藏立刻拿掉、该显才重渲染');
{
  const w = makeWorld({ chat: [user(), ai()] });
  w.render('A');
  w.chat.push(user());
  w.api.sync();
  ok(!w.visible() && w.dom.removed === 1 && w.dom.renders === 0, '不该显示 → 直接移除，不做整体重渲染');
  w.chat.pop();
  w.dom.editing = true;
  w.api.sync();
  ok(w.dom.renders === 0, '该显示但用户正在编辑 → 不打扰（下一次渲染自然补上）');
  w.dom.editing = false;
  w.dom.targetMounted = false;
  w.api.sync();
  ok(w.dom.renders === 0, '该显示但目标楼没挂载（虚拟化翻到别处）→ 不空渲染');
  w.dom.targetMounted = true;
  w.api.sync();
  ok(w.dom.renders === 1 && w.visible(), '该显示且缺 → 一次常规渲染挂回来');
  w.api.sync();
  ok(w.dom.renders === 1, '已显示 → 不重复渲染');
}

section('[O-7] renderInterface 接线（源码顺序检查，非行为测试）');
{
  const r0 = src.indexOf('const renderInterface = (forceRefresh = false) => {');
  const body = src.slice(r0, src.indexOf('insertHtmlToPage(html);', r0));
  const noteAt = body.indexOf('noteOptionDataChange(optionStr);');
  const gate = body.match(/optionTables\.length > 0 && shouldShowOptions\(\)/g) || [];
  ok(r0 > 0 && noteAt > 0, '渲染时先把选项数据交给 noteOptionDataChange 认领归属');
  eq(gate.length, 1, '生成选项按钮恰好一处，且受 shouldShowOptions 门控');
  ok(noteAt < body.search(/optionTables\.length > 0 && shouldShowOptions/), '认领发生在门控判断之前（否则本次渲染用的是旧归属）');
  ok(!/hideOptionsUntilUpdate|hiddenOptionsAnchor/.test(src), '旧的「换楼即解除隐藏」状态已彻底移除（防新旧两套规则并存）');
}

report('options-ownership');
