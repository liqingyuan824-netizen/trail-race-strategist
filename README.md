# Trail Race Strategist / 越野赛策略助手

[English](#english) | [中文](#中文)

## 中文

### 简介

`trail-race-strategist` 是一个基于证据的越野赛规划与复盘 Skill。它围绕公开 ITRA 跑者资料和官方赛事资料，支持赛道与 CP（检查点）建模、跑者状态评估、补给与天气情景、赛中重规划及赛后复盘。

它强调可追溯性：事实、估算和建议会被区分标注；未知信息保持为未知，不会被经验推断伪装成官方事实。

### 适用场景

- 核验跑者的公开 ITRA 资料（需要精确 Runner ID）
- 采集并核对官方赛事、组别、路线、CP、补给和关门资料
- 基于已核验资料生成赛前策略、补给/天气情景和赛中调整建议
- 进行赛后复盘与资料留档

### 使用前须知

- 正式 CP 到离站预算和逐段策略报告，默认需要目标年份、精确组别的官方 CP 证据。
- 如完整检索后没有当年 CP 详情，但已有同赛事同组别的官方历史路线资料，必须先由用户明确同意，才可生成带有“历史路线参考版”标识的报告；其中 CP、补给和关门并非当年已确认信息，赛前仍必须以当年官方公告复核。
- 缺少关键证据时，Skill 只会输出待补全确认单，不会虚构 CP、关门、健康结论或完赛预测。
- 这是规划辅助工具，不替代赛事规则、医疗建议、救援人员决定或个人风险判断。

### 安装与运行

1. 下载 ZIP，或克隆仓库：

   ```powershell
   git clone https://github.com/liqingyuan824-netizen/trail-race-strategist.git
   cd trail-race-strategist
   ```

2. 在支持 Skills 的 Codex 环境中，将本目录作为一个 Skill 安装或引用；随后可通过 `$trail-race-strategist` 调用。

3. 在本目录初始化独立运行环境：

   ```powershell
   python scripts/run_workflow.py bootstrap
   python scripts/run_workflow.py status
   ```

   `bootstrap` 会在 Skill 内创建 `.venv` 并安装 `requirements.txt` 中的依赖。若网页抓取提示缺少浏览器，可在该虚拟环境中安装 Playwright Chromium：

   ```powershell
   .\.venv\Scripts\python -m playwright install chromium
   ```

4. 查看可用工作流：

   ```powershell
   python scripts/run_workflow.py --list
   ```

### 推荐的首次请求

请提供：跑者姓名、精确 ITRA Runner ID、目标赛事（含年份和组别）。例如：

> 为“姓名”、ITRA Runner ID “1234567”准备“2026 年某赛事 50K 组”的赛前策略。请从公开与官方来源采集资料，并明确标注尚未确认的信息。

### 隐私与数据边界

公开 ITRA 页面不等于允许公开个人身份或逐场历史。请只处理获得授权的资料；不要将身份映射、健康细节、私有原始历史或本地专用文件提交到公开仓库。

### 许可证

本项目采用 [MIT License](LICENSE)。

---

## English

### Overview

`trail-race-strategist` is an evidence-bound Skill for trail-race planning and review. It works with public ITRA runner information and official race sources to support course and checkpoint (CP) modeling, runner-readiness review, nutrition and weather scenarios, live replanning, and post-race review.

Traceability is a core principle: facts, estimates, and advice are labeled separately. Unknowns remain unknown; they are never presented as official facts through guesswork.

### What it supports

- Verifying public ITRA runner information with an exact Runner ID
- Capturing and checking official race, category, route, CP, aid-station, and cutoff information
- Producing evidence-bound pre-race strategy, nutrition/weather scenarios, and live adjustment guidance
- Conducting post-race review and preserving auditable records

### Important limits

- Formal CP arrival/departure budgets and segment-by-segment strategy reports normally require official CP evidence for the target year and exact category.
- If a complete search finds no current-year CP details but official historical route material exists for the same event and category, the user must explicitly consent before a clearly labeled “historical route reference” report can be produced. Its CP, aid, and cutoff information are not confirmed for the current year and must be checked against the current official notice before race day.
- When critical evidence is missing, the Skill produces a checklist for missing information rather than inventing CPs, cutoffs, health conclusions, or finish-time predictions.
- This is a planning aid. It does not replace race rules, medical advice, rescue personnel decisions, or personal risk judgment.

### Installation and local runtime

1. Download the ZIP archive or clone this repository:

   ```powershell
   git clone https://github.com/liqingyuan824-netizen/trail-race-strategist.git
   cd trail-race-strategist
   ```

2. Install or reference this directory as a Skill in a Codex environment that supports Skills. Invoke it with `$trail-race-strategist`.

3. Initialize its self-contained runtime:

   ```powershell
   python scripts/run_workflow.py bootstrap
   python scripts/run_workflow.py status
   ```

   `bootstrap` creates a local `.venv` inside the Skill and installs the dependencies in `requirements.txt`. If a web-capture task reports that browser binaries are missing, install Playwright Chromium in that environment:

   ```powershell
   .\.venv\Scripts\python -m playwright install chromium
   ```

4. List available workflows:

   ```powershell
   python scripts/run_workflow.py --list
   ```

### Suggested first request

Provide the runner name, exact ITRA Runner ID, and target event including year and category. For example:

> Prepare a pre-race strategy for “Runner Name,” ITRA Runner ID “1234567,” for the 2026 Example Race 50K category. Gather public and official sources and explicitly label anything that remains unconfirmed.

### Privacy and data boundary

A public ITRA page is not permission to publish a person's identity or race-by-race history. Process authorized data only, and never commit identity mappings, health details, private raw histories, or machine-local files to a public repository.

### License

This project is released under the [MIT License](LICENSE).

---

## Report rendering / 报告渲染

This repository includes a fixed-style renderer in [`rendering/`](rendering/) for the final Markdown report. It produces matching HTML and PDF output without relying on a machine-specific renderer path.

本仓库在 [`rendering/`](rendering/) 内自带固定风格渲染器，可将最终 Markdown 报告生成风格一致的 HTML 和 PDF，不依赖任何本机专属路径。

Only render after the report workflow has completed and reports `terminal_report_allowed=true`. Rendering must never bypass missing CP evidence or other workflow gates.

仅当报告工作流完成且显示 `terminal_report_allowed=true` 后才可渲染；渲染不能绕过 CP 证据缺失或其他工作流门槛。

```powershell
python rendering/build_report.py 路径\最终报告.md --out-dir E:\输出目录
```

The command generates a same-named `.html` file and `.pdf` file. Keep `style-spec.md`, `report.css`, and `pdf_style.py` synchronized whenever the visual style is changed.

命令会生成同名 `.html` 与 `.pdf` 文件。修改视觉风格时，必须同步维护 `style-spec.md`、`report.css` 和 `pdf_style.py`。
