# -*- coding: utf-8 -*-
# ============================================================================
# 模板：逐面力积分（从整张蒙皮里切出子部件的受力）
# 原理与坑见 docs/06。三大自校验已内置：坐标映射失败率、驻点压力符号、窗口面积。
# 运行：python postproc_surface_forces.py
# ============================================================================
import sys, os, json, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("AWP_ROOT252", r"D:\Program Files\ANSYS Inc\v252")
import numpy as np

# --------------------------- USER CONFIG -----------------------------------
BASE  = r"D:\work"
CASE  = os.path.join(BASE, "runs", "sweep", "cfg_a")          # 含 .cas.h5/.dat.h5
CASE  = os.environ.get("SWEEP_CASE", CASE)
ZONES = ["part-fluid_box", "part-fluid_box-shadow"]           # 主面+影子面都要试
                                                              # 力在哪边随网格翻转
# 子部件极坐标窗口（部件嵌在共面升力面里时，盒窗口必被污染，docs/06 §4）
# (方位角deg, 半径范围[m], 方位半宽deg, 轴向范围[m])
WINDOWS = {
    "part1": dict(az=45.0,  r=(0.0219, 0.0593), daz=30.0, ax=(-0.126, -0.1045)),
    "part2": dict(az=135.0, r=(0.0219, 0.0593), daz=30.0, ax=(-0.126, -0.1045)),
}
AREA_KNOWN = {"part1": 15.8, "part2": 15.8}   # 部件已知面积 cm²（窗口面积自校验基准）
# ---------------------------------------------------------------------------

from ansys.fluent.core import launch_fluent
from ansys.fluent.core.fields.field_data_interfaces import (
    SurfaceFieldDataRequest, SurfaceDataType, ScalarFieldDataRequest)

# 找到存盘 case
cas = None
for z in ZONES + [CASE]:
    pass
cas = next((os.path.join(CASE, fn) for fn in os.listdir(CASE) if fn.endswith(".cas.h5")), None)
assert cas, "case 未找到"

solver = launch_fluent(mode="solver", precision="double", processor_count=4,
                       product_version="25.2.0", ui_mode="no_gui_or_graphics",
                       cwd=os.path.dirname(cas))
solver.file.read_case(file_name=cas.replace("\\", "/"))
solver.file.read_data(file_name=cas.replace(".cas.h5", ".dat.h5"))
fd = solver.fields.field_data

# 选出真正"活着"的 zone（力在主面还是影子面随网格翻转，docs/05 §1）
ZONE = None
for z in ZONES:
    try:
        a = np.asarray(list(fd.get_field_data(ScalarFieldDataRequest(
            field_name="pressure", surfaces=[z])).values())[0], dtype=float)
        if a.min() != 0.0 or a.max() != 0.0:
            ZONE = z
            print(f"活动 zone = {z}")
            break
    except Exception:
        continue
assert ZONE, "两个 zone 都全零？检查报告区域"

# ---------- 面几何（面积用 Newell 自算：face_normals 不可靠，docs/06 §2） ----------
r = fd.get_field_data(SurfaceFieldDataRequest(
    surfaces=[ZONE], data_types=[SurfaceDataType.FacesNormal,
                                 SurfaceDataType.FacesCentroid,
                                 SurfaceDataType.FacesConnectivity,
                                 SurfaceDataType.Vertices]))
d = r.get(ZONE) if hasattr(r, "get") else r
verts = np.asarray(d.vertices, dtype=float)
conn  = d.connectivity                       # 逐面节点 id 列表（无计数前缀）
c     = np.asarray(d.face_centroids, dtype=float)
n     = np.asarray(d.face_normals, dtype=float)
nf    = len(conn)

area = np.zeros(nf)
ngeo = np.zeros((nf, 3))
for i, seg in enumerate(conn):
    ids = np.asarray(seg, dtype=np.int64)
    vv = verts[ids]
    nv = np.zeros(3)
    for k in range(len(ids)):                # Newell: 0.5·Σ v_k × v_{k+1}
        nv += np.cross(vv[k], vv[(k + 1) % len(ids)])
    ngeo[i] = 0.5 * nv
    area[i] = np.linalg.norm(ngeo[i])
nhat = n / np.linalg.norm(n, axis=1)[:, None]    # fluent 法向只取方向

# ---------- 节点坐标映射（标量场节点序 ≠ 顶点序！docs/06 §3） ----------
def nodal(field):
    rr = fd.get_field_data(ScalarFieldDataRequest(field_name=field, surfaces=[ZONE]))
    return np.asarray(list(rr.values())[0], dtype=float)

nx, ny, nz = nodal("x-coordinate"), nodal("y-coordinate"), nodal("z-coordinate")
cmap = {(round(a,8), round(b,8), round(cc,8)): i
        for i, (a, b, cc) in enumerate(zip(nx, ny, nz))}
vidx = np.array([cmap[(round(v[0],8), round(v[1],8), round(v[2],8))] for v in verts])
assert (vidx >= 0).all(), "坐标映射失败"

def face_avg(field):
    a = nodal(field)
    return np.asarray([a[vidx[np.asarray(seg, dtype=np.int64)]].mean() for seg in conn])

p  = face_avg("pressure")
tx, ty, tz = face_avg("x-wall-shear"), face_avg("y-wall-shear"), face_avg("z-wall-shear")
F_shear = np.stack([tx, ty, tz], axis=1)

# ---------- 自校验 1：驻点区压力必须为正（映射错位探测器） ----------
ax_med = float(np.median(c[:, 2]))
nose = c[:, 2] > ax_med + 0.9 * (c[:, 2].max() - ax_med)
print(f"[校验] 驻点区 mean p = {p[nose].mean():+.1f} Pa（应为正；为负=映射/数据错）")

# ---------- 整面对账定符号（勿手推，docs/06 §5） ----------
F0p = (-p[:, None] * nhat * area[:, None]).sum(axis=0)
best = None
for sp in (+1, -1):
    for st in (+1, -1):
        F = sp * F0p + st * (F_shear * area[:, None]).sum(axis=0)
        # 用原生报告的力(N)做对账目标； HERE 填你的报告值（注意力矩报告是 Cm，见 docs/05 §2）
        target = np.array([-0.0645, 0.0435, -0.3047])   # <-- 换成你的 (f_side, f_norm, -f_axial)
        err = float(np.abs(F - target).sum())
        if best is None or err < best[0]:
            best = (err, sp, st, F)
err, SP_P, SP_T, Ftot = best
print(f"[对账] 符号 p×{SP_P} τ×{SP_T} 残差={err:.4f} N | F=({Ftot[0]:+.4f},{Ftot[1]:+.4f},{Ftot[2]:+.4f})")

def forces(mask):
    return (SP_P * -p[mask, None] * nhat[mask] * area[mask, None]
            + SP_T * F_shear[mask] * area[mask, None])

# ---------- 子部件窗口积分 ----------
def angdiff(a, b):
    dd = np.abs(a - b) % 360.0
    return np.minimum(dd, 360.0 - dd)

rr = np.hypot(c[:, 0], c[:, 1])
az_f = np.degrees(np.arctan2(c[:, 1], c[:, 0]))
out = {}
for name, wdef in WINDOWS.items():
    mask = ((rr > wdef["r"][0]) & (rr < wdef["r"][1]) &
            (angdiff(az_f, wdef["az"]) < wdef["daz"]) &
            (c[:, 2] > wdef["ax"][0]) & (c[:, 2] < wdef["ax"][1]))
    a_win = float(area[mask].sum() * 1e4)
    # ---------- 自校验 2：窗口面积 == 部件已知面积（污染/错位探测器） ----------
    dev = abs(a_win - AREA_KNOWN[name]) / AREA_KNOWN[name]
    print(f"[校验] {name}: 窗口面积 {a_win:.1f} cm² vs 已知 {AREA_KNOWN[name]} cm² (偏差 {dev*100:.1f}%)")
    Ff = forces(mask)
    out[name] = {"n_faces": int(mask.sum()), "area_cm2": a_win,
                 "F": [float(x) for x in Ff.sum(axis=0)],
                 "flag": "OK" if dev < 0.05 else "CHECK"}
    print(f"  {name}: F = {np.round(Ff.sum(axis=0), 4).tolist()} N")

with open(os.path.join(os.path.dirname(cas), "surface_forces.json"), "w", encoding="utf-8") as f:
    json.dump({"zone": ZONE, "calib": {"sign_p": SP_P, "sign_t": SP_T,
               "F_total": [float(x) for x in Ftot], "residual_N": err},
               "parts": out}, f, ensure_ascii=False, indent=1)
print("已保存 surface_forces.json")
try: solver.exit()
except Exception: pass
