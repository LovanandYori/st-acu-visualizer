// 设置保存契约（V17.8.2：「允许手动编辑表格」点了没反应）
//
// 守的契约：
//   C-1 正常写入：写进 localStorage，内存缓存清空（下次按存储读），返回 true
//   C-2 存储满、是前端自己的高亮快照占的：腾掉快照后重试成功，设置保存下来，不提示
//   C-3 存储一直写不进：新设置留在内存里，本次页面 getConfig 读到新值；只提示一次；返回 false
//       （V17.8.1 吞掉异常后清空缓存，getConfig 又读回旧值——开关会动，功能没开）
//   C-4 之后再改别的设置时，前一次没写进去的改动不会丢
//
// 跑的是真实的 getConfig / saveConfig 源码。
'use strict';

const { section, ok, eq, report } = require('./helpers/harness');
const { readSource, sliceRange, buildScope } = require('./helpers/extract');
const vm = require('vm');

const src = readSource(process.argv[2]);
const block = sliceRange(src, '    let configCache = null;', '    // M-03 存储缓存补齐', 'getConfig/saveConfig block');

function makeEnv(failMode) {
  const store = new Map();
  const toasts = [];
  const localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    removeItem: k => { store.delete(k); },
    setItem: (k, v) => {
      if (k === 'acu_ui_config_v18') {
        if (failMode === 'always') throw new Error('QuotaExceededError');
        if (failMode === 'snapshot' && store.has('acu_data_snapshot_v18_5')) throw new Error('QuotaExceededError');
      }
      store.set(k, String(v));
    },
  };
  store.set('acu_ui_config_v18', JSON.stringify({ theme: 'dark', allowTableEdit: false }));
  store.set('acu_data_snapshot_v18_5', '{"big":"snapshot"}');
  const scope = buildScope([
    "const STORAGE_KEY_UI_CONFIG = 'acu_ui_config_v18';",
    "const STORAGE_KEY_LAST_SNAPSHOT = 'acu_data_snapshot_v18_5';",
    'const DEFAULT_CONFIG = { theme: "aurora", allowTableEdit: false, fontSize: 13 };',
    'const applyConfigStyles = () => {};',
    block,
    'const __peek = () => configCache;',
  ], '{ getConfig, saveConfig, __peek }');
  const api = vm.runInNewContext(scope, {
    localStorage, window: { toastr: { warning: m => toasts.push(m) } },
    console: { ...console, error() {} }, JSON, Object, String,
  });
  return { api, store, toasts };
}

section('[C-1] 正常写入');
{
  const { api, store, toasts } = makeEnv(null);
  const r = api.saveConfig({ allowTableEdit: true });
  eq(r, true, '返回 true');
  eq(JSON.parse(store.get('acu_ui_config_v18')).allowTableEdit, true, '写进了存储');
  eq(api.__peek(), null, '内存缓存清空，下次按存储读');
  eq(api.getConfig().allowTableEdit, true, 'getConfig 读到新值');
  eq(toasts.length, 0, '没有警告');
  ok(store.has('acu_data_snapshot_v18_5'), '写入顺利时不动高亮快照');
}

section('[C-2] 存储满、被前端自己的快照占着');
{
  const { api, store, toasts } = makeEnv('snapshot');
  const r = api.saveConfig({ allowTableEdit: true });
  eq(r, true, '腾掉快照后保存成功');
  ok(!store.has('acu_data_snapshot_v18_5'), '快照被腾掉');
  eq(JSON.parse(store.get('acu_ui_config_v18')).allowTableEdit, true, '设置保存下来');
  eq(toasts.length, 0, '没有警告');
}

section('[C-3] 存储一直写不进');
{
  const { api, store, toasts } = makeEnv('always');
  const r = api.saveConfig({ allowTableEdit: true });
  eq(r, false, '返回 false（调用方不能说「已保存」）');
  eq(JSON.parse(store.get('acu_ui_config_v18')).allowTableEdit, false, '存储里仍是旧值');
  eq(api.getConfig().allowTableEdit, true, '本次页面 getConfig 读到新值（开关点了就生效）');
  eq(api.getConfig().theme, 'dark', '其余旧设置不丢');
  eq(toasts.length, 1, '提示一次');
  api.saveConfig({ fontSize: 15 });
  eq(toasts.length, 1, '再失败不重复提示');
  section('[C-4] 后续改动不丢前一次没写进去的设置');
  eq(api.getConfig().allowTableEdit, true, '改字号后编辑开关仍是开');
  eq(api.getConfig().fontSize, 15, '字号也生效');
}

report('config-persist');
