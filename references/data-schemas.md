# 数据 Schema

以版本化 JSON 作为权威机器可读输出，至少包含：

- `schema_name`、`schema_version`、`generated_at`、`generator_version`
- `safety_notice`
- 来源/证据引用
- 适用时的诊断、警告和验证背景

使用语义版本：重大含义变更为 major，新增兼容内容为 minor，不破坏兼容的修复为 patch。一个 major 内不得静默改名或删除字段。

已知缺失值使用 `null`，另给出明确的缺失/不可用列表和机器可读的部分原因。受阻、锁定、过期、有歧义或不可用的值绝不可用估计替代。

官方事实、模型估计与建议必须放在不同字段或清晰分隔的章节。每项估计保留输入引用、公式/规则、假设、置信度与验证背景。

每个面向用户的产物都必须包含等效声明：

```json
{
  "version": "1.0.0",
  "medical_advice": false,
  "replaces_race_rules": false,
  "message": "This tool does not replace race rules, on-site safety, or professional medical judgment."
}
```

使用稳定数据族名称，如 `runner_profile`、`race_source_bundle`、`course_model`、`current_readiness`、`baseline_candidate_ranges`、`race_plan`、`race_support_plan`、`weather_scenarios`、`live_replanning_snapshot` 与 `race_retro`。

正式报告产物还须应用 [output-contract.md](output-contract.md)。契约 `2.0.0` 为增量式：保留既有字段，并在顶层加入契约封套。

## 目标组别抓取回执

供 `race_strategy` 使用的每个 `course_model` 都必须包含 `event.target_group_capture`：`capture_attempt_status`、`captured_at`、赛事/年份/组别身份绑定、官方来源计数、`detail_checks`、发布结论与下一动作。策略拒绝缺失、不完整或绑定不一致的回执。

仅当抓取到的目标组别来源含有该字段时，`detail_checks.<field>.status` 才能是 `verified`；否则为 `checked_not_confirmed`。只有另行抓取、且绑定同年同组的官方通知明确表示未发布时，才能用 `officially_not_published`；抓取中未看到该字段不是充分证据。

回执 `2.0.0` 记录 `request_id`、必需/已尝试/缺失搜索通道、每个 URL 与来源类型、抓取时间、HTTP/错误状态、原始路径、SHA-256、解析状态、附件状态、适用年份/组别、来源层级及自动下一动作。`capture_attempt_status=completed` 要求全部通道已尝试，且没有发现附件仍未获取或未解析。

仅当字节已获取并解析、但目标年份/组别适用性未解决或来源冲突时使用 `checked_not_confirmed`；其他情况使用 `attachment_not_acquired`、`attachment_parse_failed`、`source_blocked` 或具体 HTTP/TLS 错误。

CP 行携带 `evidence_tier`、`source_year`、`applicable_year`、`applicable_group`、`route_version` 和 `current_year_applicability`。允许层级为 `current_year_official`、`official_historical_reference`、`third_party_cross_check` 与 `derived`。历史行绝不可为目标年份设置 `officially_confirmed=true`。
