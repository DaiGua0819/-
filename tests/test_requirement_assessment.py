from xvi.capture.requirement import assess_requirement


def test_requirement_assessment_defaults_to_manual_review() -> None:
    is_requirement_met, reason = assess_requirement()

    assert is_requirement_met is None
    assert "陈列" in reason
    assert "普通产品图" in reason
    assert "人工复核" in reason
