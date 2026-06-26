from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.config import ConfigStore
from app.media import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    discover_media,
    extract_av_code,
    list_small_av_files,
    output_subtitle_path,
    prepare_audio,
)


def _output_exists_for_media(media_path: Path, output_dir: Path, formats: list[str]) -> bool:
    """检查媒体文件的所有格式字幕是否都已存在"""
    return all(output_subtitle_path(media_path, output_dir, fmt).exists() for fmt in formats)


from app.modal_runner import ModalRunner
from app.storage import Job, JobStore

logger = logging.getLogger("subtitle.worker")


@dataclass
class SmallFileSnapshot:
    path: str
    size: int
    mtime: float


class SmallFileIgnoreStore:
    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    def should_skip(self, entry: Path) -> bool:
        record = self._data.get(str(entry))
        if not record:
            return False

        current_files = self._current_files(entry)
        if current_files is None:
            self.forget(entry)
            return False

        current = [asdict(item) for item in self._snapshot_files(current_files)]
        if record.get("files") != current:
            self.forget(entry)
            return False
        return True

    def remember(self, entry: Path, files: list[Path]) -> None:
        self._data[str(entry)] = {
            "files": [asdict(item) for item in self._snapshot_files(files)],
            "updated_at": time.time(),
        }
        self._save()

    def forget(self, entry: Path) -> None:
        if self._data.pop(str(entry), None) is not None:
            self._save()

    def _current_files(self, entry: Path) -> list[Path] | None:
        if entry.is_file():
            if not entry.exists():
                return None
            if extract_av_code(entry) is None:
                return None
            if entry.suffix.lower() not in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS:
                return None
            return [entry]

        if not entry.exists():
            return None

        files = sorted(
            path for path in entry.rglob("*")
            if path.is_file()
            and extract_av_code(path) is not None
            and path.suffix.lower() in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
        )
        return files or None

    @staticmethod
    def _snapshot_files(files: list[Path]) -> list[SmallFileSnapshot]:
        snapshots: list[SmallFileSnapshot] = []
        for file_path in sorted(files):
            stat = file_path.stat()
            snapshots.append(SmallFileSnapshot(path=str(file_path), size=stat.st_size, mtime=stat.st_mtime))
        return snapshots

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")


class JobRunner:
    def __init__(self, store: JobStore, config_store: ConfigStore, watch_root: Path, cache_dir: Path):
        self.store = store
        self.config_store = config_store
        self.watch_root = watch_root
        self.cache_dir = cache_dir
        self.small_file_ignore_store = SmallFileIgnoreStore(self.config_store.path.parent / "watchdog_ignored_small_files.json")
        self._running = False

    async def start(self) -> None:
        self._running = True
        tasks = [asyncio.create_task(self._run_forever())]
        tasks.append(asyncio.create_task(self._watchdog_loop()))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_forever(self) -> None:
        config = self.config_store.load()
        max_workers = max(1, min(config.max_workers, 10))
        semaphore = asyncio.Semaphore(max_workers)
        local_lock = asyncio.Lock()
        worker_counter = 0

        async def worker(worker_id: int) -> None:
            while self._running:
                # --- claim_next_queued with defensive error handling ---
                try:
                    job = self.store.claim_next_queued()
                except Exception:
                    logger.exception("worker-%d claim_next_queued raised", worker_id)
                    await asyncio.sleep(2)
                    continue

                if job is None:
                    await asyncio.sleep(2)
                    continue

                # --- is_cancelling with defensive error handling ---
                try:
                    cancelling = self.store.is_cancelling(job.id)
                except Exception:
                    logger.exception("worker-%d is_cancelling raised for job %s", worker_id, job.id)
                    cancelling = False

                if cancelling:
                    logger.info("worker-%d skipping cancelling job %s", worker_id, job.id)
                    await asyncio.sleep(2)
                    continue

                async with semaphore:
                    try:
                        logger.info("worker-%d claimed job %s path=%s", worker_id, job.id, job.input_path)
                        await self._process_job_pipelined(job, local_lock)
                        logger.info("worker-%d finished job %s", worker_id, job.id)
                    except Exception as exc:
                        logger.exception("worker-%d processing job %s failed", worker_id, job.id)
                        self.store.update_job(job.id, status="failed", message=str(exc), completed_at=time.time())

        def _new_worker() -> asyncio.Task:
            nonlocal worker_counter
            wid = worker_counter
            worker_counter += 1
            return asyncio.create_task(worker(wid), name=f"worker-{wid}")

        # Config refresher: one-shot, reads config every 30s, adjusts semaphore
        # and pending set when max_workers changes.
        async def config_refresher() -> None:
            nonlocal max_workers
            try:
                fresh = self.config_store.load()
                new_max = max(1, min(fresh.max_workers, 10))
                diff = new_max - max_workers
                if diff > 0:
                    for _ in range(diff):
                        semaphore.release()
                        pending.add(_new_worker())
                    logger.info("_run_forever: max_workers %d -> %d (added %d workers, semaphore +%d)", max_workers, new_max, diff, diff)
                elif diff < 0:
                    logger.info("_run_forever: max_workers %d -> %d (extra workers exit naturally)", max_workers, new_max)
                max_workers = new_max
            except Exception:
                logger.exception("config_refresher: config load failed")
            await asyncio.sleep(30)

        # Launch initial workers (pending defined first so config_refresher closure can access it)
        pending: set[asyncio.Task] = set()
        for _ in range(max_workers):
            pending.add(_new_worker())
        pending.add(asyncio.create_task(config_refresher(), name="config-refresher"))
        logger.info("_run_forever: started %d workers", max_workers)

        # Main loop: detect dead workers, restart them
        while self._running and pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                name = task.get_name()
                if name == "config-refresher":
                    # Restart config refresher if it died
                    pending.add(asyncio.create_task(config_refresher(), name="config-refresher"))
                else:
                    if not task.cancelled():
                        exc = task.exception()
                        if exc:
                            logger.error("worker '%s' died: %s", name, exc)
                        else:
                            logger.error("worker '%s' exited without exception", name)
                    # Restart only if below target (respects down-scaling)
                    current = sum(1 for t in pending if t.get_name() != "config-refresher")
                    if current < max_workers and self._running:
                        new_t = _new_worker()
                        pending.add(new_t)
                        logger.info("restarted dead worker as '%s'", new_t.get_name())

        logger.info("_run_forever: all workers stopped")

    async def _process_job_pipelined(self, job: Job, local_lock: asyncio.Lock) -> None:
        """Pipeline: serial local phase (ffmpeg+submit), parallel cloud phase."""
        stage = ""
        phase_timings: dict[str, int] = {}
        t0: float | None = None
        try:
            self.store.update_job(job.id, progress=0)

            config = self.config_store.load()
            media_files = discover_media(Path(job.input_path), min_file_size_mb=config.min_file_size_mb)
            if not media_files:
                raise RuntimeError("未找到支持的媒体文件")

            runner = ModalRunner(config, self.cache_dir)
            output_files: list[str] = []
            media_parents: set[Path] = set()
            item_output_dir = Path(job.output_dir)

            total_media = len(media_files)
            audio_paths: list[Path] = []
            for index, media_path in enumerate(media_files, start=1):
                if self.store.is_cancelling(job.id):
                    self.store.update_job(job.id, status="cancelled", message=f"用户已取消（文件 {index}/{total_media}）")
                    return

                # Skip check (no cloud needed)
                expected = [output_subtitle_path(media_path, item_output_dir, fmt) for fmt in job.formats]
                if not job.overwrite and all(path.exists() for path in expected):
                    logger.info("[skip] job=%s media=%s existing files=%s", job.id, media_path.name, [str(p) for p in expected])
                    output_files.extend(str(path) for path in expected)
                    media_parents.add(media_path.parent)
                    prog = min(int(index / total_media * 95), 99)
                    self.store.update_job(job.id, message=f"⏭️ 字幕已存在，跳过（{index}/{total_media}）", progress=prog)
                    continue

                # --- Serial phase: ffmpeg + submit ---
                if t0 is None:
                    self.store.update_job(
                        job.id,
                        status="running",
                        message=f"⏳ 等待本地处理通道（{index}/{total_media}）",
                        progress=max(1, (index - 1) * 35 // total_media),
                    )

                async with local_lock:
                    if self.store.is_cancelling(job.id):
                        self.store.update_job(job.id, status="cancelled", message=f"用户已取消（文件 {index}/{total_media}）")
                        return

                    if t0 is None:
                        t0 = time.time()
                        self.store.update_job(job.id, started_at=t0)

                    t_local_start = time.time()


                    def _mk_cb(jid, store, idx, total, tls):
                        def cb(pct):
                            overall = int(pct * 35 // 100) + (idx - 1) * 35 // total if total > 0 else 0
                            elapsed = int(time.time() - tls)
                            store.update_job(jid, message=f"🎵 正在提取音频 {idx}/{total}  {pct}%  ⏱ {elapsed}s", progress=overall)
                        return cb

                    stage = f"正在提取音频 {index}/{total_media}"
                    self.store.update_job(job.id, status="running", message=f"🎵 正在提取音频 {index}/{total_media}", progress=max(1, (index - 1) * 35 // total_media))
                    audio_path = await asyncio.to_thread(
                        prepare_audio, media_path, self.cache_dir,
                        on_progress=_mk_cb(job.id, self.store, index, total_media, t_local_start),
                        is_cancelled_fn=lambda: self.store.is_cancelling(job.id),
                    )

                    if self.store.is_cancelling(job.id):
                        self.store.update_job(job.id, status="cancelled", message=f"用户已取消（文件 {index}/{total_media}）")
                        return

                    audio_paths.append(audio_path)
                    t_local_end = time.time()
                    local_dur = int(t_local_end - t_local_start)
                    phase_timings["local"] = phase_timings.get("local", 0) + local_dur

                    stage = f"正在上传到云端 {index}/{total_media}"
                    base_prog = 35 + (index - 1) * 55 // total_media if total_media > 0 else 35

                    self.store.update_job(job.id, message=f"☁️ 正在上传音频到云端GPU...（{index}/{total_media}）", progress=base_prog)
                    handle = await asyncio.to_thread(runner.launch, audio_path, item_output_dir, job.formats, config.default_timeout_seconds)

                    self.store.update_job(job.id, message=f"☁️ 正在提交到云端GPU...（{index}/{total_media}）", progress=base_prog + 5)
                    await asyncio.to_thread(handle.wait_for_submit, 600)

                # --- Parallel phase: cloud runs, next job can start local ---
                t_cloud_start = time.time()
                stage = f"云端推理中 {index}/{total_media}"
                cloud_prog = 40 + (index - 1) * 50 // total_media if total_media > 0 else 40
                self.store.update_job(job.id, message=f"🧠 云端推理中...（{index}/{total_media}）（下一个任务可同时进行）", progress=cloud_prog)

                result = await asyncio.to_thread(handle.wait, config.default_timeout_seconds)
                t_cloud_end = time.time()
                cloud_dur = int(t_cloud_end - t_cloud_start)
                phase_timings["cloud"] = phase_timings.get("cloud", 0) + cloud_dur



                # --- Finalize ---
                stage = f"正在整理输出 {index}/{total_media}"
                final_prog = 90 + (index - 1) * 10 // total_media if total_media > 0 else 90
                self.store.update_job(job.id, message=f"📦 正在整理输出文件...（{index}/{total_media}）", progress=final_prog)
                logger.info("[normalize] job=%s media=%s produced=%s expected=%s",
                            job.id, media_path.name,
                            [str(p) for p in result.output_files],
                            [str(p) for p in expected])
                renamed = self._normalize_outputs(result.output_files, expected)
                logger.info("[normalize] job=%s renamed=%s", job.id, [str(p) for p in renamed])
                output_files.extend(str(path) for path in renamed)
                media_parents.add(media_path.parent)

            # Post-processing: move source folders
            move_target = job.move_target_dir or config.default_move_target_dir
            if move_target:
                stage = "正在移动源文件夹"
                self.store.update_job(job.id, message=f"📂 正在移动源文件夹到 {move_target}", progress=95)
                output_parents = {Path(f).parent for f in output_files}
                for parent in sorted(media_parents):
                    if not parent.exists():
                        continue
                    if parent == self.watch_root:
                        logger.warning("refusing to move watch root: %s", parent)
                        continue
                    # 检查输出文件是否在移动范围内，避免删除已生成的字幕
                    if any(parent in op.parents or parent == op for op in output_parents):
                        logger.warning("refusing to move parent %s: output files are inside", parent)
                        continue
                    dest = Path(move_target) / parent.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(shutil.move, str(parent), str(dest))

            # Done - format timing message
            def _fmt_mmss(seconds: int) -> str:
                minutes, secs = divmod(max(0, int(seconds)), 60)
                return f"{minutes:02d}:{secs:02d}"

            t_end = time.time()
            total_dur = int(t_end - (t0 or t_end))
            local_secs = phase_timings.get("local", 0)
            cloud_secs = phase_timings.get("cloud", 0)
            local_str = f"本地{_fmt_mmss(local_secs)}" if local_secs else ""
            cloud_str = f"云端{_fmt_mmss(cloud_secs)}" if cloud_secs else ""
            timing_msg = f"✅ 完成  总耗时{_fmt_mmss(total_dur)}"
            if local_str or cloud_str:
                timing_msg += f"（{local_str} / {cloud_str}）"
            # 前端通过 completed_at 时间戳渲染完成时间，消息只保留耗时

            verified_files = [f for f in output_files if Path(f).exists()]
            if len(verified_files) < len(output_files):
                missing = [f for f in output_files if not Path(f).exists()]
                logger.warning("job %s: %d/%d output files missing at completion: %s",
                               job.id, len(output_files) - len(verified_files), len(output_files), missing)
            else:
                logger.info("job %s: all %d output files verified: %s", job.id, len(verified_files), verified_files)
            self.store.update_job(job.id, status="done", message=timing_msg,
                                  output_files=verified_files, completed_at=t_end, progress=100)

            for p in audio_paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as exc:
            self.store.update_job(job.id, status="failed", message=f"❌ {stage}: {exc}", completed_at=time.time())

    async def _watchdog_loop(self) -> None:
        while self._running:
            config = self.config_store.load()
            if not config.enable_watchdog:
                await asyncio.sleep(5)
                continue

            try:
                candidates: set[Path] = set()
                min_file_size_mb = config.min_file_size_mb
                for entry in sorted(self.watch_root.iterdir()):
                    if self.small_file_ignore_store.should_skip(entry):
                        continue

                    media = discover_media(entry, min_file_size_mb=min_file_size_mb)
                    if media:
                        self.small_file_ignore_store.forget(entry)
                        parent = media[0].parent
                        if parent == self.watch_root:
                            # 根目录直放文件：创建子目录，移入文件，统一为子目录模式
                            av_code = extract_av_code(media[0]) or media[0].stem
                            sub_dir = self.watch_root / av_code
                            sub_dir.mkdir(exist_ok=True)
                            try:
                                dest = sub_dir / media[0].name
                                media[0].rename(dest)
                                logger.info("moved root file %s -> %s", media[0].name, dest)
                            except OSError:
                                logger.exception("move failed for %s", media[0])
                                continue
                            candidates.add(sub_dir)
                        else:
                            candidates.add(parent)
                        continue

                    small_files = list_small_av_files(entry, min_file_size_mb=min_file_size_mb)
                    if small_files:
                        self.small_file_ignore_store.remember(entry, small_files)
                    else:
                        self.small_file_ignore_store.forget(entry)

                for path in sorted(candidates):
                    formats = [f.strip() for f in config.default_formats.split(",") if f.strip()]
                    output_dir = Path(config.default_output_dir)
                    input_path = str(path)

                    # A: 跳过活跃任务中已有或字幕已存在的文件
                    if self.store.has_active_job_for_path(input_path):
                        continue
                    if self.store.has_any_failed_job_for_path(input_path):
                        continue  # 已有失败任务，不自动重试
                    media_files = discover_media(path, min_file_size_mb=min_file_size_mb)
                    if all(
                        _output_exists_for_media(m, output_dir, formats)
                        for m in media_files
                    ):
                        continue

                    self.store.create_job(
                        input_path=input_path,
                        output_dir=config.default_output_dir,
                        formats=formats,
                        overwrite=False,
                        move_target_dir=config.default_move_target_dir,
                    )
            except Exception:
                logger.exception("watchdog scan error")

            await asyncio.sleep(config.watchdog_interval_seconds)

    def stop(self) -> None:
        self._running = False

    @staticmethod
    def _normalize_outputs(produced: list[Path], expected: list[Path]) -> list[Path]:
        if not produced:
            logger.info("[normalize] no produced files, returning []")
            return []

        # 过滤掉不属于当前任务的文件：produced 来自共享 /output/ 的 before/after 快照差集，
        # 可能包含其他并发任务的输出。用 AV 番号匹配而非文件名精确匹配。
        from app.media import extract_av_code
        expected_codes = {extract_av_code(t) for t in expected}
        expected_codes.discard(None)
        if expected_codes:
            original_count = len(produced)
            produced = [p for p in produced if extract_av_code(p) in expected_codes]
            if len(produced) < original_count:
                logger.info("[normalize] filtered %d -> %d files (excluded other jobs' output)",
                            original_count, len(produced))

        normalized: list[Path] = []
        # 按后缀分组，每个后缀可能对应多个文件（如脏名 + 纯番号）
        by_suffix: dict[str, list[Path]] = {}
        for path in produced:
            by_suffix.setdefault(path.suffix.lower(), []).append(path)
        logger.info("[normalize] by_suffix=%s", {k: [str(p) for p in v] for k, v in by_suffix.items()})

        for target in expected:
            candidates = by_suffix.get(target.suffix.lower(), [])
            if not candidates:
                logger.warning("[normalize] no candidates for target %s (suffix %s)", target, target.suffix)
                continue
            # 优先选文件名已经匹配的，否则取第一个
            source = next(
                (p for p in candidates if p.name == target.name),
                candidates[0]
            )
            candidates.remove(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                logger.info("[normalize] moving %s -> %s", source, target)
                shutil.move(str(source), str(target))
            normalized.append(target)

        # 清理未被匹配的脏文件（如 489155.com@START-554-xxxx.srt）
        # 经过 AV 番号过滤后，leftovers 只包含属于当前任务的多余文件，可安全删除。
        leftovers = [p for lst in by_suffix.values() for p in lst]
        if leftovers:
            logger.info("[normalize] deleting %d leftover(s): %s", len(leftovers), [str(p) for p in leftovers])
        for path in leftovers:
            try:
                path.unlink()
            except OSError:
                pass

        result = [p for p in (normalized or produced) if p.exists()]
        logger.info("[normalize] returning %d file(s): %s", len(result), [str(p) for p in result])
        return result
