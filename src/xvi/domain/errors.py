from xvi.domain.enums import ErrorCode


class XviError(Exception):
    """XVI 业务异常基类。"""


class PolicyError(XviError):
    """来源访问策略不允许。"""

    def __init__(self, message: str = "当前来源访问策略不允许执行") -> None:
        super().__init__(message)
        self.code = ErrorCode.SOURCE_POLICY_DISABLED


class SelectorDriftError(XviError):
    """核心选择器无法定位或结构异常。"""

    def __init__(self, selector_key: str) -> None:
        super().__init__(f"核心选择器发生漂移: {selector_key}")
        self.code = ErrorCode.SELECTOR_DRIFT
        self.selector_key = selector_key


class CaptureIncompleteError(XviError):
    """轮播未能完整前进或闭环。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = ErrorCode.CAPTURE_INCOMPLETE
