# W2：训练特征与 readiness 只读接口

`wearable_ingest.features.build_feature_summary` 只接收已规范化的活动聚合 JSON；它不会读取 FIT、私密目录、轨迹点、秒级心率、wellness 或账号数据。

摘要按生成时的 `as_of_date` 计算最近 7、28、84 天的距离、时长与爬升，以及最长单次、7:28 与 28:84 距离负荷比、最近 84 天每周的 20km 以上活动频率、截至当日连续训练日与最近 28 天无训练日比例。任一窗口的一个活动缺少该指标时，该指标总量写为 `null`；覆盖率和不确定性会明确反映缺失，绝不以零或估值补造。

每个摘要都保留仅限非识别性 `activity_id`、`import_request_id` 与活动日期的来源链。`runner_readiness build --wearable-feature-summary <summary.json>` 会验证此合同及两项治理锁，然后只在 `current_readiness.wearable_training_exposure` 中显示训练暴露上下文。它不改写手工自报、健康/红旗字段、风险级别、计划权限或任何预测治理状态；不传该参数时既有输出不增加该字段。
