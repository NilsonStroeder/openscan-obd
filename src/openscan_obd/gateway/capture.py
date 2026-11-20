"""Persistência explícita de frames KWP em JSON Lines."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

CAPTURE_SCHEMA_VERSION = 1


class JsonlFrameCapture:
    def __init__(self, path: Path, metadata: dict[str, Any]) -> None:
        self.path = path
        self.metadata = metadata
        self._file: TextIO | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("x", encoding="utf-8", newline="\n")
        try:
            self._write({
                "event": "capture_started",
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "metadata": self.metadata,
            })
        except OSError:
            self._file.close()
            self._file = None
            raise

    def write_frame(self, frame: dict[str, Any]) -> None:
        self._write({
            "event": "frame",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "frame": frame,
        })

    def close(self) -> None:
        if self._file is None:
            return
        file = self._file
        try:
            self._write({
                "event": "capture_stopped",
                "captured_at": datetime.now(timezone.utc).isoformat(),
            })
        finally:
            try:
                file.close()
            finally:
                self._file = None

    def _write(self, record: dict[str, Any]) -> None:
        if self._file is None:
            raise RuntimeError("captura JSONL não está aberta")
        self._file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self._file.flush()
