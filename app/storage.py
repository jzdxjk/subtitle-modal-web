from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Job:
    id: str
    input_path: str
    output_dir: str
    formats: list[str]
    overwrite: bool
    move_target_dir: str
    status: str
    message: str
    output_files: list[str]
    created_at: float
    updated_at: float
    started_at: float = 0.0
    completed_at: float = 0.0
    progress: int = 0


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    input_path TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    formats TEXT NOT NULL,
                    overwrite INTEGER NOT NULL,
                    move_target_dir TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    output_files TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN move_target_dir TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN started_at REAL NOT NULL DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN completed_at REAL NOT NULL DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

    def create_job(self, input_path: str, output_dir: str, formats: Iterable[str], overwrite: bool, move_target_dir: str = "") -> Job:
        now = time.time()
        job = Job(
            id=str(uuid.uuid4()),
            input_path=input_path,
            output_dir=output_dir,
            formats=list(formats),
            overwrite=overwrite,
            move_target_dir=move_target_dir,
            status="queued",
            message="等待中",
            output_files=[],
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.input_path,
                    job.output_dir,
                    json.dumps(job.formats),
                    int(job.overwrite),
                    job.move_target_dir,
                    job.status,
                    job.message,
                    json.dumps(job.output_files),
                    job.created_at,
                    job.updated_at,
                    job.started_at,
                    job.completed_at,
                    job.progress,
                ),
            )
        return job

    def update_job(self, job_id: str, **fields: object) -> None:
        allowed = {"status", "message", "output_files", "started_at", "completed_at", "progress"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = time.time()
        columns = []
        values = []
        for key, value in updates.items():
            columns.append(f"{key} = ?")
            values.append(json.dumps(value) if key == "output_files" else value)
        values.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(columns)} WHERE id = ?", values)

    def get_job(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, limit: int = 100) -> list[Job]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def next_queued(self) -> Job | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1").fetchone()
        return self._row_to_job(row) if row else None

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation. Returns True if the job was cancellable."""
        with self._connect() as conn:
            job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return False
            status = job["status"]
            if status == "queued":
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', message = '用户已取消', updated_at = ? WHERE id = ?",
                    (time.time(), job_id),
                )
                return True
            if status == "running":
                conn.execute(
                    "UPDATE jobs SET status = 'cancelling', message = '取消中...', updated_at = ? WHERE id = ?",
                    (time.time(), job_id),
                )
                return True
            return False  # done/failed/cancelled/already cancelling

    def is_cancelling(self, job_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM jobs WHERE id = ? AND status = 'cancelling'", (job_id,)).fetchone()
        return row is not None

    def retry_job(self, job_id: str) -> bool:
        """Retry a failed/cancelled job by moving it back to queued."""
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None or row["status"] not in ("failed", "cancelled", "cancelling"):
                return False
            message = "重试已提交，等待中" if row["status"] == "failed" else "已重新加入队列，等待中"
            conn.execute(
                "UPDATE jobs SET status = 'queued', message = ?, output_files = ?, started_at = 0.0, completed_at = 0.0, progress = 0, updated_at = ? WHERE id = ?",
                (message, json.dumps([]), time.time(), job_id),
            )
        return True

    def retry_all_failed_jobs(self) -> int:
        """Retry all failed jobs and return affected row count."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'queued', message = ?, output_files = ?, started_at = 0.0, completed_at = 0.0, progress = 0, updated_at = ? WHERE status = 'failed'",
                ("批量重试已提交，等待中", json.dumps([]), time.time()),
            )
        return cur.rowcount

    def has_active_job_for_path(self, input_path: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE input_path = ? AND status IN ('queued', 'running', 'cancelling') LIMIT 1",
                (input_path,),
            ).fetchone()
        return row is not None

    def claim_next_queued(self) -> Job | None:
        """Atomically claim the next queued job. Returns the job or None."""
        claim_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'running', message = ?, updated_at = ? WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1)",
                (claim_id, now),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM jobs WHERE message = ? AND status = 'running'",
                (claim_id,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            input_path=row["input_path"],
            output_dir=row["output_dir"],
            formats=json.loads(row["formats"]),
            overwrite=bool(row["overwrite"]),
            move_target_dir=row["move_target_dir"],
            status=row["status"],
            message=row["message"],
            output_files=json.loads(row["output_files"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            progress=row["progress"],
        )

