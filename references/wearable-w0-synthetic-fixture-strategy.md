# W0 合成 fixture 策略

W0 不创建 FIT fixture，也不读取任何真实活动文件。W1 之前只测试 JSON schema 的结构和禁止字段。

W1 仅可新增完全合成或明确允许公开再分发的 fixture，并在文件旁标注来源、许可证和 `synthetic=true`。禁止从真实用户活动去标识化后充当测试样本。

W1 的最小场景：

- 可解析的合成活动；
- 损坏文件、重复文件、缺失 GPS、缺失心率、时区/日期边界；
- 未经授权的 wellness 字段和凭据字段必须 fail-closed；
- request_id 删除演练；
- 无任何预测字段、无真实姓名、无外部账号 ID、无真实轨迹和秒级心率序列。

合成 fixture 必须留在版本控制中；`.gitignore` 只忽略真实 FIT 和私密运行目录，不能忽略 `tests/fixtures/` 下的合成样本。
