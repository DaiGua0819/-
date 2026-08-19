import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID


class ArtifactWriter:
    """写入脱敏的浏览器运行 Artifact。"""

    def __init__(self, root: Path, run_id: UUID) -> None:
        self.directory = root / str(run_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.steps_path = self.directory / "steps.jsonl"

    def write_manifest(self, payload: dict[str, Any]) -> None:
        self._write_json("manifest.json", payload)

    def write_result(self, payload: dict[str, Any]) -> None:
        self._write_json("result.json", payload)

    def write_diagnostics(self, payload: dict[str, Any]) -> None:
        self._write_json("diagnostics.json", payload)

    def append_step(self, step: str, status: str, **metadata: Any) -> None:
        entry = {
            "step": step,
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata,
        }
        with self.steps_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def _write_json(self, name: str, payload: dict[str, Any]) -> None:
        path = self.directory / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
