# 04 Watertight 网格自动化

PyFluent 驱动 Watertight Geometry 工作流的核心是"任务舞蹈"和键名纪律。
本文按流程顺序给配方，坑单独标红。

## 1. 会话与工作流

```python
from ansys.fluent.core import launch_fluent
mesh = launch_fluent(mode="meshing", precision="double", processor_count=8,
                     product_version="25.2.0", ui_mode="no_gui_or_graphics", cwd=RUN)
wf = mesh.workflow
wf.InitializeWorkflow(WorkflowType="Watertight Geometry")
```

调试期**一律 `no_gui_or_graphics`**：GUI 模式下报错会弹模态对话框卡死脚本。

## 2. 任务执行包装

```python
def exec_task(task, args, label, hard=True):
    try:
        task.Arguments = args
        task.Execute()
        w = task.get_state().get("Warnings")
        if w: log(f"{label} 警告: {str(w)[:300]}")     # 警告必看！
        return True
    except Exception as e:
        log(f"✗ {label}: {repr(e)[:300]}")
        if hard: raise
```

**警告不是废话**：`stair-stepping occurred at N locations` 和
`minimum Orthogonal Quality of: X` 是后续求解发散的预告片。
OQ=0.00 的网格跑得动也别信——它是定时炸弹。

## 3. 键名纪律

- 键名权威 = 安装目录下 `settings_252.pyi`（求解器）/ pyfluent 包内
  `datamodel_252/meshing.py`（网格任务参数）。**猜键名是下策**。
- 非法键**静默丢弃**，只在 transcript 里留一行 "Illegitimate input"。
  所以设完关键参数后 `task.get_state()` 打印回读确认。

## 4. 边界层（棱柱层）的任务舞蹈

加边界层不能直接设参数，要先"舞"出子任务：

```python
bl = wf.TaskObject["Add Boundary Layers"]
bl.AddChildToTask()
bl.InsertCompoundChildTask()
# 子任务名动态找（比如 smooth-transition_1）
child = [t for t in wf.TaskObject.get_state().keys() if t not in KNOWN_TASKS][0]
c = wf.TaskObject[child]
c.Arguments = {"NumberOfLayers": 15, "Rate": 1.15, "TransitionRatio": 0.272}
c.Execute()
bl.Execute()      # 最后执行父任务
```

三条纪律：
1. **不要设 `OffsetMethodType`**——保持程序控制的 smooth-transition，首层厚度
   自适应（设了反而出负体积）。
2. 层数/增长率宁小勿大：实测 **15 层/1.15** 在薄板窄缝环境存活，
   **20 层/1.25** 阶梯化 16 处 + OQ=0 → 后续求解发散。
3. 首层高度的 y+ 目标靠表面网格尺寸间接控制，smooth-transition 会自己配平。

## 5. 发散加固（边界层网格专用）

加了棱柱层后 coupled 求解器可能在 100~200 步失稳（症状：力从 0.3 N 炸到 5 N、
出口 100% 逆流、湍流粘性比限幅单元几十万个、残差 1e7）。注意
**2025R2 的 coupled 默认已开伪瞬态**（log 里的 "Stabilizing pressure coupled"
是正常输出，不是问题）——所以出事了不能再怪"没开伪瞬态"。

实测有效的加固序列：

```python
m = solver.settings.solution.methods
m.expert.first_to_second_order_blending = 0.0   # 全一阶起步（数值耗散大但稳）
# ... 迭代 200 步 ...
m.expert.first_to_second_order_blending = 1.0   # 切回二阶收敛
```

外加驱动层的**力爆炸早停**：每 100 步读一次力，|F| 超过正常量级 5 倍立即终止，
别让发散烧 40 分钟。

## 6. cell zone 策略

- **正确分类的固体区不要删**（比如焊成一体后的"本体"固体区）：蒙皮 wall 天然
  存在，删除反而引发 zone 记账的随机行为。
- 远场面切分（sep-face-zone-angle）只对远场做：对整张蒙皮 wall 切分会让
  pyfluent RPC **永久挂死**（transcript 显示完成但 Python 永不返回）。
- TUI 命令传 zone 名带冒号/特殊字符会报 `wta to symbol->string`——
  **传 zone ID（整数）**。

## 7. TUI 与 settings 的缓存滞后（假收敛之源）

TUI 改完边界类型（zone_type）后，settings API 短期内看不到变化：

```python
# 错误：直接循环赋值 → inlets 为空 → 循环体没执行 → 入口速度是 0
# 正确：轮询 + 写后读回断言
for _ in range(8):
    inlets = list(solver.setup.boundary_conditions.velocity_inlet.get_state().keys())
    if inlets: break
    time.sleep(3)
assert inlets
# ... 赋值后 ...
vz = bc.velocity_inlet[inlets[0]].momentum.get_state()["velocity_components"][2]["value"]
assert abs(float(vz) + V0) < 1e-6
```

另一个同族坑：`get_state()` 里数组元素要再取 `["value"]`，直接 `.value` 拿到
的是包装对象。**残差 1e-10 的"完美收敛"+ 力全零 = 流场里根本没流动**，
先查入口速度再查别的。

## 8. 批量纪律

- 每构型独立子进程（见 templates/batch_driver.py）：崩溃不连坐、断点续跑、
  环境脏了不影响后续。
- 每构型独立运行目录 + 独立 transcript（.trn），排错时 grep。
- 先跑一发"探针"（只到网格阶段）确认新几何能过 Share Topology，再投全批。
