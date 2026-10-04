# 06 逐面力积分（field_data 后处理）

当你需要"从一整张蒙皮里切出某个子部件的受力"（部件已被布尔并进本体、
不再是独立壁面），或者要绕开 2025R2 被砍掉的 TUI 表面工具时，唯一稳的路是：
**把面的原始数据拉出来自己积分**。本文是这套方法的完整说明书。

## 1. 数据从哪来

```python
from ansys.fluent.core.fields.field_data_interfaces import (
    SurfaceFieldDataRequest, SurfaceDataType, ScalarFieldDataRequest)

r = fd.get_field_data(SurfaceFieldDataRequest(
    surfaces=[zone],
    data_types=[SurfaceDataType.FacesNormal,     # 面法向
                SurfaceDataType.FacesCentroid,   # 面质心
                SurfaceDataType.FacesConnectivity,  # 面连接（节点id表）
                SurfaceDataType.Vertices]))      # 顶点坐标
d = r.get(zone)
verts, conn = d.vertices, d.connectivity
cent, nrm  = d.face_centroids, d.face_normals
```

标量场（压力/剪切/y+）用 `ScalarFieldDataRequest`，返回**节点值**数组。
`get_mesh()` 对 face zone 会抛 `NotImplementedError`——别走那条路。

## 2. 面积：必须自己算（Newell 公式）

实测 `face_normals` **既不是单位向量也不是面积加权**（|n| 最大才 8e-6，
与任何面积对不上）。它只能当**方向**用。面积用 Newell 公式从顶点算：

```python
for i, seg in enumerate(conn):            # conn = 逐面节点 id 列表（无计数前缀）
    vv = verts[np.asarray(seg, dtype=np.int64)]
    nv = np.zeros(3)
    for k in range(len(ids)):
        nv += np.cross(vv[k], vv[(k + 1) % len(vv)])
    area[i] = np.linalg.norm(nv * 0.5)    # |0.5·Σ v_k × v_{k+1}|
```

法向方向：Fluent 的 n 与 Newell 几何法向**恰好整体差 180°**（顶点绕向约定），
一致性检验应为 0% 同向——这是正常的，符号问题交给与原生报告的对账统一解决。

## 3. 节点映射（最阴险的坑）

**标量场调用的节点顺序 ≠ SurfaceData 的顶点顺序**（连节点总数都可能不同）。
直接按索引配对，会把压力贴到错误的面上——后果是力的总和可能看着还算正常
（大数平均），但空间分布全错、力矩离谱。

**识别**（物理不可能检验，强烈建议内置）：
- 驻点区（迎风面）平均压力必须为正——若为负，映射必错；
- 部件窗口的面积必须等于该部件的已知几何面积——差多了必有污染或错位。

**修复**：坐标钥匙映射。拉一遍 `x/y/z-coordinate` 的节点值，建坐标字典，
顶点按坐标查表：

```python
coord_map = {(round(x,8), round(y,8), round(z,8)): i for i, (x, y, z) in enumerate(nodal_xyz)}
vidx = [coord_map[(round(v[0],8), round(v[1],8), round(v[2],8))] for v in verts]
# 面值 = 该面节点值的平均
face_p = [nodal_p[vidx[i]].mean() for i in conn]
```

映射失败率应 = 0，>1% 直接中止排查。

## 4. 子区域窗口：用极坐标，别用盒窗口

要切"嵌在共面升力面里的那块控制面"时，笛卡尔盒窗口必然把旁边的固定面
圈进来（实测 15.8 cm² 的面圈出 39.6 cm²）。改用**部件的真实几何参数**：

```
半径 r ∈ [r_in, r_out]、方位角 ±Δ、弦向范围 [z0, z1]
```

验收：窗口总面积 == 该部件已知面积（±2%）。这个等式成立，积分才可信。

## 5. 积分与符号

```
F = Σ_faces ( S_p · (−p·n̂·A) + S_τ · (τ⃗·A) )
M = Σ_faces ( (r_face − r_ref) × dF )
```

符号有两个自由度（压力取负取正、剪切取负取正），**不要手推**——整面
对账定符号：把整个 zone 积分一遍，与 Fluent 原生报告对齐，残差应在百分之几
以内（节点→面平均的固有误差）。对账时注意力矩要换算成 N·m（见 05 §2）。

对账基准建议分项：侧力/法向力（几何对称敏感）能对到 3~8%，轴向力 14% 左右
（驻点/底部压力梯度被节点平均抹平）。**分部件的滚转/偏航力矩对账可以到 2% 以内**。

## 6. 汇报纪律

- 每个提取结果附带：窗口面积 vs 已知面积、整面对账残差、映射失败数；
- 任何超过对账残差的物理解读都要先过这三关再说。

## 7. 顺带：headless 出图

- 存图必须 `ui_mode="hidden_gui"`（`no_gui` 报 no active graphics window）；
- 图形对象用 `g.contour.create("名")` 创建（下标赋值会 KeyError）；
- 相机 `g.views.camera.target/position(xyz=[...])` 会强制重绘——存图前动一下相机；
- 存完**检查 PNG 文件大小**（约 1.7KB = 纯空白，渲染没跟上，重来）。
