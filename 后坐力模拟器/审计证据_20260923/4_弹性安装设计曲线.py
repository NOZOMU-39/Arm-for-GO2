# -*- coding: utf-8 -*-
"""
弹性安装（软接口）设计曲线
公式：传到臂的峰值力 ≈ min(2π·fm·I, F_peak)     （fm 远低于 1/脉宽 时成立）
      器件相对行程 ≈ I/(m_d·2π·fm)
关节力矩 τi = F × di；给定对齐姿态 di = 0.03/0.02/0.025 m
"""
import math
I = 2.6          # N·s，单发冲量（真枪 2.6 / 本机 2.6）
m_d = 1.6        # kg，弹性安装上运动的质量（模拟器 1.5 + 视觉 0.1 估）
F_src = 875.0    # 真枪刚性安装峰值
D = {"肩": 0.03, "肘": 0.02, "腕": 0.025}
LIM = {"肩": 40.0, "肘": 40.0, "腕": 7.0}

W, H = 980, 660
L, R = 110, 930
P1, P2 = (70, 330), (400, 630)
import math as _m
def LX(f): return L + (R-L)*(_m.log10(f)-_m.log10(3))/ (_m.log10(60)-_m.log10(3))
def LY(p, v, vmax):
    return p[1] - (p[1]-p[0])*min(v, vmax)/vmax

svg = []
svg.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="Microsoft YaHei, SimHei, sans-serif">' % (W,H,W,H))
svg.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (W,H))
svg.append('<text x="490" y="30" font-size="19" font-weight="bold" text-anchor="middle">弹性安装设计曲线：安装刚度怎么选，关节才不超限</text>')
svg.append('<text x="490" y="52" font-size="12" text-anchor="middle" fill="#555">冲量 2.6 N·s、运动质量 1.6 kg、姿态已对齐（反坐力线垂距 肩0.03/肘0.02/腕0.025 m）</text>')

def axis(p, vmax, ticks, title, ylab):
    svg.append('<text x="%d" y="%d" font-size="14" font-weight="bold">%s</text>' % (L, p[0]-18, title))
    svg.append('<text x="%d" y="%d" font-size="12" fill="#666">%s</text>' % (L, p[0]-2, ylab))
    for v in ticks:
        y = LY(p, v, vmax)
        svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ddd"/>' % (L, y, R, y))
        svg.append('<text x="%d" y="%.1f" font-size="11" fill="#666" text-anchor="end">%g</text>' % (L-6, y+4, v))
    for f in [3,5,8,10,15,20,30,45,60]:
        x = LX(f)
        svg.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#eee"/>' % (x, p[0], x, p[1]))
        svg.append('<text x="%.1f" y="%d" font-size="11" fill="#666" text-anchor="middle">%d</text>' % (x, p[1]+16, f))

def curve(f_pts, vals, p, vmax, color, dash, w, label=None, lx=None, ly=None):
    pts = " ".join("%.1f,%.1f" % (LX(f), LY(p, v, vmax)) for f, v in zip(f_pts, vals))
    st = 'stroke-dasharray="%s"' % dash if dash else ''
    svg.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.1f" %s/>' % (pts, color, w, st))
    if label:
        svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="%s">%s</text>' % (LX(lx), LY(p, ly, vmax), color, label))

fs = [3 + i*0.25 for i in range(229)]
Ftrans = [min(2*_m.pi*f*I, F_src) for f in fs]
travel = [I/(m_d*2*_m.pi*max(f,1e-6))*1000 for f in fs]

axis(P1, 900, [0,200,400,600,800], "A. 传到臂的峰值力（N）与各关节上限换算线", "峰值力 (N)")
curve(fs, Ftrans, P1, 900, "#d62728", None, 2.6, "实际传到臂的峰值力", 22, 300)
# 各关节"上限换算成力"的水平线：F = LIM/d
for nm, col in [("肩", "#1f77b4"), ("肘", "#2ca02c"), ("腕", "#9467bd")]:
    f_lim = LIM[nm]/D[nm]
    svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1.6" stroke-dasharray="5 4"/>' % (L, LY(P1, f_lim, 900), R, LY(P1, f_lim, 900), col))
    svg.append('<text x="%d" y="%.1f" font-size="12" fill="%s">%s上限（%.0f N）</text>' % (R-150, LY(P1, f_lim, 900)-5, col, nm, f_lim))
svg.append('<text x="%d" y="%.1f" font-size="12" fill="#8a6d3b">腕是最紧的一环：安装频率要低于约 17 Hz 才进限</text>' % (L+8, LY(P1, 330, 900)))

axis(P2, 90, [0,20,40,60,80], "B. 器件相对臂的相对行程（mm，单边）", "行程 (mm)")
curve(fs, travel, P2, 90, "#2ca02c", None, 2.6, "相对行程（单边）", 12, 60)
svg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#999" stroke-width="1.2" stroke-dasharray="4 3"/>' % (L, LY(P2, 25, 90), R, LY(P2, 25, 90)))
svg.append('<text x="%d" y="%.1f" font-size="12" fill="#666">真手枪在手里后坐行程量级 20 到 30 mm，这个量级不夸张</text>' % (L+8, LY(P2, 32, 90)))
svg.append('<text x="490" y="%d" font-size="12" fill="#333" text-anchor="middle">弹性安装固有频率 fm (Hz，对数轴)</text>' % (P2[1]+44))
svg.append('</svg>')
open("弹性安装设计曲线.svg", "w", encoding="utf-8").write("\n".join(svg))

# 表格数据
print("频率 f | 传到臂峰值力 | 肩力矩 | 肘力矩 | 腕力矩 | 相对行程")
for f in [30, 20, 17, 15, 12, 10, 8, 5]:
    Fn = min(2*_m.pi*f*I, F_src)
    print("%6.0f | %10.0f N | %6.1f | %6.1f | %5.1f | %6.1f mm" % (
        f, Fn, Fn*D["肩"], Fn*D["肘"], Fn*D["腕"], I/(m_d*2*_m.pi*f)*1000))
