// 随机对拍向量生成器：JS 老翻译答 2000+ 道随机题 → 标准答案 JSON
// 运行（Windows 本机）:
//   node tools/gen_rand_vectors.js <index.html 绝对路径> <输出 json 路径>
// 用途: pytest test_rand.py 读产物，Python 版对同输入重算，values 必须逐值一致。
// 只比 values 不比 summary：随机值会撞 JS toFixed 与 Python 格式化的浮点舍入边界差异。
// 装载 stub 复制自 gen_golden.js（同源 proto_core_test.js）。
const fs = require('fs');
const vm = require('vm');

const htmlPath = process.argv[2];
const outPath = process.argv[3];
if (!htmlPath || !outPath) { console.error('用法: node gen_rand_vectors.js <index.html路径> <输出json路径>'); process.exit(1); }
const html = fs.readFileSync(htmlPath, 'utf8');
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

// ============ stub（同 gen_golden.js） ============
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
  createElement() { return fakeEl(); }, addEventListener() {}, querySelectorAll() { return []; },
  activeElement: { tagName: 'BODY' }, body: { focus() {} },
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

// ============ 随机题生成与作答（vm 内执行） ============
const collect = `
// ---- 电机配置（id1-5 = 界面注册表真实参数; id6 = V3 angle 语义变体） ----
motors.length = 0;
motors.push({id:1,name:"x8",proto:"V3",gear:6,dir:-1,E0:-92.97});
motors.push({id:2,name:"big",proto:"V43",gear:1,dir:1,v9cSemantics:"pulse"});
motors.push({id:3,name:"small",proto:"V43",gear:1,dir:1});
motors.push({id:4,name:"wrist",proto:"V44",gear:1,dir:1});
motors.push({id:5,name:"end",proto:"V44",gear:1,dir:-1});
motors.push({id:6,name:"v3ang",proto:"V3",gear:1,dir:1,v9cSemantics:"angle"});
try { selectedId = 1; } catch (e) {}

// ---- 参数采样: 特殊边界池 × 均匀随机（clamp/round/符号/溢出邻域） ----
const SPEC = [-999999,-65536,-32769,-32768.5,-32768,-32767,-1.5,-1,-0.5,-0.1,0,0.1,0.5,1,1.5,2.5,0.005,-0.005,
  123.456,359.99,359.999,360.5,32767.5,65535.9,65536,999999];
function rndArg() {
  return Math.random() < 0.6 ? SPEC[(Math.random() * SPEC.length) | 0] : (Math.random() * 2 - 1) * 1e5;
}
function rndByte() { return (Math.random() * 256) | 0; }
function rndIdx255() { return (Math.random() * 256) | 0; }

const __rf = [], __rp = [];
// ---- A. 组帧随机（每 builder 25 组） ----
function fCase(proto, op, args) { __rf.push({ proto, op, args, hex: hx(build_frame_of(proto, op, args)) }); }
function build_frame_of(proto, op, args) {
  const t = proto === "V3" ? BUILD_V3 : BUILD_V44;
  return t[op](...args);
}
const V3_OPS = ["Q","POS","POS1","SPEED","TORQUE","PIDW","ACC","ZERO_OFF","MODE","SETID","READID","B3","B4","B6","FUNC"];
const V44_OPS = ["Q","POS","FORCE_POS","SPEED","TORQUE","FF_SPD","FF_TQ","PID","ACC","ZERO_OFF","MODE","FUNC","B3","B4","B6"];
for (let i = 0; i < 25; i++) {
  fCase("V3", "Q", [rndIdx255()]);
  fCase("V3", "POS", [rndIdx255(), rndArg(), rndArg()]);
  fCase("V3", "POS1", [Math.random() < 0.5 ? 1 : -1, rndArg(), rndArg()]);
  fCase("V3", "SPEED", [rndArg()]);
  fCase("V3", "TORQUE", [rndArg()]);
  fCase("V3", "PIDW", [rndIdx255(), [rndByte(), rndByte(), rndByte(), rndByte(), rndByte(), rndByte()]]);
  fCase("V3", "ACC", [rndIdx255(), rndIdx255(), rndArg()]);
  fCase("V3", "ZERO_OFF", [rndArg()]);
  fCase("V3", "MODE", [rndIdx255()]);
  fCase("V3", "SETID", [rndIdx255()]);
  fCase("V3", "READID", []);
  fCase("V3", "B3", [Math.random() * 5e9]);
  fCase("V3", "B4", [rndIdx255()]);
  fCase("V3", "B6", [Math.random() < 0.5 ? 1 : 0]);
  fCase("V3", "FUNC", [rndIdx255(), rndArg()]);
  fCase("V44", "Q", [rndIdx255()]);
  fCase("V44", "POS", [rndIdx255(), rndArg(), rndArg()]);
  fCase("V44", "FORCE_POS", [rndIdx255(), rndArg(), rndArg()]);
  fCase("V44", "SPEED", [rndIdx255(), rndArg()]);
  fCase("V44", "TORQUE", [rndArg()]);
  fCase("V44", "FF_SPD", [rndArg(), rndArg()]);
  fCase("V44", "FF_TQ", [rndIdx255(), rndArg(), rndArg()]);
  fCase("V44", "PID", [rndIdx255(), rndIdx255(), rndArg()]);
  fCase("V44", "ACC", [rndIdx255(), rndIdx255(), rndArg()]);
  fCase("V44", "ZERO_OFF", [rndArg()]);
  fCase("V44", "MODE", [rndIdx255()]);
  fCase("V44", "FUNC", [rndIdx255(), rndArg()]);
  fCase("V44", "B3", [Math.random() * 5e9]);
  fCase("V44", "B4", [rndIdx255()]);
  fCase("V44", "B6", [Math.random() < 0.5 ? 1 : 0]);
}
// ---- B. 回复解析随机（cmd×payload 偏置随机; mid 对应电机与 cid） ----
const BYTE_POOL = [0x00, 0x01, 0x02, 0x7F, 0x80, 0x81, 0xFE, 0xFF, 0x10, 0x27];
function rndPayload() {
  const b = new Array(8);
  for (let k = 0; k < 8; k++) {
    b[k] = Math.random() < 0.5 ? ((Math.random() * 256) | 0)
      : BYTE_POOL[(Math.random() * BYTE_POOL.length) | 0];
  }
  return b;
}
const V3_CMDS = [0x9A,0x9C,0x9D,0x30,0x31,0x32,0x42,0x43,0x90,0x92,0x94,0x60,0x61,0x62,0x70,0x71,0x79,0xB1,0xB2,0xB3,0xB4,0xB5,0x20,0xA1,0xA2,0xA4,0xA6,0xA8,0x80,0x81,0x77,0x78,0xEE];
const V44_CMDS = [0x9A,0x9C,0x9D,0x92,0x94,0x30,0x31,0x32,0x42,0x43,0x63,0x64,0x60,0x61,0x62,0x70,0x79,0xB1,0xB2,0xB3,0xB4,0xB5,0xB6,0x20,0x80,0x81,0x77,0x78,0xA1,0xA2,0xA4,0xA8,0xA9,0x72,0x73,0xEE];
// (proto, 电机id, cmd集) → 每 cmd 25 帧（mid6 = V3 angle 语义）
const ROUTES = [ ["V3", 1, V3_CMDS], ["V3", 6, V3_CMDS], ["V44", 2, V44_CMDS], ["V43", 3, V44_CMDS], ["V44", 5, V44_CMDS] ];
for (const [proto, mid, cmds] of ROUTES) {
  const cid = 0x240 + mid;
  for (const cmd of cmds) {
    for (let i = 0; i < 25; i++) {
      const bytes = rndPayload(); bytes[0] = cmd;
      const out = parseReply(proto, cid, bytes);
      __rp.push({ proto, mid, bytes, out: out ? { cmd: out.cmd, values: out.values } : null });
    }
  }
}
globalThis.__RAND = JSON.stringify({ rand_frames: __rf, rand_parse: __rp });
`;
vm.runInContext(js + collect, ctx);

const rand = JSON.parse(ctx.__RAND);
const doc = {
  generated_by: 'tools/gen_rand_vectors.js',
  source: htmlPath,
  note: '随机对拍: 跨语言随机输入标准答案。pytest 断言 Python 版对同输入重算一致(组帧逐字节; 解析比 values)。',
  frame_count: rand.rand_frames.length,
  parse_count: rand.rand_parse.length,
  rand_frames: rand.rand_frames,
  rand_parse: rand.rand_parse,
};
fs.writeFileSync(outPath, JSON.stringify(doc, null, 1), 'utf8');
console.log(`OK: 组帧随机 ${rand.rand_frames.length} + 解析随机 ${rand.rand_parse.length} 题已写入 ${outPath}`);
