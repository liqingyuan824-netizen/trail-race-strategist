# W0–W3 可穿戴受限备赛功能操作指南

## 这项功能能做什么

本功能在本机、经同意的前提下，把跑步／越野跑活动整理为训练暴露摘要，并将该摘要以**只读上下文**接入 `runner_readiness`。当目标年份、精确组别的官方赛道与 CP 证据已经通过既有门槛时，W3 可给出保守、条件式的备赛提示：训练重点、负荷调整、长距离／爬升演练、补给演练、减量时机，或数据不足说明。

它不是医疗工具、赛道资料替代品或成绩预测器。

## 不可改变的边界

- 仅在用户指定的 **E: 私密目录**保存原始、规范化和派生可穿戴数据；不得放入工作区、Skill 包、fixture、公开导出或报告附件。
- 每次导入前必须有对应参与者、日期范围和设备品牌的不可变同意回执；没有回执时不导入。
- 仅处理获授权的跑步／越野跑活动。不得读取或导出 wellness、睡眠、压力、HRV、账户、Cookie、密码、OAuth token、设备序列号、精细 GPS 或秒级心率。
- 可穿戴摘要保持只读、可追溯，不能覆盖自报信息、红旗、风险等级或 `planning_permission`；它只能收紧计划或说明不确定性。
- 无摘要、摘要覆盖不完整或不确定性较高时，流程正常降级为保守建议，而不是补造数据。
- 预测锁始终保持：`validation_decision=retain_distance_only`、`model_validated=false`、`user_facing_prediction_allowed=false`。不生成个人完赛时间、概率、配速、CP 到离站预算或分段策略。

## 最小操作流程

### 1. 先签同意，再在私密目录操作

让参与者确认允许范围后，由本地操作者签发 W1 同意回执。以下均为占位符，必须替换为用户指定的 E: 私密位置和新建请求标识；不要使用旧请求或示例中的值。

```powershell
python -m wearable_ingest issue-consent `
  --request-id <new-request-id> `
  --private-alias <private-alias> `
  --consented-at <UTC-timestamp> `
  --allowed-start-date <YYYY-MM-DD> `
  --allowed-end-date <YYYY-MM-DD> `
  --consent-root <E-private-consent-root> `
  --source-brand <garmin-or-coros>
```

真实数据操作前，先在执行记录中说明本次 E: 私密目标目录。回执签发本身不读取活动文件。

### 2. 先 dry-run，再导入获授权活动

单个 FIT 文件：

```powershell
python -m wearable_ingest ingest `
  --source <E-private-source.fit> `
  --private-root <E-private-data-root> `
  --consent-file <E-private-consent-receipt.json> `
  --dry-run
```

确认 dry-run 的日期范围、同意回执和重复检查均通过后，去掉 `--dry-run` 执行正式导入。多个已经单独确认的文件可使用 `ingest-batch`；仍须传入同一参与者、同一授权范围对应的私密同意回执。

```powershell
python -m wearable_ingest ingest-batch `
  --source-dir <E-private-authorized-fit-directory> `
  --private-root <E-private-data-root> `
  --consent-file <E-private-consent-receipt.json> `
  --dry-run
```

不把真实 FIT 当测试样本，也不把任何导入产物复制到项目目录。

### 3. 生成并保存 W2 训练摘要

由受控 W2 流程从已导入的私密规范化活动生成 `wearable_feature_summary`。该摘要只包含 7／28／84 天训练暴露、质量、不确定性及最小来源链；不得手工编辑、拼接或移入工作区。生成后的摘要继续留在用户指定的 E: 私密目录。

### 4. 构建 readiness（可选接入摘要）

先收集既有 readiness 的 profile 与自报 answers。两者也应位于本次用户指定的 E: 私密工作目录。带摘要的调用如下：

```powershell
python -m runner_readiness build `
  --profile <E-private-profile.json> `
  --answers <E-private-answers.json> `
  --wearable-feature-summary <E-private-wearable-feature-summary.json> `
  --output-dir <E-private-readiness-output-directory>
```

没有可穿戴摘要时，省略 `--wearable-feature-summary`。这会生成普通 readiness 输出，不会报错，也不会假设训练中断或健康状况。

### 5. 使用 W3 条件式备赛建议

W3 仅在以下前提同时成立时可生成建议：

1. `current_readiness` 已完成，且风险等级、红旗和 `planning_permission` 已核验；
2. 目标年份、精确组别已绑定；
3. 当前请求内已有通过持久化审阅的官方赛道／CP 证据；
4. 证据门槛没有失败码。

输出是本地 JSON `training_preparation_advice`，不是 HTML/PDF 策略报告。它只能给条件式、需复核的训练准备提示；不会抄写活动清单、训练负荷明细、赛道 CP、补给站或时间预算。

若赛道证据未通过，W3 fail-closed，不给五类训练建议；若存在红旗或 `stop_and_seek_professional_assessment`，建议数组为空，停止调整强度并寻求专业评估。可穿戴摘要再完整也不能解除这些限制。

## 删除与撤回

参与者撤回时，按其导入请求标识在同一 E: 私密根目录执行受控删除：

```powershell
python -m wearable_ingest delete `
  --request-id <existing-private-request-id> `
  --private-root <E-private-data-root>
```

删除操作只针对明确、已核验的私密请求；不删除工作区、Skill 包或其他参与者的目录。执行后保留受控删除回执，不重新利用被撤回数据生成摘要或建议。

## 操作前后核对清单

- 操作前：确认新请求、同意回执、授权日期、设备品牌和 E: 私密目标目录。
- 导入后：确认去重、来源链、质量与不确定性均已记录；不公开原始或派生数据。
- readiness 后：确认自报与红旗优先，摘要没有修改风险等级或计划权限。
- W3 前：确认目标年份、精确组别及持久化官方 CP 证据门槛通过。
- 输出前：确认不含个人预测、医疗判断、CP 时间、配速、原始活动标识、路径或敏感字段。

## 验证命令

仅用合成 fixture 运行专项与全量测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_wearable_w2_features.py tests/test_phase6a_runner_readiness.py tests/test_w3_restricted_preparation_advice.py tests/test_phase14_skill_wrapper.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

通过测试表示合同与封装一致；不表示模型已验证，也不改变任何预测锁。
