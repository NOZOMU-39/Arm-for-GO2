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
/* ============ 回复解析对拍用例（真实回复帧样例） ============ */
/* 注册测试电机（parseReply 按回复 can_id 从 motors 找配置; cid=0x240+id） */
motors.length = 0;
motors.push({id:1,name:"x8",proto:"V3",gear:1,dir:1,v9cSemantics:"pulse"});
motors.push({id:2,name:"x6",proto:"V43",gear:1,dir:1});
motors.push({id:3,name:"x2",proto:"V44",gear:6,dir:-1});
motors.push({id:4,name:"v3g6",proto:"V3",gear:6,dir:-1});
motors.push({id:5,name:"v3ang",proto:"V3",gear:1,dir:1,v9cSemantics:"angle"});
try { selectedId = 3; } catch (e) {}   // 对齐界面选中态(0x20 idx6/7 摘要的 gearOf(selMotor))
const __p = [];
function P(proto, cid, bytes, note, valuesOnly) {
  const out = parseReply(proto, cid, bytes);
  if (!out) { __p.push({ proto, cid, bytes, motor: null, note, out: null }); return; }
  const motor = motorById(out.motorId) || null;
  __p.push({ proto, cid, bytes, motor: JSON.parse(JSON.stringify(motor)), out, valuesOnly: !!valuesOnly, note });
}
/* V3 帧（id1/4/5 回复地址 0x241/0x244/0x245） */
P("V3", 0x241, [0x9A,35,0,1,120,0,0,0], "9A 抱闸释放");
P("V3", 0x241, [0x9A,35,0,2,120,0,0,0], "9A 抱闸未定义");
P("V3", 0x241, [0x9A,35,0,0,0,0,0,0], "9A 电压零=旧固件");
P("V3", 0x241, [0x92,0x21,0x67,0,0,0,0,0], "92 D1-D4 264.01");
P("V3", 0x244, [0x92,0x98,0x3A,0,0,0,0,0], "92 gear6 dir-1 显示角");
P("V3", 0x241, [0x9C,30,0x64,0,0xF4,0x01,0x34,0x12], "9C 相位脉冲");
P("V3", 0x245, [0x9C,30,0x64,0,0xF4,0x01,0x34,0x12], "9C angle 语义", true);
P("V3", 0x241, [0x9D,10,0,20,0,30,0,0], "9D 相电流");
P("V3", 0x241, [0x30,0,1,2,3,4,5,6], "30 PID 六参数");
P("V3", 0x241, [0x42,1,0,0,0xD2,0x04,0,0], "42 加速度");
P("V3", 0x241, [0x90,0,0x34,0x12,0,0,0,0], "90 单圈编码器");
P("V3", 0x241, [0x94,0,0,0,0,0,0x10,0x27], "94 单圈角");
P("V3", 0x241, [0x61,0,0,0,0,0,1,0], "61 编码器 i32");
P("V3", 0x241, [0x70,0,0,0,0,0,0,3], "70 模式位置环");
P("V3", 0x241, [0x71,0,0,0,0,0,0x64,0], "71 功率");
P("V3", 0x241, [0x79,0,1,0,0,0,0x42,0x02], "79 读ID 回复0x242");
P("V3", 0x241, [0x79,0,0,0,0,0,0,5], "79 写回显");
P("V3", 0x241, [0xB1,0,0,0,0xC4,0x09,0,0], "B1 运行时间");
P("V3", 0x241, [0xB2,0,0,0,0,0,0x35,0x01], "B2 固件日期");
P("V3", 0x241, [0xB3,0,0,0,0xE8,0x03,0,0], "B3 中断保护");
P("V3", 0x241, [0xB4,0,0,0,0,0,0,1], "B4 波特率1M");
P("V3", 0x241, [0xB5,0x52,0x4D,0x44,0x2D,0x58,0x38,0], "B5 型号");
P("V3", 0x241, [0x20,1,0,0,0xFF,0xFF,0,0], "20 功能回显");
P("V3", 0x241, [0xA4,30,0x64,0,0xF4,0x01,0x34,0x12], "A4 控制回复");
P("V3", 0x241, [0x81,0,0,0,0,0,0,0], "81 停止回显 全零真机帧(2026-09-05)");
P("V3", 0x100, [0x9A,0,0,0,0,0,0,0], "cid 不识别→null");
/* V4.3/V4.4 帧（id2/3 回复 0x242/0x243） */
P("V44", 0x242, [0x9A,35,40,0,120,0,0,0], "V4 9A");
P("V44", 0x242, [0x92,0,0,0,0x82,0xDA,0xFF,0xFF], "V4 92 D4-D7 负值");
P("V43", 0x242, [0x94,0,0,0,0,0,0x10,0x27], "V43 94 两字节");
P("V43", 0x242, [0xB5,0x58,0x36,0x2D,0x50,0x33,0x36,0x2D], "V43 B5 型号文本 X6-P36");
P("V44", 0x242, [0x9D,0x19,0xFE,0xFF,0xFB,0xFF,0xFC,0xFF], "V44 9D 真机帧 D1=温度25 相电流归位");
P("V44", 0x243, [0x94,0,0,0,0x10,0x27,0,0], "V44 94 int32");
P("V44", 0x243, [0x9C,30,0x64,0,0xF4,0x01,0x34,0x12], "V44 9C");
P("V44", 0x243, [0x63,0,0,0,0,0x80,0,0], "V44 63 零偏回显");
P("V44", 0x243, [0x60,0,0,0,0,0,1,0], "V44 60 多圈位置");
P("V44", 0x242, [0x62,0,0,0,0x00,0x40,0,0], "V44 62 零偏");
P("V44", 0x242, [0x31,1,0,0,0,0,0xC0,0x3F], "V44 31 PID f32=1.5");
P("V44", 0x242, [0x42,0,0,0,0x88,0x13,0,0], "V44 42 加速度");
P("V44", 0x242, [0x70,0,0,0,0,0,0,2], "V44 70 位置环模式");
P("V44", 0x242, [0xB1,0,0,0,0xC4,0x09,0,0], "V44 B1");
P("V44", 0x242, [0xB4,0,0,0,0,0,0,0], "V44 B4 索引0=1M");
P("V44", 0x242, [0xB5,1,1,0x52,0x4D,0x44,0x2D,0x58], "V44 B5 真机段1 标记+索引+D3-7=RMD-");
P("V44", 0x242, [0xB5,1,2,0x32,0x2D,0x50,0x32,0x38], "V44 B5 真机段2 2-P28");
P("V44", 0x242, [0xB5,1,3,0x2D,0x37,0,0,0], "V44 B5 真机段3 -7(2026-09-05 三段拼 RMD-X2-P28-7)");
P("V44", 0x242, [0xB6,0,0,0,0,0,0,1], "V44 B6 开");
P("V44", 0x242, [0x79,0,1,0,0,0,0x43,0x02], "V44 79 读ID");
P("V44", 0x243, [0x20,6,0,0,0x30,0x75,0,0], "V44 20 正向最大角 5000");
P("V44", 0x243, [0x80,0,0,0,0,0,0,0], "V44 80 关闭回显 全零真机帧(ID4/5 失能实测 2026-09-05,失能后 A4 回锁角度零丢失)");
P("V44", 0x243, [0xA4,30,0x64,0,0xF4,0x01,0x34,0x12], "V44 A4 控制回复");
P("V44", 0x243, [0x72,30,0x64,0,0xF4,0x01,0x34,0x12], "V44 72 前馈");
globalThis.__GOLDEN = JSON.stringify({ cases: __c, parse_cases: __p });
`;
vm.runInContext(js + collect, ctx);

const golden = JSON.parse(ctx.__GOLDEN);
golden.cases.sort((a, b) => (a.proto + a.op + a.hex).localeCompare(b.proto + b.op + b.hex));
const doc = {
  generated_by: 'tools/gen_golden.js',
  source: htmlPath,
  frame_count: golden.cases.length,
  parse_count: golden.parse_cases.length,
  note: '黄金向量: JS 版标准答案。frame_cases 组帧逐字节比对 build_frame; parse_cases 回复解析比对 parse_reply(values/summary)。',
  cases: golden.cases,
  parse_cases: golden.parse_cases,
};
fs.writeFileSync(outPath, JSON.stringify(doc, null, 1), 'utf8');
console.log(`OK: 组帧 ${golden.cases.length} 条 + 解析 ${golden.parse_cases.length} 条黄金向量已写入 ${outPath}`);
