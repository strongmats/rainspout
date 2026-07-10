"""The operational log: per (stage x work item) truth, and the resume source.

Append-only JSONL. Two record kinds: one per stage execution, one summary per
work item. "What has already been attempted" — the driver's delta subtracts
work-item records (success or failure alike); `--retry-failed` re-queues the
cells whose latest summary is a failure.

This log answers "what has the pipeline done?" — the provenance chain
(:mod:`rainspout.provenance`), which travels with the data, answers "where did
this file come from?". They are never merged.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .errors import RainspoutError


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["stage"] = "stage"
    run_id: str
    cell_id: str
    stage: str  # the stage INSTANCE name from the config
    status: Literal["succeeded", "failed"]
    status_line: str = ""
    warnings: tuple[str, ...] = ()
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class WorkItemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["work_item"] = "work_item"
    run_id: str
    cell_id: str
    status: Literal["succeeded", "failed"]
    failed_stage: str | None = None
    finished_at: datetime


Record = StageRecord | WorkItemRecord


class OpLog:
    """An append-only JSONL operational log at a fixed path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Record) -> None:
        with self.path.open("a") as f:
            f.write(record.model_dump_json() + "\n")

    def records(self) -> tuple[Record, ...]:
        if not self.path.exists():
            return ()
        parsed: list[Record] = []
        for line_no, line in enumerate(self.path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            kind = payload.get("kind")
            if kind == "stage":
                parsed.append(StageRecord.model_validate(payload))
            elif kind == "work_item":
                parsed.append(WorkItemRecord.model_validate(payload))
            else:
                raise RainspoutError(
                    f"operational log {self.path} line {line_no}: unknown record kind {kind!r}"
                )
        return tuple(parsed)

    def attempted_cells(self) -> frozenset[str]:
        """Every cell with a work-item summary — success or failure alike."""
        return frozenset(
            record.cell_id for record in self.records() if isinstance(record, WorkItemRecord)
        )

    def failed_cells(self) -> frozenset[str]:
        """Cells whose LATEST work-item summary is a failure."""
        latest: dict[str, str] = {}
        for record in self.records():
            if isinstance(record, WorkItemRecord):
                latest[record.cell_id] = record.status
        return frozenset(cell for cell, status in latest.items() if status == "failed")
