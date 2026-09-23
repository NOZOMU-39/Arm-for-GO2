# -*- coding: utf-8 -*-
"""
后坐扰动 → 机械臂响应 估计（用用户给的实物参数，量级估算）
臂：X6-40 大臂 0.32 m/1.2 kg → X6-40 小臂 0.30 m/1.0 kg → X2-P28-7 腕
    末端（腕电机+模拟器+视觉）2.5 kg，质心距腕轴 0.08 m
模型：三个俯仰关节解耦的二阶模型（脉冲只有几十毫秒、姿态变化极小，
      用解耦 + 常值力臂足够做量级估计；关节力矩超过上限时截断=饱和）
      干扰力矩 τi(t) = F(t) × di（di = 反坐力线到该关节轴的垂距，姿态相关）
输入：三条力-时间历程——① 本机现状（2.6 N·s，含加速段向前）
                          ② 真枪参考（2.6 N·s，9mm 档模板）
                          ③ 真枪参考（1.75 N·s，5.8mm 档）
输出：枪口指向角误差 Σθ(t) 与三关节力矩（含重力偏置与上限比较）
"""
import math

# ---------------- 臂参数（用户给的估计值） ----------------
L1, m1 = 0.32, 1.2          # 大臂
L2, m2 = 0.30, 1.0          # 小臂
m3, r3 = 2.5, 0.08          # 末端总重与质心距腕轴
g = 9.81

# 绕各关节的等效惯量
J3 = m3 * r3**2 + 0.010                     # 腕：末端 + 自身惯量估值
J2 = m2 * L2**2 / 3.0 + m3 * (L2 + r3)**2   # 肘：小臂 + 末端
J1 = m1 * L1**2 / 3.0 + m2 * (L1 + L2/2)**2 + m3 * (L1 + L2 + r3)**2

# 反坐力线到各关节轴的垂距（典型持枪姿态估计，结果与它成正比）
D = {"肩": 0.23, "肘": 0.10, "腕": 0.025}

# 重力静载力矩（姿态估计：小臂水平、大臂 45 度）
GRAV = {"肩": (m3*(L1+L2+r3)*math.sin(math.pi/4) + m2*(L1+L2/2)*math.sin(math.pi/4) + m1*(L1/2)*math.sin(math.pi/4))*g,
        "肘": (m3*(L2+r3) + m2*L2/2)*g,
        "腕": m3*r3*g}

# 关节：惯量、峰值力矩上限（按型号名后缀暂定，需核对手册）、闭环 15 Hz/0.8
JOINTS = [("肩", J1, 40.0), ("肘", J2, 40.0), ("腕", J3, 7.0)]
WN, ZETA = 2*math.pi*15.0, 0.8

# ---------------- 三条力-时间历程 ----------------
T1 = 11.08
def machine(t):
    if t < 0: return 0.0
    if t < T1: return -369.0*math.cos(141.8*t/1000.0)
    w2 = 3.5
    if t < T1+w2: return (math.pi*2.60/(2*w2/1000.0))*math.sin(math.pi*(t-T1)/w2)
    w3 = 9.9
    if t < T1+w2+w3: return 269.0*(1.0-(t-T1-w2)/w3)
    T4 = 11.1
    if t < T1+w2+w3+T4: return -(1331.0/(2*T4/math.pi))*math.sin(math.pi*(t-T1-w2-w3)/(2*T4))
    return 0.0

ref_t = [0.0,0.5,1.0,1.5,2.0,2.5,3.0,3.5,4.0,4.5,5.0,5.5,6.0,6.5,7.0,7.5,8.0,8.5,9.0,9.5,10.0]
ref_f = [0,471,0,0,156,514,771,874,805,576,233,0,0,0,0,0,0,194,275,194,0]
def _interp(x, y, v):
    if v <= x[0]: return y[0]
    if v >= x[-1]: return y[-1]
    for i in range(len(x)-1):
        if x[i] <= v <= x[i+1]:
            r = (v-x[i])/(x[i+1]-x[i]); return y[i]+r*(y[i+1]-y[i])
    return 0.0
def reference(t): return _interp(ref_t, ref_f, t)
def reference58(t): return 0.75/2.60*reference(t) if False else (1.75/2.60)*reference(t)

CASES = [("本机现状 2.6 N·s", machine), ("真枪参考 2.6 N·s", reference), ("真枪参考 1.75 N·s", reference58)]

# ---------------- 仿真 ----------------
H_STEP = 2e-5
def simulate(Ffunc, tmax=0.6, h=H_STEP):
    th = [0.0, 0.0, 0.0]; om = [0.0, 0.0, 0.0]
    rec = []
    n = int(tmax/h)
    for i in range(n):
        t = i*h
        F = Ffunc(t*1000.0)
        for j, (name, J, tlim) in enumerate(JOINTS):
            kp = J*WN*WN; kd = 2*ZETA*WN*J
            tau_d = F*D[name]
            tau_s = -kp*th[j] - kd*om[j]
            tau = tau_d + tau_s
            # 与重力偏置合计后按上限截断（饱和）
            total = tau + GRAV[name]
            if total > tlim: tau = tlim - GRAV[name]
            if total < -tlim: tau = -tlim - GRAV[name]
            alpha = tau/J
            om[j] += alpha*h
            th[j] += om[j]*h
        rec.append((t, th[0]+th[1]+th[2], th[0], th[1], th[2],
                    F*D["肩"], F*D["肘"], F*D["腕"]))
    return rec

print("=" * 78)
print("臂模型假设（可改）：")
print("  惯量 J：肩 %.3f  肘 %.3f  腕 %.4f kg·m²" % (J1, J2, J3))
print("  重力静载力矩：肩 %.1f  肘 %.1f  腕 %.2f N·m" % (GRAV["肩"], GRAV["肘"], GRAV["腕"]))
print("  峰值力矩上限（按型号后缀暂定）：肩/肘 40（X6-40）  腕 7（X2-P28-7）")
print("  反坐力线垂距：肩 %.2f  肘 %.2f  腕 %.3f m（结果与此成正比）" % (D["肩"], D["肘"], D["腕"]))
print("  伺服闭环 15 Hz、阻尼比 0.8；力矩超限截断（饱和）")
print("=" * 78)

summary = []
for name, f in CASES:
    rec = simulate(f)
    aim = [r[1] for r in rec]
    pk_aim = max(aim, key=abs)
    t_pk = [r[0] for r in rec][aim.index(pk_aim)]
    # 各关节峰值干扰力矩与峰值合力矩（含重力）
    tj = {"肩": max(abs(r[5]) for r in rec), "肘": max(abs(r[6]) for r in rec), "腕": max(abs(r[7]) for r in rec)}
    sat = {}
    for j, (nm, J, tlim) in enumerate(JOINTS):
        peak_total = max((abs(r[5+j]) + GRAV[nm]) for r in rec)
        sat[nm] = (peak_total, tlim)
    aim100 = [r[1] for r in rec if abs(r[0]-0.1) < H_STEP*1.5]
    aim300 = [r[1] for r in rec if abs(r[0]-0.3) < H_STEP*1.5]
    print("\n【%s】" % name)
    print("  枪口指向角误差峰值 %.2f mrad（%.2f 度，t=%.0f ms）" %
          (pk_aim*1000, math.degrees(pk_aim), t_pk*1000))
    print("  100 ms 时残余 %.2f mrad，300 ms 时残余 %.2f mrad" %
          (aim100[0]*1000 if aim100 else 0, aim300[0]*1000 if aim300 else 0))
    print("  干扰力矩峰值：肩 %.1f  肘 %.1f  腕 %.1f N·m" % (tj["肩"], tj["肘"], tj["腕"]))
    for nm in ["肩", "肘", "腕"]:
        pt, lim = sat[nm]
        print("    %s：含重力峰值 %.1f / 上限 %.0f N·m（占用 %.0f%%）%s" %
              (nm, pt, lim, 100*pt/lim, "  ← 饱和" if pt >= lim*0.999 else ""))
    summary.append((name, pk_aim, aim100[0] if aim100 else 0, aim300[0] if aim300 else 0))

# ---------------- 画图 ----------------
W, H = 980, 620
L, R = 100, 940
TMAX_PLOT = 0.15
def X(t): return L + (R-L)*t/TMAX_PLOT
def Y(panel, v, vmin, vmax):
    y0, y1 = panel
    v = max(min(v, vmax), vmin)
    return y1 - (y1-y0)*(v-vmin)/(vmax-vmin)

P1 = (70, 300); P2 = (380, 590)
svg = []
svg.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="Microsoft YaHei, SimHei, sans-serif">' % (W,H,W,H))
svg.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (W,H))
svg.append('<text x="490" y="30" font-size="19" font-weight="bold" text-anchor="middle">后坐扰动下机械臂响应估计（肩/肘/腕三关节解耦模型）</text>')
svg.append('<text x="490" y="52" font-size="12" text-anchor="middle" fill="#555">臂参数取用户实物估计值：大臂 0.32 m/1.2 kg、小臂 0.30 m/1.0 kg、末端 2.5 kg 质心距腕轴 0.08 m</text>')

def axes(p, vmin, vmax, title, ylab, ticks):
    svg.append('<text x="%d" y="%d" font-size="14" font-weight="bold">%s</text>' % (L, p[0]-18, title))
    svg.append('<text x="%d" y="%d" font-size="12" fill="#666">%s</text>' % (L, p[0]-2, ylab))
    for v in ticks:
        y = Y(p, v, vmin, vmax)
        svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#dddddd"/>' % (L, y, R, y))
        svg.append('<text x="%d" y="%.1f" font-size="11" fill="#666" text-anchor="end">%g</text>' % (L-6, y+4, v))
    for t in [0,0.025,0.05,0.075,0.1,0.125,0.15]:
        x = X(t)
        svg.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#eee"/>' % (x, p[0], x, p[1]))
        svg.append('<text x="%.1f" y="%d" font-size="11" fill="#666" text-anchor="middle">%g</text>' % (x, p[1]+16, t*1000))

def curve(rec, idx, p, vmin, vmax, color, dash, w, scale=1.0):
    pts = " ".join("%.1f,%.1f" % (X(r[0]), Y(p, r[idx]*scale, vmin, vmax)) for r in rec)
    st = 'stroke-dasharray="%s"' % dash if dash else ''
    svg.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.1f" %s/>' % (pts, color, w, st))

recs = [simulate(f) for _, f in CASES]
aimmax = max(abs(r[1]) for rec in recs for r in rec)*1000
AM = math.ceil(aimmax/2.0)*2.0
axes(P1, -AM, AM, "A. 枪口指向角误差（正 = 枪口上抬/后坐方向）", "mrad", [-AM, -AM/2, 0, AM/2, AM])
curve(recs[0], 1, P1, -AM, AM, "#d62728", None, 2.6, 1000.0)
curve(recs[1], 1, P1, -AM, AM, "#1f77b4", "6 4", 2.4, 1000.0)
curve(recs[2], 1, P1, -AM, AM, "#1f77b4", "2 3", 1.6, 1000.0)
svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#999" stroke-width="1.2"/>' % (L, Y(P1,0,-AM,AM), R, Y(P1,0,-AM,AM)))
svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="#d62728">本机现状 2.6 N·s</text>' % (X(0.085), Y(P1, AM*0.80, -AM, AM)))
svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="#1f77b4">真枪参考 2.6 N·s（虚线）/ 1.75 N·s（点线）</text>' % (X(0.085), Y(P1, -AM*0.75, -AM, AM)))

torquemax = max(max(abs(r[5+i]) for r in recs[1]) for i in range(3))
TM = math.ceil(torquemax*1.15/50.0)*50.0
axes(P2, -TM, TM, "B. 干扰力矩（不含重力，真枪参考 2.6 N·s 工况）", "N·m", [-TM, -TM/2, 0, TM/2, TM])
curve(recs[1], 5, P2, -TM, TM, "#d62728", None, 2.6)
curve(recs[1], 6, P2, -TM, TM, "#2ca02c", "6 4", 2.4)
curve(recs[1], 7, P2, -TM, TM, "#9467bd", "2 3", 1.8)
for nm, col, yv in [("肩 X6-40（上限 40）", "#d62728", 0.86), ("肘 X6-40（上限 40）", "#2ca02c", 0.68), ("腕 X2-P28-7（上限 7）", "#9467bd", 0.50)]:
    svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="%s">%s</text>' % (X(0.070), Y(P2, TM*yv, -TM, TM), col, nm))
svg.append('<text x="490" y="%d" font-size="12" fill="#333" text-anchor="middle">时间 (ms)</text>' % (P2[1]+40))
svg.append('</svg>')
open(r"C:\Users\NOZOMU\AppData\Local\Temp\claude\后坐力审计\臂响应估计.svg", "w", encoding="utf-8").write("\n".join(svg))
print("\nSVG written")
