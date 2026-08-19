from xvi.integrations.feishu_cli import FeishuCliQuerySource


def test_row_mapping_uses_field_ids() -> None:
    source = FeishuCliQuerySource.__new__(FeishuCliQuerySource)
    rule = source._row_to_rule(
        "rec-1",
        ["fld3St9ySE", "fldgGkSfV3", "fldXkf5vZp", "fldokhNRj0"],
        ["品牌 快闪", "品牌", ["快闪", "联名"], ["待检索"]],
    )
    assert rule.record_id == "rec-1"
    assert rule.query_text == "品牌 快闪"
    assert rule.event_types == ["快闪", "联名"]
    assert rule.status == "待检索"
