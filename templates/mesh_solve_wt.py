# -*- coding: utf-8 -*-
# ============================================================================
# 模板：Watertight 网格 + 求解一条龙（CPython + PyFluent 0.42 / Fluent 2025R2）
# 运行：python mesh_solve_wt.py   （SWEEP_CFG/SWEEP_SRC/SWEEP_RUN 环境变量可覆盖）
# 坑的出处见 docs/04（网格）、docs/05（求解）。所有"读回断言"一个都不能删。
# ============================================================================
import sys, os, json, time, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("AWP_ROOT252", r"D:\Program Files\ANSYS Inc\v252")   # 许可/安装定位

# --------------------------- USER CONFIG（可用环境变量覆盖） -----------------
BASE = r"D:\work"
CFG  = os.environ.get("SWEEP_CFG", "cfg_a")
RUN  = os.environ.get("SWEEP_RUN", os.path.join(BASE, "runs", "sweep", CFG))
SRC  = os.environ.get("SWEEP_SRC", os.path.join(BASE, "runs", "sweep", CFG + ".dsco"))
A_REF, L_REF = 0.003118, 0.255        # 参考面积/长度（与几何配套！跨构型比较前先核对）
V0   = 17.0                           # 来流速度
F_EXPLODE = 2.0                       # 力爆炸早停阈值（正常量级的 ~5 倍）
# 子区域窗口（可选，用于分部件积分；极坐标定义见 docs/06 §4）
# ---------------------------------------------------------------------------

os.makedirs(RUN, exist_ok=True)
T0 = time.time()
def log(m): print(f"[{time.time()-T0:7.1f}s] {m}", flush=True)

from ansys.fluent.core import launch_fluent

# ---------- 网格阶段（headless：调试期禁 GUI，报错弹窗会卡死脚本 docs/04 §1） ----------
mesh = launch_fluent(mode="meshing", precision="double", processor_count=8,
                     product_version="25.2.0", ui_mode="no_gui_or_graphics", cwd=RUN)
try:
    mesh.tui.file.start_transcript(os.path.join(RUN, "mesh.trn"))   # 留档，排错靠它
except Exception:
    pass
wf = mesh.workflow
wf.InitializeWorkflow(WorkflowType="Watertight Geometry")

def exec_task(task, args, label, hard=True):
    try:
        task.Arguments = args
        task.Execute()
        w = task.get_state().get("Warnings")
        if w:
            log(f"{label} 警告: {str(w)[:300]}")     # 警告=发散前期征兆，必须看（docs/04 §2）
        log(f"{label} 完成")
        return True
    except Exception as e:
        log(f"✗ {label}: {repr(e)[:300]}")
        if hard:
            raise
        return False

imp = wf.TaskObject["Import Geometry"]
imp.Arguments = {"FileName": SRC, "LengthUnit": "mm"}
imp.Execute()                                       # Meshing→Solver 自动 mm→m，勿再缩放
log(f"导入 {len(mesh.meshing_utilities.get_all_objects())} 对象")

exec_task(wf.TaskObject["Generate the Surface Mesh"], {"CFDSurfaceMeshControls": {
    "MinSize": 1.5, "MaxSize": 60.0, "GrowthRate": 1.2, "CurvatureNormalAngle": 18.0,
}}, "表面网格")

exec_task(wf.TaskObject["Describe Geometry"], {
    "SetupType": "The geometry consists of both fluid and solid regions and/or voids",
    "CappingRequired": "No", "WallToInternal": "No",
    "InvokeShareTopology": "Yes", "Multizone": "No"}, "描述几何")
exec_task(wf.TaskObject["Update Boundaries"], {}, "更新边界", hard=True)
exec_task(wf.TaskObject["Update Regions"], {}, "更新区域", hard=True)

# ---------- 边界层：子任务创建流程 + 保守参数（docs/04 §4） ----------
bl = wf.TaskObject["Add Boundary Layers"]
try:
    bl.AddChildToTask(); bl.InsertCompoundChildTask()
except Exception as e:
    log(f"BL 子任务创建流程失败: {repr(e)[:200]}")
KNOWN = {"Import Geometry", "Add Local Sizing", "Generate the Surface Mesh",
         "Describe Geometry", "Enclose Fluid Regions (Capping)", "Update Boundaries",
         "Create Regions", "Update Regions", "Add Boundary Layers",
         "Generate the Volume Mesh", "Apply Share Topology"}
child = next((t for t in wf.TaskObject.get_state().keys() if t not in KNOWN), None)
c = wf.TaskObject[child]
c.Arguments = {"NumberOfLayers": 15, "Rate": 1.15, "TransitionRatio": 0.272}
c.Execute()                                          # 只设层数/速率/过渡比，勿碰 OffsetMethodType
bl.Execute()
log("边界层完成")

exec_task(wf.TaskObject["Generate the Volume Mesh"],
          {"VolumeFill": "poly-hexcore"}, "体网格", hard=True)

# ---------- 切求解器 ----------
solver = mesh.switch_to_solver()
log("进入求解器")
try:
    solver.tui.mesh.check()
except Exception:
    pass

bc = solver.setup.boundary_conditions
allwalls = list(bc.get_state().get("wall", {}).keys())

# ---------- 远场切分 + 边界类型（只切远场！整皮切分会让 RPC 永久挂起无响应 docs/04 §6） ----------
from ansys.fluent.core.fields.field_data_interfaces import ScalarFieldDataRequest
fd = solver.fields.field_data
def centroid(z):
    cs = [float(np.asarray(list(fd.get_field_data(ScalarFieldDataRequest(
        field_name=cmp, surfaces=[z])).values())[0], dtype=float).ravel().mean())
        for cmp in ("x-coordinate", "y-coordinate", "z-coordinate")]
    return cs
import numpy as np
pos = {w_: centroid(w_) for w_ in allwalls}
def is_far(p):   # 按几何尺度改：远离弹体邻域的 wall 即远场
    return abs(p[0]) > 0.5 or abs(p[1]) > 0.5 or p[2] > 0.5 or p[2] < -1.0
far = [w_ for w_ in allwalls if is_far(pos[w_])]

# TUI 传 zone ID 不传名字（冒号名会 wta 报错 docs/04 §6）
zid = {}
try:
    solver.tui.define.boundary_conditions.list_zones()
except Exception:
    pass
time.sleep(2)
import glob, re
for tf in sorted(glob.glob(os.path.join(RUN, "fluent-*.trn")), key=os.path.getmtime)[-1:]:
    for m in re.finditer(r"^\s*\(?(\d+)\s+\(?([^\s)]+)\)?\s*\)?\s+(wall|velocity-inlet|pressure-outlet)",
                         open(tf, encoding="utf-8", errors="ignore").read(), re.M):
        zid[m.group(2)] = int(m.group(1))
outlet = min(far, key=lambda w_: pos[w_][2])
for w_ in far:
    if w_ in zid:
        solver.tui.define.boundary_conditions.zone_type(
            zid[w_], "pressure-outlet" if w_ == outlet else "velocity-inlet")

# 入口速度：轮询等缓存 + 写后读回断言（假收敛之源，docs/04 §7 / docs/05 §3）
inlets = []
for _ in range(8):
    inlets = list(bc.velocity_inlet.get_state().keys())
    if inlets:
        break
    time.sleep(3)
assert inlets, "没有 velocity-inlet（zone_type 未生效？）"
for w_ in inlets:
    m_ = bc.velocity_inlet[w_].momentum
    m_.velocity_specification_method = "Components"
    comps = m_.velocity_components
    try: comps.resize(3)
    except Exception: pass
    comps[0].value = 0.0; comps[1].value = 0.0; comps[2].value = -V0
vz = bc.velocity_inlet[inlets[0]].momentum.get_state()["velocity_components"][2]["value"]
assert abs(float(vz) + V0) < 1e-6, "入口速度未生效！"
log(f"入口速度读回 {vz} m/s")

rv = solver.settings.setup.reference_values
rv.area = A_REF; rv.length = L_REF; rv.velocity = V0; rv.density = 1.225

# ---------- 报告定义：区域必须含主面和影子面（力在 -shadow 上，docs/05 §1） ----------
body_surf = [w_ for w_ in allwalls if not is_far(pos[w_])]
rd = solver.settings.solution.report_definitions
rd.force["f_axial"] = {"force_vector": [0, 0, -1], "zones": body_surf}
rd.force["f_side"]  = {"force_vector": [1, 0, 0],  "zones": body_surf}
rd.force["f_norm"]  = {"force_vector": [0, 1, 0],  "zones": body_surf}
rd.moment["m_roll"]  = {"mom_center": [0,0,0], "mom_axis": [0,0,1], "zones": body_surf}
rd.moment["m_pitch"] = {"mom_center": [0,0,0], "mom_axis": [0,1,0], "zones": body_surf}

solver.settings.solution.initialization.hybrid_initialize()

# ---------- 发散加固：一阶起步 200 步再切二阶（docs/04 §5） ----------
_m = solver.settings.solution.methods
try:
    _m.expert.first_to_second_order_blending = 0.0
    log("一阶起步 = 0.0")
except Exception as e:
    log(f"blending 失败: {repr(e)[:120]}")

REP = ["f_axial", "f_side", "f_norm", "m_roll", "m_pitch"]
def reports():
    out = {}
    for k in REP:
        try:
            r = rd.compute(report_defs=[k])
            v = r.get(k) if isinstance(r, dict) else (r[0] if isinstance(r, list) else r)
            if isinstance(v, (dict, list)):
                v = list(v.values())[0] if isinstance(v, dict) else v[0]
            if isinstance(v, (list, tuple)):
                v = v[0]
            out[k] = float(v)
        except Exception:
            out[k] = None
    return out

calc = solver.settings.solution.run_calculation
hist = []
for start in range(0, 800, 100):
    try: calc.iterate(iter_count=100)
    except TypeError: calc.iterate(count=100)
    rep = reports()
    hist.append({"iter": start + 100, **rep})
    log(f"[{start+100} 步] {json.dumps(rep)}")
    if start >= 200:
        try:
            _m.expert.first_to_second_order_blending = 1.0    # 切回二阶
        except Exception:
            pass
    if rep.get("f_axial") is not None and abs(rep["f_axial"]) > F_EXPLODE:
        log("!!! 力爆炸，发散，提前终止")                      # 别让发散烧 40 分钟
        break
    if (len(hist) >= 4 and start >= 400 and
            all(abs(hist[-1][k] - hist[-3][k]) / max(abs(hist[-3][k]), 1e-9) < 0.01
                for k in ("f_axial", "f_side") if hist[-1][k] is not None)):
        log("收敛判据满足")
        break

# ---------- 存盘 + summary（summary 存在 = 断点续跑的"已完成"标记） ----------
cas = os.path.join(RUN, f"{CFG}.cas.h5").replace("\\", "/")
solver.file.write_case(file_name=cas)
solver.file.write_data(file_name=cas.replace(".cas.h5", ".dat.h5"))
with open(os.path.join(RUN, f"{CFG}_summary.json"), "w", encoding="utf-8") as f:
    json.dump({"cfg": CFG, "case": cas, "final": reports(),
               "hist_tail": hist[-6:], "body_walls": body_surf}, f,
              ensure_ascii=False, indent=1)
log(f"=== {CFG} DONE ===")
try: solver.exit()
except Exception: pass
