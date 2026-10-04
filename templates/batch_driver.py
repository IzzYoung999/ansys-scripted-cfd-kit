# -*- coding: utf-8 -*-
# ============================================================================
# 模板：批量驱动（断点续跑 + 子进程隔离）
# 设计：docs/07 §4。每构型一个独立 Fluent 子进程，崩一个不连坐；
#       summary 文件存在 = 已完成，自动跳过；删目录即强制重跑。
# 运行：python batch_driver.py
# ============================================================================
import os, subprocess, sys, time

BASE = r"D:\work"
SWEEP = os.path.join(BASE, "runs", "sweep")
PY    = r"D:\miniconda3\envs\ansys\python.exe"      # 绝对路径！WindowsApps 有假 python
SOLVE = os.path.join(os.path.dirname(__file__), "mesh_solve_wt.py")

CONFIGS = ["cfg_a", "cfg_b", "cfg_c"]               # 与 dsco 文件名对应

T0 = time.time()
def log(m): print(f"[{(time.time()-T0)/60:6.1f}min] {m}", flush=True)

done, failed = [], []
for cfg in CONFIGS:
    src  = os.path.join(SWEEP, cfg + ".dsco")
    rund = os.path.join(SWEEP, cfg)
    summ = os.path.join(rund, cfg + "_summary.json")

    if not os.path.exists(src):
        log(f"跳过 {cfg}: dsco 不存在（先跑几何模板）")
        continue
    if os.path.exists(summ):
        log(f"跳过 {cfg}: 已完成（断点续跑）")
        done.append(cfg)
        continue
    os.makedirs(rund, exist_ok=True)

    env = os.environ.copy()
    env["SWEEP_CFG"] = cfg
    env["SWEEP_SRC"] = src
    env["SWEEP_RUN"] = rund
    log(f"=== 开始 {cfg} ===")
    # 子进程隔离：崩溃只丢自己；独立日志文件，排错 grep 用
    with open(os.path.join(SWEEP, f"solve_{cfg}.log"), "w",
              encoding="utf-8", errors="replace") as lf:
        rc = subprocess.call([PY, SOLVE], stdout=lf, stderr=subprocess.STDOUT,
                             env=env, cwd=rund)
    if rc == 0 and os.path.exists(summ):
        log(f"=== {cfg} 完成 ✓ ===")
        done.append(cfg)
    else:
        log(f"=== {cfg} 失败 rc={rc}（见 solve_{cfg}.log）✗ ===")
        failed.append(cfg)

log(f"全部结束: 成功 {len(done)}/{len(CONFIGS)}, 失败: {failed}")
if failed:
    sys.exit(2)
