# 越野赛策略报告 · 渲染风格契约（style-spec）

> 本文件是「视觉风格的唯一事实来源」。它与 `trail-race-strategist` skill **解耦**：
> skill 只负责产出符合结构的 Markdown 内容；本契约 + 同目录的 `report.css` /
> `pdf_style.py` / `build_report.py` 只负责把 Markdown 渲染成**固定风格**的 HTML 与 PDF。
> 其他智能体/模型执行 skill 后得到 Markdown，再调用本包即可输出同风格成品。
>
> **本目录刻意不放 `SKILL.md`**，因此不会被 WorkBuddy 注册为 skill，也不会改动任何原 skill 文件。

---

## 0. 设计原则

- **内容 / 渲染分离**：风格包不规定文章内容，只规定视觉。文章板块顺序、措辞由 skill 决定。
- **单一事实来源**：所有颜色、字号、字体只在本契约 + `report.css` + `pdf_style.py` 三处定义，三者必须保持同步。
- **红点强制**：所有列表（有序/无序）在 PDF 中统一渲染为红色圆点 `•`，**禁止使用数字自动编号**（reportlab 多条目下编号会失效、全部显示"1"）。
- **HTML = 原生编号**：HTML 版本保留 Markdown 原生 `1. 2. 3.` 与 `-` 渲染（已确认无误），不与 PDF 强求一致。
- **CP 总览表全列渲染**：PDF 与 HTML 必须渲染 MD 表格的**全部列**，不得做列投影/裁剪。

---

## 1. 配色变量（CSS `:root` 与 reportlab 常量一一对应）

| 语义 | CSS 变量 | 值 | reportlab 常量 | 用途 |
|---|---|---|---|---|
| 正文墨色 | `--ink` | `#1f2933` | `INK` | 正文/段落 |
| 次要文字 | `--muted` | `#52606d` | `MUTED` | 元信息/副标题 |
| 分隔线 | `--line` | `#d9e2ec` | `LINE` | 表格边框、HR、标题下边框底 |
| 强调红 | `--accent` | `#b91c1c` | `ACCENT` | H1 底部红边、H2 左侧红边、列表红点 |
| 页面背景 | `--bg` | `#f8fafc` | — | HTML body 背景 |
| 标题深蓝 | — | `#0b1f33` | `TITLE_C` | H1/H2 文字 |
| 三级标题 | — | `#102a43` | `H3_C` | H3 文字、表头文字 |
| 四级标题 | — | `#243b53` | `H4_C` | H4 文字 |
| 引用文字 | — | `#7c2d12` | `QUOTE_C` | blockquote 文字 |
| 代码文字 | — | `#e2e8f0` | `CODE_C` | PDF 代码块文字（深色底） |
| 表头底 | — | `#eef2f7` | `TH_BG` | 表头背景 |
| 斑马纹 | — | `#fbfcfe` | `ZEBRA` | 表格偶数行背景 |

**引用块（HTML）**：背景 `#fff7ed`，左边 4px `#f59e0b`（橙），文字 `#7c2d12`。
**提示块 `.tip`（HTML）**：背景 `#f0fdf4`，边框 `#86efac`，文字 `#14532d`。

---

## 2. 字体

- **HTML**：`"Microsoft YaHei","PingFang SC","Hiragino Sans GB","Source Han Sans SC","Noto Sans CJK SC",sans-serif`
- **PDF**：按优先级注册系统 CJK 字体
  - 常规：`C:/Windows/Fonts/msyh.ttc`（subfontIndex 0）→ `simhei.ttf` → `simsun.ttc`
  - 粗体：`C:/Windows/Fonts/msyhbd.ttc`
  - 兜底：reportlab 内置 `STSong-Light`（CID 字体，免下载）
- **字号基准**：正文 15px（HTML）/ 9.3pt（PDF）；行高 1.7（HTML）/ `size*1.45`（PDF leading）。

---

## 3. 标题层级（HTML / PDF 对应）

| 层级 | HTML | PDF 字号/颜色 | 装饰 |
|---|---|---|---|
| H1（`# `） | 25px / `#0b1f33`，底部 3px 红边 | 15pt bold / `#0b1f33`，space_before 12 | 红色下边框 |
| H2（`## `） | 20px / `#0b1f33`，左侧 5px 红边 + padding-left 12px | 12.5pt bold / `#0b1f33`，space_before 10 | 红色左边框 |
| H3（`### `） | 17px / `#102a43` | 11pt bold / `#102a43`，space_before 8 | 无 |
| H4（`#### `） | 15px / `#243b53` | （并入 BODY，不单独定义） | 无 |
| 正文 | 15px / `#1f2933` | 9.3pt / `#1f2933` | — |
| 引用 | blockquote 样式 | 9pt / `#7c2d12` | 橙左边框 |
| 代码 | `pre` 深色 `#0f172a` | 7.6pt / `#e2e8f0` | 深色底 |

---

## 4. 表格

- 边框：`1px solid #d9e2ec`（HTML）/ `0.4pt #d9e2ec`（PDF）
- 表头：背景 `#eef2f7`，文字 `#102a43`，粗体
- 斑马纹：偶数行 `#fbfcfe`（HTML `tr:nth-child(even)`；PDF `ROWBACKGROUNDS`）
- 单元格内边距：HTML `7px 9px`；PDF `2pt`（紧凑，装得下宽表）
- **CP 总览表**：因列多（15 列），PDF 用 5.6pt 小字（`S_CELL_SM`）渲染，HTML 用 13px；两端均渲染**全部列**。
- 表格在 PDF 中 `repeatRows=1`（跨页重复表头）。

---

## 5. 列表（红点强制）

- **PDF 全部列表统一**：`bulletType="bullet"`, `start="•"`, `bulletColor="#b91c1c"`，`bulletFontName=正文字体`。
- **禁止**在 PDF 中使用 `bulletType="1"` 数字编号（已知 bug：多条目下全显示"1"）。
- HTML 保留 Markdown 原生编号/圆点，不做干预。

---

## 6. 渲染处理规则（Markdown → 元素映射）

| Markdown | HTML | PDF flowable |
|---|---|---|
| `# ` / `## ` / `### ` | h1/h2/h3 | H1/H2/H3 段落 |
| `> ` 连续 | blockquote | QUOTE 段落 |
| `---` | `<hr>` | HRFlowable |
| `\|` 表格 | `<table>` | parse_table（全列） |
| `- ` / `* ` | `<ul>` | 红点列表 |
| `1. ` 有序 | `<ol>` | 红点列表（PDF 不显示数字） |
| ```` ``` ```` 代码块 | `<pre>` | Preformatted |
| 连续普通行 | `<p>` | 合并段落 |
| `**粗**` | `<strong>` | `<b>` |
| `[文本](链接)` | 链接 | 去链接保留文本 |

---

## 7. 报告预期板块顺序（内容层约定，供一致性参考）

风格包不强制内容，但建议 skill 产出遵循以下顺序，便于读者与跨模型一致：

1. **结论与验证边界**（H1）
2. **赛事事实捕获回执**（七通道，H1）
3. **跑者档案与当前状态边界**（H1）
4. **预测基线计算（distance_only）**（H1）
5. **情景预测（研究用）**（H1）
6. **备赛训练计划**（H1）
7. **比赛策略与 CP 总览**（H1）
   - 全段总览表
   - 逐段战术详解
   - 情境切换 / 红旗停赛
8. **来源、隐私与技术附录**（H1：输出契约 JSON、evidence 清单、修订记录）

---

## 8. 文件职责

| 文件 | 职责 |
|---|---|
| `style-spec.md` | 本契约（人/模型可读的风格事实来源） |
| `report.css` | HTML 完整样式（从本契约导出，被 `build_report.py` 读取） |
| `pdf_style.py` | reportlab 字体注册 + 样式常量 + 表格/列表/解析函数 + `build_pdf()` |
| `build_report.py` | CLI 入口：读任意 Markdown → 输出同风格 HTML + PDF |
| `README.md` | 给其他模型/使用者的操作说明 |
