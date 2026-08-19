import json
import subprocess
from typing import Any

from xvi.domain.errors import XviError
from xvi.domain.models import QueryRule


class FeishuCliQuerySource:
    """通过用户已配置的 lark-cli 只读读取飞书 Base 查询规则。"""

    def __init__(self, cli_bin: str, base_url: str, identity: str = "user") -> None:
        if not base_url:
            raise ValueError("FEISHU_BASE_URL 不能为空")
        self.cli_bin = cli_bin
        self.base_url = base_url
        self.identity = identity

    def load_rules(self, limit: int = 200) -> list[QueryRule]:
        resolved = self._run(
            "base",
            "+url-resolve",
            "--url",
            self.base_url,
            "--as",
            self.identity,
            "--json",
            "--jq",
            ".data",
        )
        base_token = str(resolved["base_token"])
        table_id = str(resolved["table_id"])
        view_id = str(resolved.get("view_id", ""))
        args = [
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--limit",
            str(limit),
            "--format",
            "json",
            "--as",
            self.identity,
            "--jq",
            ".data",
        ]
        if view_id:
            args.extend(["--view-id", view_id])
        records = self._run(*args)
        field_ids = records["field_id_list"]
        rows = records.get("data", [])
        return [
            self._row_to_rule(record_id, field_ids, row)
            for record_id, row in zip(records["record_id_list"], rows, strict=False)
        ]

    def _row_to_rule(self, record_id: str, field_ids: list[str], row: list[Any]) -> QueryRule:
        values = dict(zip(field_ids, row, strict=False))

        def text(field_id: str) -> str | None:
            value = values.get(field_id)
            if isinstance(value, list):
                return ", ".join(str(item) for item in value) or None
            return str(value).strip() if value is not None and str(value).strip() else None

        def tags(field_id: str) -> list[str]:
            value = values.get(field_id)
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item) for item in value]
            return [str(value)]

        return QueryRule(
            record_id=record_id,
            query_text=text("fld3St9ySE") or "",
            target=text("fldgGkSfV3"),
            entity_type=text("fldQQaoJ3J"),
            market=text("fldtUa1LQS"),
            priority=text("fldKh8V419"),
            event_types=tags("fldXkf5vZp"),
            location_terms=text("fldT9SJoh9"),
            inclusion_criteria=text("fldQL7cqJd"),
            exclusion_criteria=text("fldCJxcEA7"),
            status=text("fldokhNRj0"),
            notes=text("flddzry9GA"),
        )

    def _run(self, *args: str) -> dict[str, Any]:
        completed = subprocess.run([self.cli_bin, *args], capture_output=True, check=False)
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if completed.returncode != 0:
            raise XviError(f"飞书 CLI 查询失败: {stderr[-500:] or stdout[-500:]}")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise XviError("飞书 CLI 返回的不是有效 JSON") from exc
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise XviError(f"飞书 CLI 返回错误: {payload.get('error')}")
        if not isinstance(payload, dict):
            raise XviError("飞书 CLI 返回的 JSON 顶层不是对象")
        return {str(key): value for key, value in payload.items()}
