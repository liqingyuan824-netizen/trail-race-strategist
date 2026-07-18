"""Runner-facing strategy report with complete CP and segment chapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from reporting_contract import technical_appendix


_NAMES = {"safe_finish": "安全完成", "stable": "稳定执行", "aggressive": "条件式积极"}
_RISK_NAMES = {"green": "绿色（可常规规划）", "yellow": "黄色（保守规划）", "red": "红色（停止成绩目标）"}
_MODE_NAMES = {
    "current_year_official": "当年官方资料已核验",
    "historical_route_reference": "官方历史路线参考",
    "nonofficial_execution_budget": "参考执行预算（非官方）",
    "insufficient_evidence": "资料不足，不提供时间预算",
    "not_allowed": "当前不提供",
}
_CAPTURE_STATUS_NAMES = {
    "completed": "已完成",
    "completed_with_failures": "已完成，部分来源受阻",
    "incomplete": "尚未完成",
    "not_completed": "尚未完成",
}
_APPLICABILITY_NAMES = {
    "confirmed": "已确认适用于目标年份",
    "reference_only_unconfirmed": "仅作历史参考，目标年适用性待确认",
    "unconfirmed": "目标年适用性待确认",
}
_SEARCH_LANE_NAMES = {
    "official_event_or_regulation": "官方赛事或规程",
    "official_registration_or_group_page": "官方报名或组别页",
    "route_roadbook_gpx_or_attachment": "路线、路书、GPX 或附件",
    "cp_aid_cutoff_material": "CP、补给或关门材料",
    "official_notice_or_social": "官方通知或社媒",
    "timing_or_tracking": "计时或追踪",
    "historical_route_and_results": "历史路线或成绩",
}


def _value(value: Any, unknown: str = "未知") -> str:
    return unknown if value in (None, "", []) else str(value)


def _display_time(plan: Mapping[str, Any]) -> bool:
    """Show an execution budget even when official cutoff proof is pending.

    The report labels such values as non-official. A red safety stop remains
    the only reason to suppress pacing targets.
    """
    safety = plan.get("facts", {}).get("readiness_safety_cap", {})
    if safety.get("risk_level") == "red" or safety.get("planning_permission") == "stop_and_seek_professional_assessment":
        return False
    for strategy in (plan.get("strategies") or {}).values():
        for checkpoint in strategy.get("checkpoints") or []:
            if _midpoint(checkpoint) is not None:
                return True
    return False


def _source_label(cp: Mapping[str, Any]) -> str:
    layer = cp.get("source_layer")
    year = cp.get("source_year")
    if layer == "current_year_official":
        return f"{year or cp.get('applicable_year') or ''} 当年官方".strip()
    if layer == "official_historical_reference":
        return f"{year or '历史届次'} 官方历史参考（非目标年官方）"
    if layer == "third_party_cross_check":
        return "第三方交叉核验"
    return _value(layer, "来源待核验")


def _range(cp: Mapping[str, Any], *, clock: bool = False) -> str:
    values = cp.get("planned_arrival_clock_range" if clock else "arrival_elapsed_range_hhmmss", {})
    lower, upper = values.get("lower"), values.get("upper")
    return f"{lower} – {upper}" if lower and upper else "条件不足"


def _margin(cp: Mapping[str, Any], mode: str) -> str:
    margin = cp.get("cutoff_margin_range")
    if mode == "historical_route_reference":
        return "不可作为目标年关门余量"
    if not isinstance(margin, Mapping):
        return "目标年官方关门未核验"
    return f"{margin.get('minimum_minutes')}–{margin.get('maximum_minutes')} min"


def _minutes(value: Any, unknown: str = "—") -> str:
    try:
        total = max(int(round(float(value))), 0)
    except (TypeError, ValueError):
        return unknown
    hours, minutes = divmod(total, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}min"


def _midpoint(cp: Mapping[str, Any]) -> float | None:
    try:
        return float(cp.get("arrival_elapsed_range_minutes", {}).get("midpoint"))
    except (TypeError, ValueError):
        return None


def _clock(value: Any, unknown: str = "—") -> str:
    if not value:
        return unknown
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError:
        return text[:5] if len(text) >= 5 and text[2] == ":" else text


def _parse_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _is_night_hour(hour: float) -> bool:
    return hour < 6.0 or hour >= 18.0


def _night_column_enabled(event: Mapping[str, Any], checkpoints: list[Mapping[str, Any]]) -> bool:
    start = _parse_datetime(event.get("start_time"))
    cutoff = _parse_datetime(event.get("cutoff_time"))
    if start and cutoff and cutoff >= start:
        cursor = start
        while cursor <= cutoff:
            if _is_night_hour(cursor.hour + cursor.minute / 60.0):
                return True
            cursor += timedelta(minutes=30)
    for cp in checkpoints:
        value = cp.get("planned_arrival_clock_range", {}).get("midpoint")
        parsed = _parse_datetime(value)
        if parsed and _is_night_hour(parsed.hour + parsed.minute / 60.0):
            return True
    return bool(start and _is_night_hour(start.hour + start.minute / 60.0))


def _daypart(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return "🌙" if _is_night_hour(parsed.hour + parsed.minute / 60.0) else "☀️"


def _segment_daypart(previous: Mapping[str, Any], cp: Mapping[str, Any], event: Mapping[str, Any]) -> str:
    start_value = previous.get("planned_departure_clock") or previous.get("planned_arrival_clock_range", {}).get("midpoint") or event.get("start_time")
    end_value = cp.get("planned_arrival_clock_range", {}).get("midpoint")
    start_part, end_part = _daypart(start_value), _daypart(end_value)
    if start_part and end_part and start_part != end_part:
        return f"{start_part}→{end_part}"
    return end_part or start_part or "按官方起跑时刻判断"


def _difficulty(cp: Mapping[str, Any]) -> str:
    notes = [str(item) for item in [*(cp.get("terrain_notes") or []), *(cp.get("risk_notes") or [])] if item]
    if notes:
        return "、".join(notes[:2])
    gain = float(cp.get("segment_elevation_gain_m") or 0)
    loss = float(cp.get("segment_elevation_loss_m") or 0)
    if gain >= 500 and loss >= 500:
        return "高起伏技术段"
    if gain >= 500:
        return "持续爬升"
    if loss >= 500:
        return "长下坡"
    return "常规起伏"


def _injury_attention(cp: Mapping[str, Any], finish_distance: float) -> str:
    gain = float(cp.get("segment_elevation_gain_m") or 0)
    loss = float(cp.get("segment_elevation_loss_m") or 0)
    progress = float(cp.get("distance_km") or 0) / max(finish_distance, 0.001)
    if progress >= 0.85 or loss >= 650:
        return "🔴降级复核"
    if progress >= 0.45 or gain >= 500 or loss >= 350:
        return "🟡重点观察"
    return "🟢正常观察"


def _pipe(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _capture_summary(plan: Mapping[str, Any]) -> list[str]:
    capture = plan.get("conditional_time_plan", {}).get("target_group_capture", {})
    missing = capture.get("missing_coverage", [])
    pending = capture.get("pending_attachment_count", 0)
    lines = [
        f"- 搜索回执：{_CAPTURE_STATUS_NAMES.get(capture.get('search_completion_status', capture.get('capture_attempt_status')), '状态待核验')}。",
        f"- 目标绑定：{_value(capture.get('identity_binding', {}).get('year'))} / {_value(capture.get('identity_binding', {}).get('group_name'))}。",
    ]
    pending_details = [
        name for name, check in (capture.get("detail_checks") or {}).items()
        if isinstance(check, Mapping) and check.get("status") == "checked_not_confirmed"
    ]
    if pending_details:
        lines.append("- 已抓取但尚未确认：" + "、".join(pending_details) + "；仅表示已取得来源但适用性/一致性仍待确认。")
    if missing:
        lines.append("- 尚未完成的搜索通道：" + "、".join(_SEARCH_LANE_NAMES.get(str(item), "待补充的资料通道") for item in missing) + "。")
    if pending:
        lines.append(f"- 仍有 {pending} 个路线或 CP 附件尚未取得或尚未完成解析；这些资料未完成前不会写成已确认。")
    return lines


def _privacy_label(plan: Mapping[str, Any]) -> str:
    return {
        "authorized_private": "授权私密：仅限已授权私密使用",
        "private_alias": "私密代号：不展示姓名或完整 Runner ID",
        "public_shareable": "公开可分享：仍不默认披露完整身份",
    }.get(plan.get("privacy", {}).get("mode"), "私密代号：不展示姓名或完整 Runner ID")


def build_markdown_report(plan: Mapping[str, Any]) -> str:
    facts = plan["facts"]
    event = facts["event"]
    safety = facts["readiness_safety_cap"]
    selected = plan.get("recommended_strategy") or "safe_finish"
    strategy = plan.get("strategies", {}).get(selected, {})
    checkpoints = strategy.get("checkpoints", [])
    conditional = plan.get("conditional_time_plan", {})
    mode = str(conditional.get("mode") or "not_allowed")
    mode_label = _MODE_NAMES.get(mode, "资料待核验")
    show_time = _display_time(plan)
    execution_budget_only = show_time and not conditional.get("allowed")
    injury_policy = facts.get("report_column_policy", {}).get("injury", {})
    show_injury = bool(injury_policy.get("enabled"))
    injury_label = str(injury_policy.get("label") or "伤痛关注")
    show_day_night = _night_column_enabled(event, checkpoints)

    historical_reference = plan.get("historical_reference", {})
    confirmed_historical_reference = bool(
        isinstance(historical_reference, Mapping)
        and historical_reference.get("user_confirmed")
    )
    lines: list[str] = [
        "# 比赛策略与情景规划（历史路线参考版）" if confirmed_historical_reference else "# 比赛策略与情景规划",
        "",
    ]
    if confirmed_historical_reference:
        lines += [
            "> **历史资料参考已由用户确认：** 本报告按上一年度同赛事、同组别的官方路线资料生成。表内 CP、补给、关门与路线版本均不是今年已确认事实；赛前必须按今年官方公告复核。",
            "",
        ]
    if execution_budget_only:
        lines += ["> 主CP时间为执行预算（非官方关门验证）；官方分站关门、余量或当前状态缺失时分别保留“待补充”，不取消完整报告。", ""]
    if safety.get("risk_level") == "red":
        lines += ["## 安全停止", "", "当前存在红旗信号：停止成绩、CP 时间和追赶规划，优先遵从赛方、救援或医疗人员指令。", ""]
    lines += [
        "## 一、先看结论与适用边界", "",
        f"- 当前计划：{_NAMES.get(selected, selected)}；状态为内部条件式执行指导，不是已验证个人预测或完赛承诺。",
        f"- 当前安全状态：{_RISK_NAMES.get(safety.get('risk_level'), '资料不足，按保守规划')}；计划会随安全状态自动收紧或停止。",
        f"- CP 数据模式：{mode_label}。历史参考行会保留来源年份，绝不写成目标年份官方事实。",
        "- 报告中的到站/离站窗口只表达条件式执行边界；任何红旗症状均使全部时间目标失效。", "",
        "## 二、赛事资料与搜索回执", "",
        f"- 赛事：{_value(event.get('official_name'))}",
        f"- 年份/组别：{_value(event.get('year'))} / {_value(event.get('group_name', event.get('group_code')))}",
        f"- 距离/爬升：{_value(event.get('distance_km'))} km / {_value(event.get('elevation_gain_m'))} m+",
        f"- 起跑/总关门：{_value(event.get('start_time'))} / {_value(event.get('cutoff_time'))}", "",
    ]
    lines.extend(_capture_summary(plan))
    sand = facts.get("terrain_adjustment")
    if isinstance(sand, Mapping):
        lines += ["", "> **沙地保守修正：** 官方资料确认存在沙地/沙漠，但缺少跑者适应与可比赛事对照；中位时间按 ×1.20、参考区间按 ×1.12–×1.30 处理。这是未校准的保守假设，不是模型预测；获得更具体的历史或路线证据后应覆盖。"]
    lines += ["", "## 三、跑者档案与当前状态边界", "",
        f"- 隐私模式：{_privacy_label(plan)}。",
        "- 历史比赛只作为能力锚点；公开历史不能证明当前健康、伤病、疲劳或训练完成度。",
        "- 未提供当前状态时按信息不足处理，不自动判为绿色，也不开放积极方案。", "",
        "## 四、估算依据与局限", "",
        "- 时间范围以精确 ITRA ID 的历史表现、赛事距离与爬升资料为参考；它是研究情景估算，不是完赛承诺。",
        "- 训练量、当前状态、地形适应或可比赛事不足时，会扩大区间并降低把握，而不是把未知写成事实。",
        "- 当年官方 CP、官方历史参考、第三方核验、推导和建议在技术资料中分层保存。", "",
        "## 五、条件式整体建议", "",
        "- 前段以可重复动作为主，不为追时间突然加速；陡坡优先稳定步频，技术下坡保留安全余量。",
        "- 补给、饮水与装备只沿用已验证习惯；未知剂量不生成处方。",
        "- 若状态、天气、胃肠、装备或路线风险上升，切换到安全完成；不得一次性追回落后时间。", "",
        "## 六、全段总览与逐段战术详解", "",
        "### 6.1 全段总览表", "",
    ]
    headers = ["#", "赛段区间", "km", "爬升", "下降", "本段耗时", "到站停留", "出站用时", "累计用时", "到达时间", "离站时间", "关门时间", "余量", "赛道难度"]
    if show_injury:
        headers.append(injury_label)
    if show_day_night:
        headers.append("昼夜")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---:" if name in {"#", "km", "爬升", "下降"} else "---" for name in headers) + "|")
    segments = checkpoints[1:] if len(checkpoints) >= 2 else []
    if not segments:
        lines.append("| " + " | ".join(["—", "结构化赛段不可生成", *(["—"] * (len(headers) - 2))]) + " |")
    finish_distance = float(checkpoints[-1].get("distance_km") or event.get("distance_km") or 0) if checkpoints else 0.0
    for index, cp in enumerate(segments):
        previous = checkpoints[index]
        segment_distance = cp.get("segment_distance_km")
        segment_gain = cp.get("segment_elevation_gain_m")
        segment_loss = cp.get("segment_elevation_loss_m")
        if segment_distance is None and cp.get("distance_km") is not None and previous.get("distance_km") is not None:
            segment_distance = round(float(cp["distance_km"]) - float(previous["distance_km"]), 3)
        if segment_gain is None and cp.get("cumulative_gain_m") is not None and previous.get("cumulative_gain_m") is not None:
            segment_gain = round(float(cp["cumulative_gain_m"]) - float(previous["cumulative_gain_m"]), 1)
        if segment_loss is None and cp.get("cumulative_loss_m") is not None and previous.get("cumulative_loss_m") is not None:
            segment_loss = round(float(cp["cumulative_loss_m"]) - float(previous["cumulative_loss_m"]), 1)
        arrival_midpoint = _midpoint(cp)
        previous_departure = previous.get("planned_departure_elapsed_midpoint_minutes")
        try:
            segment_minutes = max(float(arrival_midpoint) - float(previous_departure or 0), 0.0) if arrival_midpoint is not None else None
        except (TypeError, ValueError):
            segment_minutes = None
        stop = cp.get("planned_stop_minutes")
        try:
            outbound_minutes = float(segment_minutes) + float(stop or 0) if segment_minutes is not None else None
        except (TypeError, ValueError):
            outbound_minutes = None
        cumulative = cp.get("planned_departure_elapsed_midpoint_minutes") if cp.get("role") != "finish" else arrival_midpoint
        route = f"{_value(cp.get('previous_cp'))} → {_value(cp.get('name'))}"
        cutoff = _clock(cp.get("official_cutoff"), "—")
        if mode == "historical_route_reference" and cutoff != "—":
            cutoff = f"历史 {cutoff}"
        row = [
            f"S{index}", route, _value(segment_distance, "—"),
            _value(segment_gain, "—"), _value(segment_loss, "—"),
            _minutes(segment_minutes, "待补充"), _minutes(stop, "待补充"), _minutes(outbound_minutes, "待补充"),
            _minutes(cumulative, "待补充"),
            _clock(cp.get("planned_arrival_clock_range", {}).get("midpoint"), "待补充") if show_time else "待补充",
            _clock(cp.get("planned_departure_clock"), "当前不提供") if show_time and cp.get("role") != "finish" else "—",
            cutoff, _margin(cp, mode), _difficulty({**cp, "segment_elevation_gain_m": segment_gain, "segment_elevation_loss_m": segment_loss}),
        ]
        if show_injury:
            row.append(_injury_attention(cp, finish_distance))
        if show_day_night:
            row.append(_segment_daypart(previous, cp, event))
        lines.append("| " + " | ".join(_pipe(value) for value in row) + " |")
    if checkpoints:
        last = checkpoints[-1]
        total_stops = sum(float(cp.get("planned_stop_minutes") or 0) for cp in checkpoints)
        finish_midpoint = _midpoint(last)
        moving = None if finish_midpoint is None else max(finish_midpoint - total_stops, 0.0)
        finish_clock = _clock(last.get("planned_arrival_clock_range", {}).get("midpoint"), "待补充") if show_time else "待补充"
        lines += ["", f"> **总计：** {_value(last.get('distance_km'), event.get('distance_km'))} km / D+ {_value(last.get('cumulative_gain_m'), event.get('elevation_gain_m'))} / D− {_value(last.get('cumulative_loss_m'))} / 纯跑约 {_minutes(moving, '当前不提供')} / 站停约 {_minutes(total_stops)} / 条件式完成 {finish_clock}"]
    if not show_time:
        lines += ["", "> 主CP时间字段已保留为“待补充”。出现红旗安全停止时，不提供配速或追赶目标。"]
    lines += ["", "> 表内时间是条件式执行窗口，不是已验证个人预测。历史参考关门不得作为目标年份正式关门。", "",
        "### 6.2 逐段战术详解", ""]
    for segment_index, cp in enumerate(checkpoints[1:]):
        title = f"{_value(cp.get('previous_cp'))} → {_value(cp.get('name'))}"
        segment_rows = [
            f"#### S{segment_index} · {title}", "",
            "| 维度 | 内容 |", "|---|---|",
            f"| 数据边界 | {_source_label(cp)}；路线版本 {_value(cp.get('route_version'))}；目标年适用性 {_APPLICABILITY_NAMES.get(cp.get('current_year_applicability'), '待核验')} |",
            f"| 距离与升降 | 分段 {_value(cp.get('segment_distance_km'))} km / +{_value(cp.get('segment_elevation_gain_m'))} / −{_value(cp.get('segment_elevation_loss_m'))}；累计 {_value(cp.get('distance_km'))} km |",
            f"| 条件式窗口 | 到站 {_range(cp, clock=True) if show_time else '当前不提供'}；停留 {_value(cp.get('planned_stop_minutes'))} min；离站 {_value(cp.get('planned_departure_clock')) if show_time else '当前不提供'} |",
            f"| 赛道特征 | {_value('、'.join(map(str, cp.get('terrain_notes') or [])), '以已解析路线资料为限')} |",
            f"| 风险 | {_value('、'.join(map(str, cp.get('risk_notes') or [])), '根据天气' + ('、昼夜' if show_day_night else '') + '和现场路况动态判断')} |",
        ]
        if show_injury:
            segment_rows.append(f"| {injury_label}关注 | {_injury_attention(cp, finish_distance)}；仅作赛中自查与降级提示，不作诊断。 |")
        action = (
            f"跑走：{_value(cp.get('movement_actions', {}).get('run_walk'))}；"
            f"技术下坡：{_value(cp.get('movement_actions', {}).get('technical_descent'))}"
        )
        if show_day_night:
            action += f"；夜间：{_value(cp.get('movement_actions', {}).get('night'))}"
        segment_rows += [
            f"| 行动策略 | {action} |",
            f"| 补给/装备 | {_value(cp.get('services'), '仅使用已验证补给')}；{_value(cp.get('equipment_notes'), '服从官方强制装备')} |",
            f"| 关门边界 | {_value(cp.get('official_cutoff'), '目标年官方分站关门未核验')}；{_margin(cp, mode)} |", "",
        ]
        lines += segment_rows
    lines += [
        "### 6.3 全程执行总则", "",
        "| 规则 | 说明 |", "|---|---|",
        "| 爬坡纪律 | 陡坡以可持续步频和快走为主，不在早段消耗不可恢复的腿力。 |",
    ]
    if show_day_night:
        lines.append("| 夜间纪律 | 缩短步幅、降低追赶冲动；照明、保暖或注意力异常时立即降级。 |")
    lines += [
        "| 下坡纪律 | 技术下坡小步高频，不锁膝，不为追回时间冒险。 |",
        "| 站停纪律 | 进站前列任务，完成补水、补给、装备检查后离站，避免无目的停留。 |",
        "| 红旗停止 | 胸痛、晕厥、意识异常、严重呼吸困难、不能负重、失温/热病或无法控制呕吐时停止成绩规划并求助。 |", "",
        "## 七、情景切换与赛中更新", "",
        "- 正常：证据条件成立且状态稳定，维持当前条件式窗口。",
        "- 保守：疼痛、疲劳、天气、补给或装备风险上升，放弃时间追逐，扩大窗口。",
        "- 安全停止：红旗或赛方/医疗指令出现，全部时间目标不可用。", "",
        "## 八、来源、隐私与技术附录", "",
        "- 原始来源、SHA-256、抓取错误和解析状态保存在本次请求的技术附件中。",
        "- 正常报告不公开身份映射、完整 Runner ID、逐场历史或本地绝对路径。", "",
    ]
    lines.extend(technical_appendix(plan))
    return "\n".join(lines) + "\n"
