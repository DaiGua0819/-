from enum import StrEnum


class SourceAccessMode(StrEnum):
    DISABLED = "disabled"
    MANUAL_IMPORT = "manual_import"
    AUTHORIZED_BROWSER = "authorized_browser"


class CaptureMode(StrEnum):
    VISIBLE_DOWNLOAD_OR_RENDERED = "visible_download_or_rendered"
    RENDERED_ONLY = "rendered_only"


class SessionStatus(StrEnum):
    UNKNOWN = "unknown"
    AUTHENTICATED = "authenticated"
    AUTH_REQUIRED = "auth_required"
    BLOCKED = "blocked"


class BrowserRunStatus(StrEnum):
    QUEUED = "queued"
    POLICY_CHECKED = "policy_checked"
    ACQUIRING_PROFILE = "acquiring_profile"
    CHECKING_SESSION = "checking_session"
    SEARCHING = "searching"
    COLLECTING_RESULTS = "collecting_results"
    OPENING_NOTE = "opening_note"
    CAPTURING = "capturing"
    CAPTURED = "captured"
    COMPLETED = "completed"
    AUTH_REQUIRED = "auth_required"
    BLOCKED = "blocked"
    SELECTOR_DRIFT = "selector_drift"
    CAPTURE_INCOMPLETE = "capture_incomplete"
    PAGE_TIMEOUT = "page_timeout"
    SESSION_CLOSED = "session_closed"
    CANCELLED = "cancelled"
    FAILED_PERMANENT = "failed_permanent"


class CaptureMethod(StrEnum):
    VISIBLE_DOWNLOAD = "visible_download"
    RENDERED_SCREENSHOT = "rendered_screenshot"


class AssetStatus(StrEnum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETED = "deleted"


class ErrorCode(StrEnum):
    SOURCE_POLICY_DISABLED = "source_policy_disabled"
    PROFILE_LEASE_CONFLICT = "profile_lease_conflict"
    AUTH_REQUIRED = "auth_required"
    SESSION_UNKNOWN = "session_unknown"
    CHALLENGE_PRESENT = "challenge_present"
    SELECTOR_DRIFT = "selector_drift"
    PAGE_TIMEOUT = "page_timeout"
    SESSION_CLOSED = "session_closed"
    RESULT_PARSE_FAILED = "result_parse_failed"
    NOTE_OPEN_FAILED = "note_open_failed"
    CAPTURE_INCOMPLETE = "capture_incomplete"
    FRAME_INVALID = "frame_invalid"
    VISIBLE_DOWNLOAD_FAILED = "visible_download_failed"
    FEISHU_QUERY_FAILED = "feishu_query_failed"
