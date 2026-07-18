# 工作流路由

在 Skill 目录运行 `python scripts/run_workflow.py`；产生写入前先用 `--dry-run`。输出和证据路径必须在 `E:`。

| 请求 | 工作流 | 项目模块 | 关键输入 |
|---|---|---|---|
| 新用户完整报告 | `report request` → 证据抓取 → `report finalize` | `report_workflow.cli` + 智能体公开搜索 | 仅请求者姓名、精确 Runner ID、目标赛事 |
| ITRA 公开历史 | `runner` | `itra_public_runner.cli` | 精确姓名、Runner ID、已保存 HTML 或显式实时证据目录 |
| 赛事证据 | `race` | `race_sources.cli` | 目标年份+精确组别、官方/补充 URL、时间戳抓取回执 |
| 赛道/CP 模型 | `course` | `course_model.cli` | 赛事来源包 |
| 状态评估 | `readiness` | `runner_readiness.cli` | 跑者档案和问答 |
| 距离研究基线 | `baseline` | `baseline_prediction.cli` | 档案、状态、赛道模型 |
| 参考研究候选 | `reference` | `reference_model.cli` | 批准的离线图输入 |
| 比赛策略 | `strategy` | `race_strategy.cli` | 含目标组别抓取回执的赛道、状态、距离基线 |
| 补给/装备/支持 | `support` | `race_support.cli` | 比赛计划、赛道、显式支持输入、可选天气 |
| 天气情景 | `weather` | `weather_scenario.cli` | 赛事、时间戳观测、截至时间 |
| CP 重规划 | `live` | `live_replanning.cli` | 比赛计划、时间戳事件、截至时间与回放背景 |
| 赛后复盘 | `retro` | `post_race.cli` | 计划、实际结果、条件、同意、可选既有模型 |

示例：

```powershell
python scripts/run_workflow.py status
python scripts/run_workflow.py runner replay --profile-html E:\inputs\profile.html --name "NAME" --runner-id "123" --output E:\outputs\runner.json
python scripts/run_workflow.py course replay --bundle E:\inputs\race_source_bundle.json --output E:\outputs\course_model.json
python scripts/run_workflow.py strategy --course-model E:\inputs\course_model.json --readiness E:\inputs\current_readiness.json --distance-only-baseline E:\inputs\baseline.json --output-dir E:\outputs\strategy-run
python scripts/run_workflow.py live --race-plan E:\inputs\race_plan.json --events E:\inputs\events.json --as-of 2026-11-07T15:00:00+08:00 --validation-context historical_replay --output-dir E:\outputs\live-run
```

通过装器的模块 `--help` 查看精确参数；不得利用本装器重开 Phase 8A 评估、暴露私有数据或绕过冻结状态。

新请求：

```powershell
python scripts/run_workflow.py report request --name "NAME" --runner-id "123" --target-event "2026 Event 100km" --output-root E:\trail-race-requests
```

该命令建立不可变请求边界并写入 `workflow_status=in_progress`，本身不是完成报告。智能体必须在同一任务继续：新鲜 ITRA 抓取、目标组别解析、全部必需公开搜索通道、附件获取/视觉解析，以及请求范围的赛事包构建；URL 和文件由智能体内部获取，不是请求者输入。

在同一外层请求中抓取跑者（不得调用会生成第二个 request ID 的独立 runner `request`）：

```powershell
python scripts/run_workflow.py report runner-live --request-dir E:\trail-race-requests\req-...
```

ITRA 受阻只记录请求范围回执，不停止赛事来源搜索。`race/search_receipt.json` 与 `race/race_source_bundle.json` 就绪后运行：

```powershell
python scripts/run_workflow.py report finalize --request-dir E:\trail-race-requests\req-...
```

`report finalize` 仅在目标年份/精确组别 CP 证据门槛通过时构建完整策略。它会在搜索通道缺失、附件待处理、CP 仅起终点、请求 ID 不匹配、CP 表为空或报告缺少 6.1/6.2 时失败关闭。资料不足时生成准备确认单而非终结产物；通过 `report status --request-dir ...` 检查，仅 `terminal_report_allowed=true` 表示完成。

策略前必须抓取并绑定目标**年份和组别**：官方赛事/组别页、路线/路书/GPX、CP/关门表、报名/规则和最新通知。逐一记录 URL、抓取时间、抓取状态及适用组别。CP、分段、关门、爬升缺失绝不是停止搜索的理由；只有抓取回执存在后可标为 `checked_not_confirmed`。`officially_not_published` 仅在同年同组官方通知明确未发布时可用，否则安排重抓取并保持未核验。

`checked_not_confirmed` 表示字节已获取并解析但适用性仍未解决或来源冲突；发现未获取、已获取未解析附件是带精确错误码的硬不完整状态。

所有 Markdown/JSON 工作流输出都必须应用 [output-contract.md](output-contract.md)：使用匹配报告类型、隐私安全中文普通层和技术附录。
