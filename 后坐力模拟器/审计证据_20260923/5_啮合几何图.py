# -*- coding: utf-8 -*-
"""
不完全齿轮-齿条啮合几何图（按 m1 z18 alpha20 的真值坐标绘制，单位 mm）
坐标系：齿条节线 y=0，节点 P=(0,0)，齿轮中心 O1=(0, r=9)
啮合线：过 P、与节线成 alpha=20 度，且切于基圆 rb=8.4575（切点 N1=(2.892,1.053)）
"""
import math
a = math.radians(20.0)
m, z = 1.0, 18
r = m*z/2; rb = r*math.cos(a); ra = r + m
u = (math.cos(a), math.sin(a))          # 啮合线方向
# 起点 A：齿条齿顶线 y=+m 与啮合线交点
xA = m/math.tan(a); A = (xA, m)
g_a = math.hypot(*A)
# 终点 E：齿轮齿顶圆与啮合线交点（在 P 另一侧）
N1 = (rb*math.sin(a), r - rb*math.cos(a))
L_N1E = math.sqrt(ra**2 - rb**2)
E = (N1[0] - L_N1E*u[0], N1[1] - L_N1E*u[1])
g_r = math.hypot(*E)
g = g_a + g_r
pb = math.pi*m*math.cos(a)
eps = g/pb
print("A=(%.3f,%.3f) P=(0,0) E=(%.3f,%.3f) N1=(%.3f,%.3f)" % (A[0],A[1],E[0],E[1],N1[0],N1[1]))
print("g_a=%.4f  g_r=%.4f  g=%.4f  pb=%.4f  eps=%.4f" % (g_a,g_r,g,pb,eps))

S = 62.0                                  # px per mm
W,H = 1000, 560
OX, OY = 690, 210                         # 画布上 P 的位置
def XY(p): return (OX + p[0]*S, OY - p[1]*S)
svg = []
svg.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="Microsoft YaHei, SimHei, sans-serif">' % (W,H,W,H))
svg.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (W,H))
svg.append('<text x="%d" y="30" font-size="19" font-weight="bold" text-anchor="middle">不完全齿轮-齿条啮合几何：单齿啮合长度从哪来（m1 z18 α20，按真值坐标绘制）</text>' % (W//2))
def line(p1,p2,col,w=1.5,dash=None,op=1.0):
    x1,y1=XY(p1); x2,y2=XY(p2)
    st='stroke-dasharray="%s"'%dash if dash else ''
    svg.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" opacity="%.2f" %s/>'%(x1,y1,x2,y2,col,w,op,st))
def label(p,txt,col="#333",dx=0,dy=0,fs=13,anchor="start"):
    x,y=XY(p)
    svg.append('<text x="%.1f" y="%.1f" font-size="%d" fill="%s" text-anchor="%s">%s</text>'%(x+dx,y+dy,fs,col,anchor,txt))
def dot(p,col="#d62728",rr=4):
    x,y=XY(p); svg.append('<circle cx="%.1f" cy="%.1f" r="%d" fill="%s"/>'%(x,y,rr,col))
# 节线与齿顶线
line((-5.6,0),(4.3,0),"#333",1.8)
line((-5.6,m),(4.3,m),"#1f77b4",1.6,"6 4")
label((-5.5,0),"齿条节线",dy=-8,fs=12)
label((-5.5,m),"齿条齿顶线（高出 m）",col="#1f77b4",dy=-8,fs=12)
# 啮合线
line((-5.2,-1.893),(7.0,2.548),"#8c564b",2.0)
label((5.2,2.2),"啮合线（与节线成 α=20°）",col="#8c564b",fs=12)
# 齿轮齿顶圆（画弧，中心 O1）
O1=(0,r); 
pts=[]
th0=math.atan2(E[1]-O1[1],E[0]-O1[0])
for i in range(41):
    th=th0 - 0.9 + 1.8*i/40.0
    pts.append((O1[0]+ra*math.cos(th), O1[1]+ra*math.sin(th)))
svg.append('<polyline points="%s" fill="none" stroke="#2ca02c" stroke-width="1.6" stroke-dasharray="5 3"/>'%(" ".join("%.1f,%.1f"%XY(p) for p in pts)))
label((E[0]-1.1,E[1]-0.5),"齿轮齿顶圆",col="#2ca02c",fs=12,anchor="middle")
# 关键点
for p,name,col in [(A,"A（接触起点：齿条齿顶入啮合）","#d62728"),((0,0),"P（节点）","#333"),(E,"E（接触终点：齿轮齿顶退出）","#d62728"),(N1,"N1（基圆切点，路径外）","#7f7f7f")]:
    dot(p,col,4); 
label(A,"A 接触起点",col="#d62728",dx=6,dy=-8,fs=13)
label((0,0),"P 节点",dx=6,dy=18,fs=13)
label(E,"E 接触终点",col="#d62728",dx=-14,dy=-10,fs=13)
label(N1,"N1 基圆切点",col="#7f7f7f",dx=6,dy=-8,fs=12)
# 尺寸：g_a 与 g_r
line(A,(A[0],0),"#999",1.0,"3 3"); dot((A[0],0),"#999",3)
line((0,0),(A[0],0),"#999",1.0,"3 3")
svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="#555">齿条齿顶高 m=1</text>'%XY((A[0]+0.05,0.5)))
# 角标注
svg.append('<path d="M %.1f %.1f A 40 40 0 0 0 %.1f %.1f" fill="none" stroke="#333" stroke-width="1.2"/>'%(
    XY((0.75,0))[0],XY((0.75,0))[1], XY((0.75*math.cos(a),0.75*math.sin(a)))[0], XY((0.75*math.cos(a),0.75*math.sin(a)))[1]))
label((0.95,0.12),"α",fs=14)
# 两个齿对的接触区间（基节 pb 相隔）
A2 = (A[0]-pb*u[0], A[1]-pb*u[1]); E2=(E[0]-pb*u[0], E[1]-pb*u[1])
for (p1,p2,col,txt,dy) in [(A,E,"#d62728","第 1 对齿：A→E",-26),(A2,E2,"#ff7f0e","第 2 对齿：A′→E′（相差一个基节 pb）",34)]:
    x1,y1=XY(p1); x2,y2=XY(p2)
    svg.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="4.5" opacity="0.55"/>'%(x1,y1,x2,y2,col))
    svg.append('<text x="%.1f" y="%.1f" font-size="12.5" fill="%s">%s</text>'%((x1+x2)/2-40,y1+dy,col,txt))
dot(A2,"#ff7f0e",4); dot(E2,"#ff7f0e",4)
label(A2,"A′",col="#ff7f0e",dx=-18,dy=-6,fs=13); label(E2,"E′",col="#ff7f0e",dx=4,dy=14,fs=13)
# 说明块
info = [
 "推导要点（全部按 m=1、z=18、α=20° 真值代入）",
 "① 起点 A：齿条齿顶线 y=m 与啮合线相交 ⇒ g_a = m/sinα = %.3f mm" % g_a,
 "    （直角三角形 A-F-P：AF=m，∠APF=α ⇒ AP = m/sinα）",
 "② 终点 E：齿轮齿顶圆与啮合线相交 ⇒ g_r = √(r_a²−r_b²) − r·sinα = %.3f mm" % g_r,
 "③ 实际啮合线长 g = g_a + g_r = %.3f mm" % g,
 "④ 基节 p_b = π·m·cosα = %.3f mm（相邻两对齿在啮合线上的间距）" % pb,
 "⑤ 重合度 εα = g/p_b = %.3f（同时参与啮合的齿对数）" % eps,
 "⑥ 接触点在啮合线上移动速度 = r_b·ω ⇒ 一对齿全程经历转角 g/r_b",
 "   换算到节圆弧长 = g/cosα = εα·π·m = %.3f mm ⇐这就是\"多出来的一截\"" % (eps*math.pi*m),
 "⑦ 故不完全齿轮的实际啮合行程 L = n·π·m + εα·π·m = (n + εα)·π·m",
 "   图中红色段=第1对齿接触区间，橙色=第2对齿，两者重叠 %.2f 个基节（=εα−1）" % (eps-1),
]
y0 = 350
svg.append('<rect x="40" y="%d" width="920" height="%d" fill="#f8f8f8" stroke="#ddd"/>'%(y0-24,26*len(info)+18))
for i,t in enumerate(info):
    svg.append('<text x="56" y="%d" font-size="13" fill="%s">%s</text>'%(y0+i*26, "#111" if i==0 else "#333", t))
svg.append('</svg>')
open("啮合几何图.svg","w",encoding="utf-8").write("\n".join(svg))
print("SVG written")
