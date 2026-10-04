# ansys-scripted-cfd-kit

**EN** A toolkit for fully scripted external-aerodynamics CFD with ANSYS 2025R2,
validated in a production project: SpaceClaim/Discovery scripting for parametric geometry,
PyFluent-driven Watertight meshing and solving, and face-wise force integration from raw
field data — with documented failure modes and workarounds. 中文正文见下方。

---

## 这是什么

一套在真实项目中完整验证过的**全脚本化外流 CFD 管线**，以及开发过程中遇到的全部问题的分析与规避记录。
覆盖 ANSYS 2025R2 + PyFluent 0.42 + SpaceClaim/Discovery 脚本（IronPython）。

适用场景：你需要对**一系列只差局部几何的构型**（比如某个可动部件的不同偏转状态）
批量做"改几何 → 画网格 → 算收敛 → 提取分部件受力"。手工 GUI 点不动这种矩阵，
这套管线能把单个构型的成本压到 25 分钟且全程无人值守。

```
Parametric CAD (SpaceClaim scripting)
        │  .dsco
        ▼
Watertight meshing (PyFluent, headless)
        │  .cas.h5
        ▼
Solve (SST k-ω, coupled, boundary layers)
        │  .dat.h5
        ▼
Face-wise force integration (field_data)
        │  CSV / JSON
        ▼
Aero derivatives for flight dynamics
```

## 快速导览

| 文档 | 内容 | 你什么时候需要读 |
|---|---|---|
| [docs/01_pipeline_overview.md](docs/01_pipeline_overview.md) | 全链路总览与设计决策 | 先读这个 |
| [docs/02_spaceclaim_discovery.md](docs/02_spaceclaim_discovery.md) | Discovery 脚本化：API 姿势、隐藏模式、布尔语义 | 要改几何 |
| [docs/03_geometry_topology.md](docs/03_geometry_topology.md) | 拓扑不可解拓扑问题目录：穿插、共面对接、楔角退化 | 几何是装配体/含可动件 |
| [docs/04_watertight_meshing.md](docs/04_watertight_meshing.md) | WT 工作流自动化 + 边界层配方 + 发散加固 | 画网格 |
| [docs/05_solver_pitfalls.md](docs/05_solver_pitfalls.md) | 求解侧常见陷阱：shadow 面、假收敛、量纲陷阱 | 出结果之前 |
| [docs/06_field_data_postproc.md](docs/06_field_data_postproc.md) | 逐面力积分：节点映射、Newell 面积、自校验 | 要分部件受力 |
| [docs/07_ops_checklist.md](docs/07_ops_checklist.md) | 运维：僵尸进程、许可证、基线导入验证、自校验哲学 | 排错时 |
| [docs/case-guided-dart/](docs/case-guided-dart/README.md) | 案例：细长体+四尾舵的完整实战记录 | 想看本工具箱实战 |
| [templates/](templates/) | 可跑模板脚本（逐行注释） | 直接抄 |

## 常见问题速查表（实战问题速查）

| 症状 | 真相 | 出口 |
|---|---|---|
| SW 合并报"厚度为 0 的实体" | 穿插/共面接触，任何网格参数无解 | Parasolid 脚本布尔 |
| 气动力全是 0 | 力在 two-sided wall 的 `-shadow` 面（且主/影归属会随网格翻转） | 报告区含两个面 |
| 残差 1e-10"收敛"但流场是死的 | TUI 改边界后 settings 缓存滞后，入口速度没写进去 | 写后读回断言 |
| 力从 0.3 N 炸到 5 N | 边界层棱柱在窄缝阶梯化，OQ=0 的严重隐患 | 减棱柱+一阶起步 200 步 |
| 力矩报告"对不上" | `rd.compute()` 对力矩返回的是无量纲系数 Cm 不是 N·m | 乘回 q·A·L 再比 |
| 逐面压力贴错面（驻点负压） | 标量场节点序 ≠ 面数据顶点序 | 坐标钥匙映射 |
| Fluent 启动超时/连接重置 | 上次会话的僵尸 fluent/cx 进程占着资源 | 清场+基线导入验证 |
| TUI 命令 "invalid command" | 2025R2 砍了一片 TUI 菜单 | 查 pyi/datamodel 走 settings API |
| STEP 里 bbox 大得离谱 | CARTESIAN_POINT 混有参考点/圆心 | 只信 VERTEX_POINT |

## 环境要求

- ANSYS 2025 R2（Discovery、Fluent Meshing/Solver）
- Python 3.12 + `ansys-fluent-core==0.42.1`（独立 conda 环境即可）
- Windows（脚本均按 Windows/PowerShell 或 Git Bash 调试）

## License

MIT
