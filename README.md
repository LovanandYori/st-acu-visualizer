# 数据库可视化前端

SillyTavern 的「SP·数据库」可视化前端扩展。在聊天区渲染数据库表格，支持表格浏览、单元格编辑、整体编辑、插入行、删除行、选项面板、仪表盘等功能。**其中单元格/整体编辑、插入行、删除行默认关闭**（在「全能设置 → 表格管理 → 允许手动编辑表格」开启），默认状态下为纯查看。

> 📌 **关于本仓库**：这是 [shuiyue-cmyk/st-acu-visualizer](https://github.com/shuiyue-cmyk/st-acu-visualizer)（维护者 Crino）的 fork。原仓库自 2026-09-07 起不再适配原版 SillyTavern（ST 酒馆），本仓库在它的基础上**继续维护 ST 酒馆这一侧**，并对齐最新的 [AlbusKen/shujuku](https://github.com/AlbusKen/shujuku)（龙血玄黄·数据库）。TT 酒馆的适配代码原样保留，但本仓库没有在 TT 上实测。
>
> 如果你之前用的是「酒馆助手脚本版」可视化前端（JSON 导入的那个），安装本扩展后请在酒馆助手里**关掉旧脚本**，否则会出现两个前端。两者的设置存在同一个位置，原来的设置会直接沿用。

## 安装（无需手动导入 JSON）

1. 打开 SillyTavern
2. 进入 `Extensions`
3. 使用 **「Install extension from Git URL」** 入口
4. 粘贴本仓库地址：
   ```
   https://github.com/LovanandYori/st-acu-visualizer
   ```
5. 安装完成后刷新 SillyTavern

安装后扩展列表中会出现 `数据库可视化前端`。无需手动导入任何 JSON 文件。

## 环境要求

- SillyTavern `1.12.13+`（已在 `1.18.0` 上测试）
- 已安装并启用「SP·数据库」插件（本前端依赖其 `AutoCardUpdaterAPI` / `AutoCardUpdaterV2API` 公共接口）

## 功能

- 聊天区底部渲染数据库全部表格（全局数据表、主角信息表、重要角色表、主角技能表、背包物品表、任务与事件表、纪要表、选项表等）
- 表格分页浏览、搜索、倒序
- 单元格就地编辑 / 整行编辑 / 插入新行 / 多选删除 —— **默认关闭**，需在「全能设置 → 表格管理 → 允许手动编辑表格」开启；关闭时面板仅可查看，前端不会发起任何写库请求（数据库自身填表、追平、正文替换不受影响）
- 选项表 → 「行动选项」面板（默认关闭；点击自动填入输入框）
- 被替换的正文：数据库正文替换成功后，默认在最新一层楼顶部内嵌可收起的原文框（与行动选项同款嵌入），可一键复制替换前原文；设置→正文替换可开关、选仅最新一层或全部楼层、选楼层顶部或底部（选项上方）
- 仪表盘自定义（槽位绑定表格）
- 底部按钮：打开数据库工作台（V2 新 UI）、打开表格编辑器、一键追平所选表未填楼层、全能设置、收起/展开
- 主题：数据库 UI 风格下拉（关闭/苹果/香薰衣草）+ 前端 17 主题（含「透线 · 纯白」「透线 · 纯黑」）；点击兜底保证追平/填表后数据即时可见
- 运行时数据提示：数据库内存态更新（未落盘聊天）时前端 toast 提示，避免误当已保存

## 与数据库版本适配

- **本仓库维护**：SillyTavern（ST 酒馆）+ 数据库 [`AlbusKen/shujuku`](https://github.com/AlbusKen/shujuku)
- **原样保留（未实测）**：TauriTavern（TT 酒馆）`2.3.0` + 数据库 [`shuiyue-cmyk/shujuku-rebuild`](https://github.com/shuiyue-cmyk/shujuku-rebuild)，即原仓库 V17.7.5 时的主基线

**当前版本 V17.7.10 适配 ST 库 `1.2.9`（`e445c96`）；TT 部分沿用 V17.7.5 时的 TT 酒馆 `2.3.0`（`a1855be4`）+ TT 库 `9.10.3`（`93eca17`）。**

> ST 库自 `1.0.0` 起**重置了版本号**（此前为 9.x）并更名，故同一仓出现了两条并行的版本序列。
> 表格里 ST 列写的都是该库**自己 manifest 里的 version**，未做任何换算。

逐版本的变更说明见 [CHANGELOG.md](CHANGELOG.md)。

| 前端版本 | ST 数据库 | TT 数据库（shujuku-rebuild） |
|---|---|---|
| V17.7.6 ~ V17.7.10（本 fork） | 1.2.9（`e445c96`） | 9.10.3（未实测） |
| V17.7.2 ~ V17.7.5 | 1.0.0（`fd91407f`，更名） | 9.10.3 |
| V17.6.10 ~ V17.7.1 | 9.2.5 | 9.10.3 |
| V17.6.5 ~ V17.6.9 | 9.2.5 | 9.6.8 |
| V17.6.4 | 9.2.5 | 9.6.2 |
| V17.5.2 ~ V17.6.3 | 9.2.4 | 9.1.1 |
| V17.5.1 | 9.2.4 | —（尚无 TT 分支） |
| V17.4.8 ~ V17.4.10 | 9.1 | — |
| V17.4.2 ~ V17.4.7 | 9.0 | — |
| V17.3.3 ~ V17.3.6 | 8.9.2 | — |
| V16.4 | 8.9 | — |
| V16.3 | 8.8 | — |
| V16.2 | 8.7.2 | — |
| V15.x | 7.5 ~ 8.1.x | — |

> 数据库更新后即使前端零逻辑改动，也要同步 bump 版本：README 此表加一行（或并入区间），`CHANGELOG.md` 记录核对结论。
> 跨库契约探针：`node tests/run-all.js --db <TT库> --db <ST库>`。

## 维护

- 原作者：夏休期
- 二改：a1185673398
- 三改：星火（已休眠）
- 四改：Crino（原仓库 [shuiyue-cmyk/st-acu-visualizer](https://github.com/shuiyue-cmyk/st-acu-visualizer)，V16.4 ~ V17.7.5）
- 现维护（本 fork，ST 酒馆侧）：LovanandYori
- 思路借鉴：九颜、Zaria

### 测试

零依赖，改完代码跑一下：

```bash
node tests/run-all.js                        # 395 项断言
python tests/sabotage-matrix.py              # 注入矩阵：验证测试本身有效
node tests/run-all.js --db <ST库>              # 附带数据库契约（ST 库 1.2.9 时共 428 项，数据库更新后必跑）
```

另有一份浏览器场景测试（需要 Python + Playwright + Chromium，不是零依赖）：用假的酒馆页面和按数据库 1.2.9 行为写的假数据库，回放自动填表高亮、换聊天、多选删除、空表诊断等 14 个场景：

```bash
python3 -I tests/browser-harness.py index.js   # V17.7.6 应为 26/26
```

所守契约与设计取舍见 [`tests/README.md`](tests/README.md)。
