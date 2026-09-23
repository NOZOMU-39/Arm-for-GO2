# -*- coding: utf-8 -*-
"""
后坐力模拟器审计：本机实际输出 F(t) 与 参考力曲线 对照
模型（全部取说明书自己的定案数字）：
  L1 弹射段 0 到 11.1 ms：击发弹簧反作用在机架上 = 向前力
     F = -369*cos(w t),  w = sqrt(k/m) = sqrt(16770/0.834) = 141.8 rad/s
     冲量 = -369/w = -2.60 N·s（向前，与后坐反向）
  L2 刹停段 11.1 到 14.6 ms：缓冲器加弹力弹簧顶后墙 = 向后力（= 说明书说的 2.6 N·s 冲量）
     半正弦，峰值 A = pi*I/(2w)，I = +2.60 N·s，w = 3.5 ms -> A = 1167 N
  L3 回程段 14.6 到 24.5 ms：弹力弹簧推活块向前、反作用顶机架向后
     F = 269*(1-x/w)，峰值 269 N（停点处弹力弹簧力 44.9*6 = 269 N），冲量 +1.33 N·s（= 活块回弹动量）
  L4 越过静止位 24.5 到 35.6 ms：活块前冲压击发弹簧、反作用拉机架向前
     上升四分之一正弦，冲量 -1.33 N·s
参考曲线 = 说明书 参考力曲线_2.6Ns缩放 的表（峰 A/B/C）
"""
import math

k, m = 16770.0, 0.834          # N/m, kg
w0 = math.sqrt(k / m)          # 141.8 rad/s
T1 = math.pi / 2 / w0 * 1000   # ms, 弹射段时长 = 四分之一周期
F0 = k * 0.02199               # 369 N

def machine(t_ms):
    """返回 (F_N, 已累计冲量 N·s)"""
    F = 0.0
    if t_ms < 0:
        return 0.0
    # L1
    if t_ms < T1:
        return -F0 * math.cos(w0 * t_ms / 1000.0)
    # L2
    w2 = 3.5
    if t_ms < T1 + w2:
        A2 = math.pi * 2.60 / (2 * w2 / 1000.0)            # 1167 N
        return A2 * math.sin(math.pi * (t_ms - T1) / w2)
    # L3
    w3 = 9.9
    if t_ms < T1 + w2 + w3:
        return 269.0 * (1.0 - (t_ms - T1 - w2) / w3)
    # L4
    T4 = 11.1
    if t_ms < T1 + w2 + w3 + T4:
        A4 = 1331.0 / (2 * T4 / math.pi)                   # 188 N, 使冲量正好 1.33
        return -A4 * math.sin(math.pi * (t_ms - T1 - w2 - w3) / (2 * T4))
    return 0.0

# 参考曲线（说明书 参考力曲线_2.6Ns缩放_20260908.md §4 数据表）
ref_t = [0.0,0.5,1.0,1.5,2.0,2.5,3.0,3.5,4.0,4.5,5.0,5.5,6.0,6.5,7.0,7.5,8.0,8.5,9.0,9.5,10.0]
ref_f = [0,471,0,0,156,514,771,874,805,576,233,0,0,0,0,0,0,194,275,194,0]

def interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            r = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + r * (ys[i + 1] - ys[i])
    return 0.0

# 采样
dt = 0.05
tmax = 40.0
T, MF, MI, RF, RI = [], [], [], [], []
acc = 0.0
racc = 0.0
t = 0.0
while t <= tmax + 1e-9:
    f = machine(t)
    acc += f * dt / 1000.0
    r = interp(ref_t, ref_f, t)
    racc += r * dt / 1000.0
    T.append(t); MF.append(f); MI.append(acc)
    RF.append(r); RI.append(racc)
    t = round(t + dt, 4)

print("L1 弹射段时长 = %.2f ms  峰值 %.0f N  冲量 %.2f N·s" % (T1, -F0, -F0 / w0))
print("本机累计冲量末值 = %.3f N·s" % MI[-1])
print("本机正冲量峰值 = %.3f N·s" % max(MI))
print("参考曲线累计冲量末值 = %.3f N·s" % RI[-1])

# ---------- 画 SVG ----------
W, H = 980, 700
X0, X1 = 90, 930
def X(t): return X0 + (X1 - X0) * t / tmax
def Y(panel, v, lo, hi):
    y0, y1 = panel
    return y1 - (y1 - y0) * (v - lo) / (hi - lo)

PA = (70, 300)      # 面板A：力
PB = (390, 620)     # 面板B：累计冲量
A_lo, A_hi = -600.0, 1300.0
B_lo, B_hi = -3.2, 3.2

def path(ts, vs, panel, lo, hi):
    pts = []
    for tt, vv in zip(ts, vs):
        pts.append("%.1f,%.1f" % (X(tt), Y(panel, vv, lo, hi)))
    return "M" + " L".join(pts)

s = []
s.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="Microsoft YaHei, SimHei, sans-serif">' % (W, H, W, H))
s.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H))
s.append('<text x="490" y="32" font-size="21" font-weight="bold" text-anchor="middle">后坐力模拟器审计：模拟器实际输出 对 真枪参考曲线</text>')
s.append('<text x="490" y="54" font-size="14" text-anchor="middle" fill="#555">模型参数全部取自《设计计算说明书 v1》定案数字　纵轴正 = 后坐方向（向后，即枪托顶肩方向）</text>')

# ---- 面板 A 网格 ----
s.append('<text x="%d" y="%d" font-size="15" font-weight="bold">A. 传给机架的力 F(t)</text>' % (X0, PA[0] - 18))
for v in [-500, 0, 500, 1000]:
    y = Y(PA, v, A_lo, A_hi)
    s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="%s"/>' % (X0, y, X1, y, "#eeeeee" if v else "#999999", 1 if v else 1.4))
    s.append('<text x="%d" y="%.1f" font-size="12" fill="#666" text-anchor="end">%d</text>' % (X0 - 6, y + 4, v))
# 参考曲线
s.append('<path d="%s" fill="none" stroke="#1f77b4" stroke-width="2.4" stroke-dasharray="6 4"/>' % path(T, RF, PA, A_lo, A_hi))
# 5.8mm 缩放的参考曲线
s.append('<path d="%s" fill="none" stroke="#1f77b4" stroke-width="1.6" stroke-dasharray="2 3"/>' % path(T, [v * 0.673 for v in RF], PA, A_lo, A_hi))
# 本机
s.append('<path d="%s" fill="none" stroke="#d62728" stroke-width="2.6"/>' % path(T, MF, PA, A_lo, A_hi))
s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#d62728" stroke-width="0.8" stroke-dasharray="3 3"/>' % (X(T1), PA[0], X(T1), PA[1]))

lab = [
    (3.5, -700, "L1 弹射段：弹簧反作用", "#d62728", 13),
    (16.0, 1180, "L2 刹停段：缓冲器顶后墙（说明书说的 2.6 N·s）", "#d62728", 13),
    (26.2, 620, "L3 回程：弹簧反作用", "#d62728", 12),
    (29.0, -520, "L4 越过静止位", "#d62728", 12),
    (7.2, 300, "真枪参考曲线 2.6 N·s", "#1f77b4", 13),
    (7.2, 700, "峰B 875 N", "#1f77b4", 12),
]
for tx, ty, txt, col, fs in lab:
    s.append('<text x="%.1f" y="%.1f" font-size="%d" fill="%s">%s</text>' % (X(tx), Y(PA, ty, A_lo, A_hi), fs, col, txt))

# ---- 面板 B ----
s.append('<text x="%d" y="%d" font-size="15" font-weight="bold">B. 累计冲量（已传给机械臂的动量，N·s）</text>' % (X0, PB[0] - 18))
for v in [-2.6, 0, 2.6]:
    y = Y(PB, v, B_lo, B_hi)
    s.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="%s"/>' % (X0, y, X1, y, "#dddddd" if v else "#999999", 1 if v else 1.4))
    s.append('<text x="%d" y="%.1f" font-size="12" fill="#666" text-anchor="end">%.1f</text>' % (X0 - 6, y + 4, v))
s.append('<path d="%s" fill="none" stroke="#1f77b4" stroke-width="2.4" stroke-dasharray="6 4"/>' % path(T, RI, PB, B_lo, B_hi))
s.append('<path d="%s" fill="none" stroke="#1f77b4" stroke-width="1.6" stroke-dasharray="2 3"/>' % path(T, [v * 0.673 for v in RI], PB, B_lo, B_hi))
s.append('<path d="%s" fill="none" stroke="#d62728" stroke-width="2.6"/>' % path(T, MI, PB, B_lo, B_hi))
blab = [
    (5.0, -2.35, "本机：先向后（-2.6）", "#d62728", 13),
    (12.0, 0.85, "再回到 0", "#d62728", 13),
    (28.6, 1.95, "回程短暂 +1.33", "#d62728", 12),
    (34.0, -0.95, "最终归 0", "#d62728", 13),
    (5.0, 2.85, "真枪（2.6 N·s 模板）：稳定在 +2.6", "#1f77b4", 13),
    (16.0, 1.35, "5.8mm 真枪约 +1.75", "#1f77b4", 12),
]
for tx, ty, txt, col, fs in blab:
    s.append('<text x="%.1f" y="%.1f" font-size="%d" fill="%s">%s</text>' % (X(tx), Y(PB, ty, B_lo, B_hi), fs, col, txt))

# 时间轴
for tt in range(0, 41, 5):
    s.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#999"/>' % (X(tt), PB[1], X(tt), PB[1] + 5))
    s.append('<text x="%.1f" y="%.1f" font-size="12" fill="#666" text-anchor="middle">%d</text>' % (X(tt), PB[1] + 20, tt))
s.append('<text x="%.1f" y="%.1f" font-size="13" fill="#333" text-anchor="middle">释放 / 击发点火 起算时间 (ms)</text>' % ((X0 + X1) / 2, PB[1] + 42))

s.append('</svg>')
open(r"C:\Users\NOZOMU\AppData\Local\Temp\claude\后坐力审计\审计对比图.svg", "w", encoding="utf-8").write("\n".join(s))
print("SVG written")
