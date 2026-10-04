# -*- coding: utf-8 -*-
# ============================================================================
# 模板：Discovery 批量参数化几何（IronPython 2.7，隐藏模式运行）
# 功能：打开基础 STEP → 绕实测轴线旋转可动件到目标角度 → 布尔并集 → 导出 .dsco
# 运行：Discovery.exe --hidden --exit-after-script --run-script geom_discovery_batch.py
# 逐行注释说明"为什么这么写"，坑的背景见 docs/02、docs/03。
# ============================================================================
import os, math, traceback

# --------------------------- USER CONFIG -----------------------------------
SRC    = r"D:\work\model_base.step"        # 基础几何：本体+全部可动件+外流场盒（mm）
OUTDIR = r"D:\work\sweep"
BODY_KEY = "body"                          # 本体实体名里的唯一子串
BOX_KEY  = "fluid_box"                     # 外流盒实体名里的唯一子串
# 可动件铰链轴：单位【米】！Discovery 内部一律米（见 docs/03 §5）
# (子串匹配名, 轴上一点[x,y,z]_m, 轴方向单位向量[x,y,z], 当前预偏角deg)
PARTS = {
    1: dict(key="-1-solid", pt=[0.0224, 0.0226, -0.1060],
            ax=[0.7071, 0.7071, 0.0], cur=15.0),
    2: dict(key="-2-solid", pt=[-0.0225, 0.0225, -0.1063],
            ax=[-0.7071, 0.7071, 0.0], cur=0.0),
}
# 构型表：(输出名, [(件号, 目标绝对角度deg), ...])；角度是"绝对目标"，脚本换算增量
CONFIGS = [("part1_p10", [(1, 10.0)]),
           ("part1_p0",  [(1, 0.0)]),     # 注意 docs/03 §2：0° 若是共面退化角要避开
           ("part2_p15", [(2, 15.0)])]
# ---------------------------------------------------------------------------

# 日志必须自己写文件：隐藏模式没有控制台，print 不落盘（docs/02 §1）
OUT = os.path.join(OUTDIR, "geom_log.txt")
if not os.path.exists(OUTDIR):
    os.makedirs(OUTDIR)
f = open(OUT, "w")
def w(s):
    f.write(unicode(s).encode("utf-8") + "\n"); f.flush()   # IronPython2 无 f-string

from SpaceClaim.Api.V252 import WindowExportFormat
from SpaceClaim.Api.V252.Geometry import Matrix, Line, Point, Direction

def bodies():
    return list(Window.ActiveWindow.Document.MainPart.GetAllBodies())

def find_part(key):
    """按子串找实体——实体名来自 STEP 产品名，可能带中文空格，别用精确匹配"""
    for b in bodies():
        if key in b.Name:
            return b
    return None

def rotate_to(b, h, target_deg):
    """把可动件绕铰链线转到目标绝对角度。刚体旋转，体积必须不变。"""
    delta = target_deg - h["cur"]                       # 增量 = 目标 - 当前
    pt = Point.Create(h["pt"][0], h["pt"][1], h["pt"][2])
    dirv = Direction.Create(h["ax"][0], h["ax"][1], h["ax"][2])
    line = Line.Create(pt, dirv)                        # Matrix.CreateRotation 绕"线"旋转
    m = Matrix.CreateRotation(line, math.radians(delta))
    v0 = b.Shape.Volume
    b.Transform(m)                                      # DesignBody.Transform 原地变换
    v1 = b.Shape.Volume
    w("  旋到 %+.1f°: vol %.6e -> %.6e %s" % (target_deg, v0, v1,
                                              "OK" if abs(v0 - v1) < 1e-12 else "!!体积变了"))
    if abs(v0 - v1) >= 1e-12:                           # 自校验：刚体变换体积不变
        raise Exception("非刚体旋转")

for name, ops in CONFIGS:
    try:
        w("=== %s: %r ===" % (name, ops))
        File.Open(SRC)                                  # 返回 None，别接返回值（docs/02 §2）
        # ① 旋转目标可动件；未列出的件保持原状
        for (n, ang) in ops:
            b = find_part(PARTS[n]["key"])
            if b is None:
                raise Exception("找不到可动件 %d" % n)
            rotate_to(b, PARTS[n], ang)
        # ② 布尔并集：全部可动件焊进本体（穿插/零厚接触由 Parasolid 吞掉，docs/03 §1）
        target = find_part(BODY_KEY)
        for _ in range(8):
            tools = [b for b in bodies()
                     if BODY_KEY not in b.Name and BOX_KEY not in b.Name]
            if not tools or target is None:
                break
            target.Shape.Unite(tools[0].Shape)          # 原地并入，返回 None，吃掉 tool
        allb = bodies()
        for b in allb:
            w("  %s vol=%.6e" % (b.Name, b.Shape.Volume))
        # ③ 自校验：并集后应只剩 本体 + 外流盒
        if len(allb) != 2:
            w("  !! 实体数 %d != 2，不导出" % len(allb))
            continue
        # ④ 导出 dsco（WT 只认 dsco；SaveAs 会挂死，永远用 Export，docs/02 §6）
        eo = ExportOptions.Create()
        eo.CleanUpBodies = False
        eo.ExportNames = True                           # 保留实体名 → 下游 zone 名可读
        Window.ActiveWindow.Export(WindowExportFormat.DISCO,
                                   os.path.join(OUTDIR, name + ".dsco"), eo)
        w("  已导出 " + name + ".dsco")
    except Exception:
        w(traceback.format_exc())                       # 顶层兜底：异常必须落盘
w("=== 全部完成 ===")
f.close()
