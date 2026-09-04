import unittest

from report_workflow.pipeline import _report_text_errors


def _valid_report() -> str:
    return """# 比赛策略与情景规划

## 一、结论
## 二、证据
## 三、状态
## 四、边界
## 五、建议
## 六、CP 总览与逐段战术详解
### 6.1 全段总览表
| # | 赛段区间 | km | 爬升 | 下降 | 本段耗时 | 到站停留 | 出站用时 | 累计用时 | 到达时间 | 离站时间 | 关门时间 | 余量 | 赛道难度 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 起点 → CP1 | 10 | 500 | 300 | 1:20 | 0:05 | 1:25 | 1:20 | 09:20 | 09:25 | 12:00 | 2:40 | 中 |
> **总计：** 10 km / D+ 500 m / D− 300 m / 纯跑约 1:20 / 站停约 0:05 / 条件式完成 09:20

### 6.2 逐段战术详解
#### S0 · 起点 → CP1
| 维度 | 内容 |
|---|---|
| 数据边界 | 当年官方 |
| 距离与升降 | 10 km / +500 / -300 |
| 条件式窗口 | 到站 09:20；停留 5 min；离站 09:25 |
| 赛道特征 | 山地 |
| 风险 | 下坡 |
| 行动策略 | 稳定推进 |
| 补给/装备 | 已验证补给 |
| 关门边界 | 12:00；余量 2:40 |

### 6.3 全程执行总则
## 七、情景切换
## 八、来源
"""


class ReportDeliveryContractTests(unittest.TestCase):
    def test_accepts_complete_cp_delivery_shape(self):
        self.assertEqual(_report_text_errors(_valid_report(), artifact="valid.md"), [])

    def test_rejects_missing_time_budget_and_total(self):
        invalid = _valid_report().replace("| 1:20 | 0:05 | 1:25 | 1:20 | 09:20 | 09:25 |", "| 待补充 | 0:05 | 1:25 | 1:20 | 09:20 | 09:25 |").replace("> **总计：** 10 km / D+ 500 m / D− 300 m / 纯跑约 1:20 / 站停约 0:05 / 条件式完成 09:20\n", "")
        errors = _report_text_errors(invalid, artifact="invalid.md")
        self.assertIn("FINAL_CP_TIME_BUDGET_INCOMPLETE:invalid.md", errors)
        self.assertIn("FINAL_CP_OVERVIEW_TOTAL_MISSING:invalid.md", errors)

    def test_rejects_incomplete_segment_card(self):
        invalid = _valid_report().replace("| 补给/装备 | 已验证补给 |\n", "")
        self.assertIn("FINAL_SEGMENT_TACTICS_CARD_INCOMPLETE:invalid.md", _report_text_errors(invalid, artifact="invalid.md"))

    def test_rejects_missing_segment_card(self):
        invalid = _valid_report().replace("#### S0 · 起点 → CP1\n", "")
        self.assertIn("FINAL_SEGMENT_TACTICS_EMPTY:invalid.md", _report_text_errors(invalid, artifact="invalid.md"))
