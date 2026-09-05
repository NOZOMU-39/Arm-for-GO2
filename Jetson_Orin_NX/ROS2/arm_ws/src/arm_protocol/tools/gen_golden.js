// 黄金向量生成器：装载交互界面 index.html 的 JS（vm 沙箱），对组帧函数输出标准答案
// 运行（Windows 本机，node 已装）:
//   node tools/gen_golden.js <机械臂操作交互界面/index.html 绝对路径> <输出 json 路径>
// 用途: 产物 test/golden_vectors.json 是 Python 版 arm_protocol 的逐字节验收尺。
// 装载 stub 复用自 机械臂操作交互界面\测试\proto_core_test.js（DOM/bridge 占位）。
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const htmlPath = process.argv[2];
const outPath = process.argv[3];
if (!htmlPath || !outPath) {
  console.error('用法: node gen_golden.js <index.html路径> <输出json路径>');
  process.exit(1);
}
const html = fs.readFileSync(htmlPath, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const js = scripts.join('\n');

// ============ DOM/bridge stub（复制自 proto_core_test.js，仅作装载占位） ============
const elStore = {};
function fakeEl() {
  return {
    value: '', textContent: '', innerHTML: '', className: '', style: {}, dataset: {},
    checked: true, disabled: false, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild() {}, removeChild() {}, setAttribute() {}, addEventListener() {},
    getContext() { return ctxStub(); },
    querySelector() { return { onclick: null, stopPropagation() {}, textContent: '', value: '', style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {} } }; },
    querySelectorAll() { return Array.from({ length: 4 }, () => ({ onclick: null, stopPropagation() {}, textContent: '', value: '', style: {}, dataset: {} })); },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
}
function ctxStub() {
  return new Proxy({}, {
    get(t, k) {
      if (k === 'canvas') return { width: 0, height: 0 };
      if (k === 'measureText') return () => ({ width: 0 });
      return typeof k === 'string' ? function () {} : undefined;
    },
    set() { return true; },
  });
}
const documentStub = {
  getElementById(id) { if (!elStore[id]) elStore[id] = fakeEl(); return elStore[id]; },
  createElement() { return fakeEl(); },
  addEventListener() {},
  querySelectorAll() { return []; },
  activeElement: { tagName: 'BODY' },
  body: { focus() {} },
};
const mockBridge = { list_devices: async () => ({}), open_usb: async () => ({}), open_wifi: async () => ({}),
  close_device: async () => ({}), send_frame: async () => ({}), get_pending: async () => ({ frames: [], logs: [], status: {} }),
  get_status: async () => ({}), get_registry: async () => ({}), save_registry: async () => ({}),
  import_registry: async () => ({}), log_line: async () => {} };
const noopTimer = () => 0;
const syncTimeout = (fn) => { if (typeof fn === 'function') fn(); return 0; };
const ctx = {
  console, Math, Date, JSON, Promise,
  setTimeout: syncTimeout, clearTimeout: noopTimer, setInterval: noopTimer, clearInterval: noopTimer,
  window: { addEventListener() {}, pywebview: { api: mockBridge } },
  document: documentStub,
  localStorage: { getItem: () => null, setItem() {} },
};
ctx.globalThis = ctx;
vm.createContext(ctx);

// ============ 用例收集（在 vm 内执行，BUILD_* 可见） ============
const collect = `
const __c = [];
function C(proto, op, hex, ...args) { __c.push({ proto, op, hex, args }); }
/* V3.9 */
C("V3","Q", hx(BUILD_V3.Q(0x9A)), 0x9A);
C("V3","Q", hx(BUILD_V3.Q(0x92)), 0x92);
C("V3","POS", hx(BUILD_V3.POS(0xA4, 360, 90)), 0xA4, 360, 90);
C("V3","POS", hx(BUILD_V3.POS(0xA4, 60, -30)), 0xA4, 60, -30);
C("V3","POS", hx(BUILD_V3.POS(0xA4, 0, 0)), 0xA4, 0, 0);
C("V3","POS", hx(BUILD_V3.POS(0xA4, 70000, 9999)), 0xA4, 70000, 9999);
C("V3","POS", hx(BUILD_V3.POS(0xA4, -5, 0.005)), 0xA4, -5, 0.005);
C("V3","POS1", hx(BUILD_V3.POS1(1, 100, 30)), 1, 100, 30);
C("V3","POS1", hx(BUILD_V3.POS1(-1, 0, 360.5)), -1, 0, 360.5);
C("V3","POS1", hx(BUILD_V3.POS1(1, 100, -0.5)), 1, 100, -0.5);
C("V3","SPEED", hx(BUILD_V3.SPEED(500)), 500);
C("V3","SPEED", hx(BUILD_V3.SPEED(-250.5)), -250.5);
C("V3","TORQUE", hx(BUILD_V3.TORQUE(1.5)), 1.5);
C("V3","TORQUE", hx(BUILD_V3.TORQUE(-400)), -400);
C("V3","PIDW", hx(BUILD_V3.PIDW(0x31, [1,2,3,4,5,6])), 0x31, [1,2,3,4,5,6]);
C("V3","PIDW", hx(BUILD_V3.PIDW(0x32, [-1, 999, 0, 1.4, 2, 3])), 0x32, [-1, 999, 0, 1.4, 2, 3]);
C("V3","ACC", hx(BUILD_V3.ACC(0x42, 1, 1234)), 0x42, 1, 1234);
C("V3","ZERO_OFF", hx(BUILD_V3.ZERO_OFF(-100)), -100);
C("V3","MODE", hx(BUILD_V3.MODE(3)), 3);
C("V3","SETID", hx(BUILD_V3.SETID(5)), 5);
C("V3","READID", hx(BUILD_V3.READID()));
C("V3","B3", hx(BUILD_V3.B3(1000)), 1000);
C("V3","B4", hx(BUILD_V3.B4(0)), 0);
C("V3","B6", hx(BUILD_V3.B6(1)), 1);
C("V3","B6", hx(BUILD_V3.B6(0)), 0);
C("V3","FUNC", hx(BUILD_V3.FUNC(1, -65535)), 1, -65535);
/* V4.4 */
C("V44","Q", hx(BUILD_V44.Q(0x92)), 0x92);
C("V44","POS", hx(BUILD_V44.POS(0xA4, 60, -30)), 0xA4, 60, -30);
C("V44","POS", hx(BUILD_V44.POS(0xA8, 1000, 45.67)), 0xA8, 1000, 45.67);
C("V44","FORCE_POS", hx(BUILD_V44.FORCE_POS(20, 300, 10)), 20, 300, 10);
C("V44","SPEED", hx(BUILD_V44.SPEED(50, 20)), 50, 20);
C("V44","SPEED", hx(BUILD_V44.SPEED(100, -123.45)), 100, -123.45);
C("V44","TORQUE", hx(BUILD_V44.TORQUE(-2.5)), -2.5);
C("V44","FF_SPD", hx(BUILD_V44.FF_SPD(100, 30)), 100, 30);
C("V44","FF_TQ", hx(BUILD_V44.FF_TQ(10, 100, -30)), 10, 100, -30);
C("V44","PID", hx(BUILD_V44.PID(0x31, 1, 1.5)), 0x31, 1, 1.5);
C("V44","PID", hx(BUILD_V44.PID(0x31, 1, -2.25)), 0x31, 1, -2.25);
C("V44","ACC", hx(BUILD_V44.ACC(0x42, 0, 5000)), 0x42, 0, 5000);
C("V44","ZERO_OFF", hx(BUILD_V44.ZERO_OFF(0)), 0);
C("V44","MODE", hx(BUILD_V44.MODE(2)), 2);
C("V44","FUNC", hx(BUILD_V44.FUNC(4, 1)), 4, 1);
C("V44","FUNC", hx(BUILD_V44.FUNC(6, 360)), 6, 360);
C("V44","B3", hx(BUILD_V44.B3(0)), 0);
C("V44","B4", hx(BUILD_V44.B4(1)), 1);
C("V44","B6", hx(BUILD_V44.B6(0)), 0);
globalThis.__GOLDEN = JSON.stringify(__c);
`;
vm.runInContext(js + collect, ctx);

const golden = JSON.parse(ctx.__GOLDEN);
golden.sort((a, b) => (a.proto + a.op + a.hex).localeCompare(b.proto + b.op + b.hex));
const doc = {
  generated_by: 'tools/gen_golden.js',
  source: htmlPath,
  count: golden.length,
  note: '黄金向量: JS 版组帧标准答案。pytest 逐字节断言 Python 版 build_frame(proto, op, *args) 输出 hx 与此一致。',
  cases: golden,
};
fs.writeFileSync(outPath, JSON.stringify(doc, null, 1), 'utf8');
console.log(`OK: ${golden.length} 条黄金向量已写入 ${outPath}`);
