# 隐私与评估状态

## 数据层级

- `public_summary`：仅聚合，不含身份、行级历史、健康细节或可重识别关联。
- `internal_research`：在记录的同意范围内，仅本地用于建模、验证或审计的化名材料。
- `sensitive_local_only`：直接身份映射、健康/状态细节、原始参与者历史及任何可重识别文件。

身份映射保留在项目私有边界内。不得把 `private/`、`evidence/`、`*.local.json`、参与者清单或真实行级记录复制进 Skill 包。公开案例同意不授权发布行级数据或身份映射。

身份绑定必须使用精确 Runner ID。分别执行参与者记录的用途：公开查询、本地回测、匿名聚合统计和匿名案例使用不可互换。

## 冻结状态

安装包装器执行前核验已审计的本地收尾：

- `validation_decision=retain_distance_only`
- `full_model_status=rejected`
- `retained_reference_model=distance_only`
- `holdout_evaluation_run=false`
- `model_validated=false`
- `user_facing_prediction_allowed=false`

状态缺失或不一致即失败关闭。只有新的具名、哈希绑定审计才可替代该状态；不得编辑打包规则来伪造已验证输出。

除非有独立外部证据，真实现场验证、运动医学审查和公开发布均视为未完成。
