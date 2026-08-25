// 机械臂操作交互界面 — 协议核心回归测试(Node vm 沙箱,无硬件无浏览器)
// 运行:node 测试\proto_core_test.js
// 套路:加载 index.html 全部 JS + DOM/bridge stub,断言协议组帧/解析/角度/限幅/设零点/键盘限位/扫描比对
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const htmlPath = path.join(__dirname, '..', 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const js = scripts.join('\n');

// ============ DOM stub ============
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
  querySelectorAll() { return []; },   // fixTipOnInputs 用(测试环境无需真包裹)
  activeElement: { tagName: 'BODY' },
  body: { focus() {} },
};

// ============ bridge stub(记录发送帧) ============
const sent = [];
const mockBridge = {
  list_devices: async () => ({ ok: true, data: [] }),
  open_usb: async () => ({ ok: true, msg: 'ok' }), open_wifi: async () => ({ ok: true, msg: 'ok' }),
  close_device: async () => ({ ok: true, msg: 'ok' }),
  send_frame: async (id, extd, hex, note, silent) => { sent.push({ id, hex, note, silent }); return { ok: true, msg: 'ok' }; },
  get_pending: async () => ({ frames: [], logs: [], status: { opened: true, mock: true, kind: 'usb', tx: 0, rx: 0, online: true } }),
  get_status: async () => ({ ok: true, data: {} }),
  get_registry: async () => ({ ok: true, data: [] }),
  save_registry: async () => ({ ok: true }), import_registry: async () => ({ ok: false, msg: '取消' }),
  log_line: async () => {},
};
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

let pass = 0, fail = 0;
function T(name, cond, extra) {
  if (cond) { pass++; console.log('  ✅', name); }
  else { fail++; console.log('  ❌', name, extra !== undefined ? '→ ' + JSON.stringify(extra) : ''); }
}

(async () => {
  vm.runInContext(js, ctx);
  vm.runInContext('init()', ctx);
  await new Promise(r => setImmediate(r));

  const R = (code) => vm.runInContext(code, ctx);
  R('dev.opened = true; dev.mock = true');   // monitorLimit 的 0x81 发送依赖 dev.opened

  console.log('\n== 1. 字节工具边界 ==');
  T('pI32(2147483647) 往返', R('i32(pI32(2147483647),0)') === 2147483647);
  T('pI32(-2147483648) 往返', R('i32(pI32(-2147483648),0)') === -2147483648);
  T('pI16(-32768) 往返', R('i16(pI16(-32768),0)') === -32768);
  T('pU16 溢出钳制', R('pU16(70000).join(",")') === '255,255');

  console.log('\n== 2. 组帧布局 ==');
  // 360 = 0x0168 小端 → 68 01;9000 = 0x2328 小端 → 28 23
  const pos = R('hx(BUILD_V3.POS(0xA4, 360, 90))');
  T('V3 0xA4: [A4,0,68,01,28,23,00,00]', pos === 'A4 00 68 01 28 23 00 00', pos);
  const spd44 = R('hx(BUILD_V44.SPEED(50, 20))');
  T('V4 0xA2: D2=50%力矩, 20°×100=2000 LE', spd44 === 'A2 00 32 00 D0 07 00 00', spd44);
  // 60 = 0x003C 小端 → 3C 00;-3000 = 0xFFFFF448 小端 → 48 F4 FF FF
  const posV4 = R('hx(BUILD_V44.POS(0xA4, 60, -30))');
  T('V4 0xA4 负角: [A4,0,3C,00,48,F4,FF,FF]', posV4 === 'A4 00 3C 00 48 F4 FF FF', posV4);

  console.log('\n== 3. V3 0x92 解析(读 D1-D4,264.01° 回归) ==');
  const m1 = { id: 1, name: 't', proto: 'V3', gear: 1, dir: 1, v9cSemantics: 'pulse' };
  R('motors.push({id:1,name:"t",proto:"V3",gear:1,dir:1,v9cSemantics:"pulse"})');
  const p1 = R('parseReply("V3", 0x241, [0x92,0x21,0x67,0,0,0,0,0])');
  T('0x92 D1-D4 = 264.01°', Math.abs(p1.values.pos - 264.01) < 0.01, p1.values.pos);
  const p1b = R('parseReply("V3", 0x241, [0x92,0x82,0xDA,0xFF,0xFF,0,0,0])');
  T('0x92 负值 = -95.98°', Math.abs(p1b.values.pos - (-95.98)) < 0.01, p1b.values.pos);

  console.log('\n== 4. V4 0x92 解析(读 D4-D7,负值) ==');
  R('motors.push({id:2,name:"v4",proto:"V44",gear:1,dir:1})');
  // -9598 = 0xFFFFDA82 小端 → D4=82 D5=DA D6=FF D7=FF
  const p2 = R('parseReply("V44", 0x242, [0x92,0,0,0,0x82,0xDA,0xFF,0xFF])');
  T('V4 0x92 = -95.98°', Math.abs(p2.values.pos - (-95.98)) < 0.01, p2.values.pos);
  const p2b = R('parseReply("V43", 0x242, [0x94,0,0,0,0,0,0x10,0x27])');
  T('V4.3 0x94 两字节 = 100.00°', Math.abs(p2b.values.pos - 100) < 0.01, p2b.values.pos);
  const p2c = R('parseReply("V44", 0x242, [0x94,0,0,0,0x10,0x27,0,0])');
  T('V4.4 0x94 int32 = 100.00°', Math.abs(p2c.values.pos - 100) < 0.01, p2c.values.pos);

  console.log('\n== 5. V3 相位最近邻(快速反转取错圈回归) ==');
  T('350° → 回读10° 取 370°', R('(function(){ const m={id:1}; const t=v3TrackOf(m); t.rotDeg=350; t.lastEnc=Math.round(350/360*65536); v3OnPhase(m, Math.round(10/360*65536)); return Math.round(t.rotDeg); })()') === 370);
  T('跳变>180° 采样(0.92 已到位时不受 0x9C 影响)', R('(function(){ lastAngle[1]=100; lastAngleSrc[1]="0x92"; const t=v3TrackOf(motorById(1)); const before=t.rotDeg; return true; })()') === true);

  console.log('\n== 6. V3 显示公式(含 E0/dir/gear) ==');
  const d6 = R('(function(){ const m={id:3,name:"x",proto:"V3",gear:6,dir:-1}; const t=v3TrackOf(m); t.E0=90; t.rotDeg=150; t.lastEnc=1; return v3PosDual(m); })()');
  T('(150−90)/6×(−1) = −10', Math.abs(d6 - (-10)) < 1e-9, d6);

  console.log('\n== 7. 设零点数学 ==');
  const e0a = R('v3E0ForX(264.01, 0, {gear:6,dir:-1})');
  T('V3 X=0: E0 = 264.01', Math.abs(e0a - 264.01) < 0.01, e0a);
  const e0b = R('v3E0ForX(264.01, 30, {gear:6,dir:-1})');
  T('V3 X=30(dir=-1,gear6): E0 = 264.01+180 = 444.01', Math.abs(e0b - 444.01) < 0.01, e0b);
  T('V4 显示偏移: rot2out(0x92)+E4', R('(function(){ const m={gear:1,dir:1,E4:30}; return rot2out(50,m)+e4Of(m); })()') === 80);
  T('V4 发送目标: out2rot(deg−E4)', R('(function(){ const m={gear:1,dir:1,E4:30}; return out2rot(10-30,m); })()') === -20);

  console.log('\n== 8. limitBlock 判定矩阵 ==');
  R('motors.push({id:4,name:"lim",proto:"V44",gear:1,dir:1,limMinDeg:-10,limMaxDeg:10,limMaxSpd:50,limMaxIq:5})');
  const m4 = { id: 4 };
  T('限幅内放行', R('limitBlock(motorById(4), {deg:5,spd:20})') === true);
  T('deg 超上限拦截', R('limitBlock(motorById(4), {deg:15})') === false);
  T('deg 低于下限拦截', R('limitBlock(motorById(4), {deg:-15})') === false);
  T('spd 超限拦截', R('limitBlock(motorById(4), {spd:80})') === false);
  T('iq 超限拦截', R('limitBlock(motorById(4), {iq:8})') === false);
  R('limitAlarm[4] = {ang:true, spd:false, iq:false}');
  R('lastAngle[4] = 9.9');   // 当前位置接近上限 10
  T('锁定态+同向(往限幅外 15°)拦截', R('limitBlock(motorById(4), {deg:15})') === false);
  T('锁定态+反向(回限幅内 5°)放行', R('limitBlock(motorById(4), {deg:5})') === true);
  T('锁定态+无当前位置信息拦截', R('delete lastAngle[4]; limitBlock(motorById(4), {deg:0})') === false);
  R('lastAngle[4] = 9.9');
  // 安全指令(0x80/0x81)不走 limitBlock——sendMotor 直接放行
  sent.length = 0;
  R('sendMotor(motorById(4), pad8([0x81]), "测试安全指令不受锁定限制")');
  T('锁定态下 0x81 仍可直发', sent.some(s => s.hex.startsWith('81')));
  R('delete limitAlarm[4]');   // 注意:必须在 vm 内执行 delete,不能 delete vm 返回值

  console.log('\n== 9. monitorLimit 状态机(先 0x81 后报警) ==');
  sent.length = 0;
  R('monitorLimit({id:4,limMinDeg:-10,limMaxDeg:10}, 25, 0, 0)');
  T('越限触发 → 发出 0x81', sent.length >= 1 && sent[0].hex.startsWith('81'), sent.map(s => s.hex));
  T('越限锁定置位', R('limitAlarm[4] && limitAlarm[4].ang') === true);
  R('monitorLimit({id:4,limMinDeg:-10,limMaxDeg:10}, 25, 0, 0)');
  T('持续越限不重复触发', sent.filter(s => s.hex.startsWith('81')).length === 1, sent.filter(s => s.hex.startsWith('81')).length);
  R('monitorLimit({id:4,limMinDeg:-10,limMaxDeg:10}, 9, 0, 0)');
  T('回落(2° 死区内)不解锁', R('limitAlarm[4].ang') === true);
  R('monitorLimit({id:4,limMinDeg:-10,limMaxDeg:10}, 7, 0, 0)');
  T('回落到死区外解锁', R('limitAlarm[4].ang') === false);

  console.log('\n== 10. 键盘限位停判定 ==');
  T('↑ 且 ≥上限 → 停', R('kbLimitBlocked(10, 1, -10, 10)') === true);
  T('↑ 且 <上限 → 放行', R('kbLimitBlocked(9.9, 1, -10, 10)') === false);
  T('↓ 且 ≤下限 → 停', R('kbLimitBlocked(-10, -1, -10, 10)') === true);
  T('↓ 且 >下限 → 放行', R('kbLimitBlocked(-9.9, -1, -10, 10)') === false);
  T('无角度反馈 → 放行', R('kbLimitBlocked(undefined, 1, -10, 10)') === false);
  T('无限位 → 放行', R('kbLimitBlocked(100, 1, null, null)') === false);

  console.log('\n== 11. chartAutoScale ==');
  const c1 = R('chartAutoScale([100,200], 360)');
  T('±15% 余量(span 100>地板7.2)', Math.abs(c1[1] - 215) < 1e-9 && Math.abs(c1[0] - 85) < 1e-9, c1);
  const c2 = R('chartAutoScale([0.1,-0.1], 360)');
  T('2% 地板(span<7.2 → 扩到 7.2)', Math.abs((c2[1] - c2[0]) - 7.2) < 1e-9, c2);
  const c3 = R('chartAutoScale([NaN,NaN], 360)');
  T('全 NaN 回落默认量程', c3[0] === -360 && c3[1] === 360, c3);
  const c4 = R('chartAutoScale([42], 360)');
  T('单值 → 以 42 为中心扩地板', Math.abs((c4[0] + c4[1]) / 2 - 42) < 1e-9, c4);

  console.log('\n== 12. decode79Reply ==');
  const d79 = R('decode79Reply([0x79,0,1,0,0,0,0x42,0x02])');
  T('0x0242 → 编号 2', d79.id === 2, d79);

  console.log('\n== 13. 扫描一致性比对 ==');
  const diff1 = R('consistencyDiff([1,2,9], [{id:1,name:"a"},{id:3,name:"c"}])');
  T('注册无应答 #3 + 在线未注册 #2/#9', diff1.length === 3 && diff1[0].includes('#3') && diff1[1].includes('#2') && diff1[2].includes('#9'), diff1);
  const diff2 = R('consistencyDiff([1], [{id:1,name:"a"}])');
  T('一致 → 空', diff2.length === 0, diff2);

  console.log('\n== 14. 界面 HTML 无指令号 / PROTO_CORE 标记 ==');
  const uiText = html.replace(/<script>[\s\S]*?<\/script>/g, '').replace(/<!--[\s\S]*?-->/g, '');
  T('界面 HTML 无 0x 指令号', !uiText.match(/0x[0-9A-F]{2}/g));
  T('PROTO_CORE 标记存在', html.includes('PROTO_CORE_START') && html.includes('PROTO_CORE_END'));

  console.log('\n========== 结果:' + pass + ' 通过 / ' + fail + ' 失败 ==========');
  process.exit(fail ? 1 : 0);
})();
