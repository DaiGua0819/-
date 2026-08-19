REQUIREMENT_PENDING_REASON = (
    "待视觉识别/人工复核：目标是门店或品牌陈列、快闪空间、装置或品牌专区；"
    "普通产品图、生活照及其他无关图片不符合。当前未接入视觉 Provider。"
)


def assess_requirement() -> tuple[bool | None, str]:
    """返回图片需求判定的默认状态，后续可替换为已审批的视觉 Provider。"""

    return None, REQUIREMENT_PENDING_REASON
