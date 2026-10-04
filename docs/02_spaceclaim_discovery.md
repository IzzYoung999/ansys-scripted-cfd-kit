# 02 SpaceClaim / Discovery 脚本化

Discovery 的隐藏模式可以把你平时在 SpaceClaim 里点的事（旋转、布尔、导出）
全部脚本化，且它的 Parasolid 内核**能吞掉 SolidWorks 交互操作拒绝的零厚度接触**。
这是整条管线选它做几何层的根本原因。

## 1. 启动与日志

```
Discovery.exe --hidden --exit-after-script --run-script your_script.py
```

三个铁律：

1. **print 不落盘。** 隐藏模式没有控制台，print 的内容消失。所有输出必须自己写文件：
   ```python
   f = open(r"D:\work\log.txt", "w")
   def w(s):
       f.write(unicode(s).encode("utf-8") + "\n"); f.flush()
   ```
2. **这是 IronPython 2.7**：`unicode()`、无 f-string、`print` 是语句。
3. 脚本抛异常不会写任何东西到日志——顶层套 `traceback.format_exc()` 落盘。

## 2. 打开文档与枚举实体

```python
File.Open(r"D:\work\model.step")          # 返回 None！不要接返回值
doc  = Window.ActiveWindow.Document       # 用活动窗口拿文档
part = doc.MainPart
bodies = list(part.GetAllBodies())        # 全部实体
```

- **DesignBody 默认是轻量化（lightweight）的**：读 `Volume` 这类标量可以，
  但某些 Shape 级操作会报 "object is deleted"。先 `TryConvertToHeavyweight()`，
  不奏效就直接用标量绕过。
- 实体名来自 STEP 的产品名，含中文/空格/点号很常见。按**子串匹配**定位实体，
  别指望精确名。

## 3. 布尔运算：返回值语义（血泪第一坑）

```python
target.Shape.Unite(tool.Shape)     # 原地并入；返回 None；tool 的 DesignBody 被删除
body.Shape.Subtract(tool.Shape)    # 原地削；返回 None！削完的体就是 body 自己
```

**两个方法都返回 None。** `Subtract` 的结果就是被削的那个体本身——不要去接
"返回的新体"，那会拿到 None 然后把原件删了（实战中丢过一片零件）。

## 4. 脱管副本 vs 设计体（血泪第二坑）

跨体布尔时，两个体必须**同属一类**：

```
ValueError: Some modeler bodies belong to design bodies and some do not.
```

- 想保护一个体不被布尔吃掉 → 用它的**脱管副本**当刀具：
  `tool = body.Shape.Copy()`（完全脱离设计树）。
- 但"设计体 vs 脱管体"混用布尔会被拒。**两边都用脱管副本**，算完再回填设计树：
  ```python
  from SpaceClaim.Api.V252 import DesignBody
  rc = rudder_shape.Copy()        # 脱管
  rc.Subtract(tool_copy)          # 原地削，rc 即结果
  rudder.Delete()
  DesignBody.Create(part, rudder.Name, rc)
  ```

## 5. 刚体变换（旋转可动件）

变换矩阵类不在你猜的地方：

- 类名：`SpaceClaim.Api.V252.Geometry.Matrix`（不在顶层，也不在 Modeler 里）。
- 旋转工厂：`Matrix.CreateRotation(Line, radians)`——**绕一条线**旋转。
- 使用：
  ```python
  from SpaceClaim.Api.V252.Geometry import Matrix, Line, Point, Direction
  line = Line.Create(Point.Create(px, py, pz), Direction.Create(ax, ay, az))
  m = Matrix.CreateRotation(line, math.radians(delta))
  design_body.Transform(m)          # DesignBody 有 .Transform 实例方法
  ```

**找不到 API 类名时的正规姿势**：用 `clr.GetClrType(某类型)` 反射方法签名拿
参数的 FullName——几秒钟。**不要**用 `AppDomain.CurrentDomain.GetAssemblies()`
+ `GetTypes()` 全库扫——在 IronPython 里会挂死几分钟到永远。

## 6. 导出

```python
eo = ExportOptions.Create()
eo.CleanUpBodies = False
eo.ExportNames = True                      # 保留实体名 → 下游 zone 名可读
Window.ActiveWindow.Export(WindowExportFormat.DISCO, out_path, eo)
```

- `doc.SaveAs("xxx.step")` 在隐藏模式会**挂死**（对话框），永远走 Export。
- Watertight 工作流**只认 `.dsco`**，FMD/ANF 都不收（别信老教程）。

## 7. 检查清单（每个几何脚本跑完必看）

- [ ] 布尔后 `GetAllBodies()` 数量 == 预期（本体+外流盒 = 2）
- [ ] 刚体变换前后 `Volume` 不变
- [ ] 每个导出文件大小在同一量级（突然小一半=丢东西）
- [ ] 日志里无 Traceback

## 8. 已知死路（别撞）

- `AppDomain` 全程序集反射 → 挂死。
- 在隐藏模式里弹任何模态对话框的操作（SaveAs、某些修复工具）→ 挂死。
- 让 Discovery 在隐藏模式打开带特征的 .sldprt 装配 → 依赖源文件在不在磁盘，
  不可靠；用 STEP 中转。
