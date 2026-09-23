# -*- coding: utf-8 -*-
"""
后坐力模拟器审计：冲击响应谱（SRS）对比
目的：判断"加速段向前反作用"与"刹停段向后撞击"分别激励机械臂的哪个频段，
      为"前冲到底重不重要"提供定量依据。
方法：对每条力-时间历程 F(t)，用一组单自由度振荡器（单位质量 1 kg、阻尼比 0.05 即 Q=10）：
        m*x'' + c*x' + k*x = F(t),  k=(2*pi*fn)^2, c=2*zeta*sqrt(k*m)
      记录两个峰值：
        ① max|k*x + c*x'|  峰值传递力（对应关节力矩量级，单位 N）
        ② max|x|           峰值相对位移（对应瞄准点偏移量级，换算 mm）
校验：无阻尼半正弦脉冲的经典结论：fn*tau≈0.5 处峰值放大约 1.77 倍。
（时间一律用秒积分，力函数按毫秒取时间）
"""
import math

MASS = 1.0
ZETA = 0.05

# ---------------- 三条力-时间历程（t 单位 ms，F 单位 N） ----------------
T1 = 11.08                       # 加速段时长 = 四分之一振动周期
def machine(t):
    if t < 0: return 0.0
    if t < T1:                   # 加速段：弹簧反作用顶机架，向前
        return -369.0 * math.cos(141.8 * t / 1000.0)
    w2 = 3.5
    if t < T1 + w2:              # 刹停段：缓冲器顶后墙，向后
        A2 = math.pi * 2.60 / (2 * w2 / 1000.0)
        return A2 * math.sin(math.pi * (t - T1) / w2)
    w3 = 9.9
    if t < T1 + w2 + w3:         # 回程：弹力弹簧推活块，机架受向后
        return 269.0 * (1.0 - (t - T1 - w2) / w3)
    T4 = 11.1
    if t < T1 + w2 + w3 + T4:    # 越过静止位：压击发弹簧，机架受向前
        A4 = 1331.0 / (2 * T4 / math.pi)
        return -A4 * math.sin(math.pi * (t - T1 - w2 - w3) / (2 * T4))
    return 0.0

ref_t = [0.0,0.5,1.0,1.5,2.0,2.5,3.0,3.5,4.0,4.5,5.0,5.5,6.0,6.5,7.0,7.5,8.0,8.5,9.0,9.5,10.0]
ref_f = [0,471,0,0,156,514,771,874,805,576,233,0,0,0,0,0,0,194,275,194,0]
def reference(t):
    if t <= ref_t[0]: return ref_f[0]
    if t >= ref_t[-1]: return ref_f[-1]
    for i in range(len(ref_t) - 1):
        if ref_t[i] <= t <= ref_t[i + 1]:
            r = (t - ref_t[i]) / (ref_t[i + 1] - ref_t[i])
            return ref_f[i] + r * (ref_f[i + 1] - ref_f[i])
    return 0.0
K58 = 1.75 / 2.60
def reference58(t): return K58 * reference(t)

def halfsine(t, A=1.0, tau=3.5):
    return A * math.sin(math.pi * t / tau) if 0.0 <= t <= tau else 0.0

# ---------------- SRS ----------------
def srs(force_ms_func, freqs, zeta=ZETA, tmax_s=0.08, h=1e-5):
    pk_tf, pk_x = [], []
    for fn in freqs:
        w = 2.0 * math.pi * fn
        k = w * w * MASS
        c = 2.0 * zeta * math.sqrt(k * MASS)
        def F(ts): return force_ms_func(ts * 1000.0)
        x = v = 0.0
        bt = bx = 0.0
        n = int(tmax_s / h)
        for i in range(n):
            ts = i * h
            def d(xx, vv, tt):
                return vv, (F(tt) - c * vv - k * xx) / MASS
            a1x, a1v = d(x, v, ts)
            a2x, a2v = d(x + 0.5*h*a1x, v + 0.5*h*a1v, ts + 0.5*h)
            a3x, a3v = d(x + 0.5*h*a2x, v + 0.5*h*a2v, ts + 0.5*h)
            a4x, a4v = d(x + h*a3x, v + h*a3v, ts + h)
            x += h * (a1x + 2*a2x + 2*a3x + a4x) / 6.0
            v += h * (a1v + 2*a2v + 2*a3v + a4v) / 6.0
            tf = abs(k * x + c * v)
            if tf > bt: bt = tf
            if abs(x) > bx: bx = abs(x)
        pk_tf.append(bt)
        pk_x.append(bx * 1000.0)          # m -> mm
    return pk_tf, pk_x

# 校验：无阻尼半正弦（幅值 1 N，宽 3.5 ms）
chk = []
for fn in [71.4, 100.0, 142.9, 200.0, 285.7]:
    f1, _ = srs(lambda t: halfsine(t), [fn], zeta=0.0, tmax_s=0.05)
    chk.append((fn, fn * 0.0035, f1[0]))
print("校验（无阻尼半正弦，幅值 1 N、宽 3.5 ms；fn*tau=0.5 处应约 1.77）:")
for fn, ft, pv in chk:
    print("   fn=%6.1f Hz  fn*tau=%.2f  峰值传递力=%.3f N" % (fn, ft, pv))

freqs = [5, 8, 12, 18, 25, 35, 50, 70, 100, 140, 200, 300, 450, 700, 1000]
mf, md = srs(machine, freqs)
rf, rd = srs(reference, freqs)
sf, sd = srs(reference58, freqs)

print("\n  fn(Hz) | 本机峰传力 | 参考2.6峰传力 | 本机峰位移 | 参考峰位移  (单位 N 与 mm)")
for i, fn in enumerate(freqs):
    print("  %6.1f | %9.1f | %11.1f | %9.4f | %9.4f" % (fn, mf[i], rf[i], md[i], rd[i]))

# ---------------- 画图（双对数） ----------------
W, H = 980, 790
L, R = 100, 940
P1 = (80, 350)      # 面板1 峰值传递力
P2 = (460, 730)     # 面板2 峰值相对位移
lo, hi = math.log10(5), math.log10(1000)
def LX(f): return L + (R - L) * (math.log10(f) - lo) / (hi - lo)
def LY(p, v, vmin, vmax):
    y0, y1 = p
    lv = math.log10(max(v, vmin * 1.0000001))
    return y1 - (y1 - y0) * (lv - math.log10(vmin)) / (math.log10(vmax) - math.log10(vmin))

FMIN, FMAX = 10.0, 3000.0      # 传递力谱范围 N
DMIN, DMAX = 0.002, 3000.0     # 位移谱范围 mm

svg = []
svg.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="Microsoft YaHei, SimHei, sans-serif">' % (W, H, W, H))
svg.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H))
svg.append('<text x="490" y="30" font-size="20" font-weight="bold" text-anchor="middle">冲击响应谱对比：本机输出 对 真枪参考曲线</text>')
svg.append('<text x="490" y="52" font-size="13" text-anchor="middle" fill="#555">单位质量（1 kg）单自由度振荡器、阻尼比 0.05（Q=10）的峰值响应；双对数轴</text>')

def panel(p, vmin, vmax, title, ylab, yticks):
    svg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#fff3cd" opacity="0.6"/>'
               % (LX(10), p[0], LX(100) - LX(10), p[1] - p[0]))
    svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="#8a6d3b">机械臂关节伺服带宽与臂结构模态典型区间（10 到 100 Hz）</text>'
               % (LX(11), p[0] - 8))
    svg.append('<text x="%d" y="%d" font-size="14" font-weight="bold">%s</text>' % (L, p[0] - 30, title))
    svg.append('<text x="%d" y="%d" font-size="12" fill="#666">%s</text>' % (L, p[0] - 12, ylab))
    for v in yticks:
        y = LY(p, v, vmin, vmax)
        svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#dddddd"/>' % (L, y, R, y))
        lab = ('%g' % v)
        svg.append('<text x="%d" y="%.1f" font-size="11" fill="#666" text-anchor="end">%s</text>' % (L - 6, y + 4, lab))
    for f in [5, 10, 25, 50, 100, 250, 500, 1000]:
        x = LX(f)
        svg.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#eeeeee"/>' % (x, p[0], x, p[1]))
        svg.append('<text x="%.1f" y="%d" font-size="11" fill="#666" text-anchor="middle">%d</text>' % (x, p[1] + 16, f))
    return

def curve(freqs, vals, p, vmin, vmax, color, dash, width):
    pts = " ".join("%.1f,%.1f" % (LX(f), LY(p, v, vmin, vmax)) for f, v in zip(freqs, vals))
    style = 'stroke-dasharray="%s"' % dash if dash else ''
    svg.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.1f" %s/>' % (pts, color, width, style))

panel(P1, FMIN, FMAX, "A. 峰值传递力谱（对应关节力矩量级）", "峰值传递力 (N)，输入力 1 N 归一化",
      [10, 30, 100, 300, 1000, 3000])
curve(freqs, mf, P1, FMIN, FMAX, "#d62728", None, 2.6)
curve(freqs, rf, P1, FMIN, FMAX, "#1f77b4", "6 4", 2.4)
curve(freqs, sf, P1, FMIN, FMAX, "#1f77b4", "2 3", 1.6)

panel(P2, DMIN, DMAX, "B. 峰值相对位移谱（对应瞄准点偏移量级）", "峰值相对位移 (mm)，输入力 1 N 归一化",
      [0.002, 0.01, 0.1, 1, 10, 100, 1000])
curve(freqs, md, P2, DMIN, DMAX, "#d62728", None, 2.6)
curve(freqs, rd, P2, DMIN, DMAX, "#1f77b4", "6 4", 2.4)
curve(freqs, sd, P2, DMIN, DMAX, "#1f77b4", "2 3", 1.6)

svg.append('<text x="%.1f" y="%.1f" font-size="13" fill="#d62728">本机（含加速段向前 2.6 N·s）</text>' % (LX(320), LY(P2, 900, DMIN, DMAX)))
svg.append('<text x="%.1f" y="%.1f" font-size="13" fill="#1f77b4">真枪参考 2.6 N·s（虚线）</text>' % (LX(320), LY(P2, 300, DMIN, DMAX)))
svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="#1f77b4">5.8mm 真枪 1.75 N·s（点线）</text>' % (LX(320), LY(P2, 100, DMIN, DMAX)))
svg.append('<text x="490" y="%d" font-size="13" fill="#333" text-anchor="middle">固有频率 fn (Hz，对数轴)：横轴位置 = 机械臂某阶模态/伺服带宽，纵轴 = 该频率下被激励出的幅值</text>' % (P2[1] + 44))
svg.append('</svg>')
open(r"C:\Users\NOZOMU\AppData\Local\Temp\claude\后坐力审计\SRS对比图.svg", "w", encoding="utf-8").write("\n".join(svg))
print("\nSRS SVG written")
