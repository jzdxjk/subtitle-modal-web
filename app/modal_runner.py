from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import textwrap
import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig


@dataclass
class ModalResult:
    output_files: list[Path]
    message: str


MODAL_RECONNECT_GRACE_SECONDS = 300


def modal_client_wait_timeout(remote_timeout_seconds: int) -> int:
    return max(1, int(remote_timeout_seconds)) + MODAL_RECONNECT_GRACE_SECONDS


def is_transient_modal_connection_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in (
        "modal.exception.connectionerror",
        "grpclib.exceptions.streamterminatederror",
    ))


class ModalRunHandle:
    """Handle to a running Modal cloud job started via ModalRunner.launch()."""

    def __init__(self, proc: subprocess.Popen, output_dir: Path, formats: list[str], before: dict[Path, float]):
        self._proc = proc
        self._output_dir = output_dir
        self._formats = formats
        self._before = before
        self._submitted_lines: list[str] = []
        self._stderr_lines: list[str] = []
        self._submitted = False

    def wait_for_submit(self, timeout_seconds: int = 600) -> None:
        """Block until the bridge script reaches the cloud submission stage."""
        result: list[str] = []

        def _reader() -> None:
            for line in self._proc.stdout:
                result.append(line)
                if "[modal_stage] run_remote_pipeline" in line:
                    return

        def _stderr_reader() -> None:
            for _line in self._proc.stderr:
                if _line.strip():
                    self._stderr_lines.append(_line.rstrip("\n"))
                    logging.getLogger("subtitle.modal").warning("[bridge-stderr] %s", _line.rstrip("\n"))

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        stderr_thread = threading.Thread(target=_stderr_reader, daemon=True)
        stderr_thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            self._proc.kill()
            self._proc.wait()
            raise RuntimeError("Timed out waiting for Modal cloud submission")

        self._submitted_lines = [line.rstrip("\n") for line in result]

        # If process exited during submission, it's an error
        if self._proc.poll() is not None:
            stderr_thread.join(timeout=1)
            stderr_remainder = self._proc.stderr.read()
            stdout_tail = "\n".join(self._submitted_lines[-30:])
            stderr_text = "\n".join([*self._stderr_lines, stderr_remainder or ""]).strip()
            raise RuntimeError(f"Modal bridge failed before cloud submission:\n{stdout_tail}\n{stderr_text}")

        self._submitted = True

    def wait(self, timeout_seconds: int | None = None) -> ModalResult:
        """Wait for cloud job to finish and return results."""
        if not self._submitted:
            self.wait_for_submit()

        try:
            stdout_remainder, stderr = self._proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.communicate()
            raise RuntimeError("Modal cloud run timed out")

        # Combine all stdout
        full_stdout = "\n".join(self._submitted_lines)
        if stdout_remainder:
            full_stdout += "\n" + stdout_remainder

        if self._proc.returncode != 0:
            stdout_tail = full_stdout[-3000:]
            stderr_tail = (stderr or "")[-3000:]
            last_stage = "unknown"
            for line in reversed(full_stdout.splitlines()):
                if line.startswith("[modal_stage]"):
                    last_stage = line.split("]", 1)[1].strip()
                    break
            detail = f"stage={last_stage}"
            if stdout_tail.strip():
                detail += f"\n--- stdout tail ---\n{stdout_tail.strip()}"
            stderr_combined = "\n".join([*self._stderr_lines, stderr_tail or ""]).strip()
            if stderr_combined:
                detail += f"\n--- stderr tail ---\n{stderr_combined[-3000:]}"
            raise RuntimeError(f"Modal run failed at stage [{last_stage}]: {detail}")

        after = ModalRunner._snapshot(self._output_dir, self._formats)
        produced = sorted(p for p, mtime in after.items() if p not in self._before or mtime > self._before[p])
        return ModalResult(output_files=produced, message=self._extract_log_summary(full_stdout))

    @staticmethod
    def _extract_log_summary(stdout: str) -> str:
        stages = []
        for line in stdout.splitlines():
            if line.startswith("[modal_stage]"):
                stages.append(line.split("]", 1)[1].strip())
        prefix = " -> ".join(stages) if stages else "no stage info"
        tail = stdout[-2000:].strip()
        return f"{prefix}\n{tail}" if tail else prefix


def _find_matching_paren(source: str, open_pos: int) -> int:
    """Return the index of the matching close paren for open_pos."""
    if source[open_pos] != "(":
        raise ValueError("open_pos must point to '('")
    depth = 1
    close_pos = open_pos + 1
    while close_pos < len(source) and depth > 0:
        ch = source[close_pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        close_pos += 1
    if depth != 0:
        raise RuntimeError("Unmatched parentheses in source")
    return close_pos - 1  # index of the matching )


def _paren_block_has_include_source(source: str, open_pos: int) -> bool:
    """Check if the paren block starting at open_pos contains include_source=True."""
    close = _find_matching_paren(source, open_pos)
    return bool(re.search(r"include_source\s*=\s*True", source[open_pos:close]))


def _all_apps_have_include_source(source: str) -> bool:
    """Check that every modal.App(...) call in source includes include_source."""
    for match in re.finditer(r"\bmodal\.App\s*\(", source):
        start = match.end() - 1
        if not _paren_block_has_include_source(source, start):
            return False
    return True


def _patch_remote_repo_ref(source: str) -> str:
    """Make upstream Modal code honor the repo ref selected in this app."""
    new = textwrap.dedent('''
        repo_ref = job.get("repo_ref") or "main"
        if not (repo_dir / ".git").exists():
            log("开始克隆仓库...")
            run(["git", "clone", "--depth", "1", REPO_URL, str(repo_dir)])
        else:
            log("更新仓库...")

        log(f"切换仓库版本: {repo_ref}")
        run(["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", repo_ref])
        run(["git", "-C", str(repo_dir), "reset", "--hard", "FETCH_HEAD"])
    ''').strip()
    pattern = (
        r'(?P<indent>[ \t]*)if not \(repo_dir / "\.git"\)\.exists\(\):\n'
        r'(?P=indent)[ \t]+log\([^\n]+\)\n'
        r'(?P=indent)[ \t]+run\(\["git", "clone", "--depth", "1", REPO_URL, str\(repo_dir\)\]\)\n'
        r'(?P=indent)else:\n'
        r'(?P=indent)[ \t]+log\([^\n]+\)\n'
        r'(?P=indent)[ \t]+run\(\["git", "-C", str\(repo_dir\), "fetch", "origin"\]\)\n'
        r'(?P=indent)[ \t]+run\(\["git", "-C", str\(repo_dir\), "reset", "--hard", "origin/main"\]\)'
    )

    def repl(match: re.Match) -> str:
        indent = match.group("indent")
        return "\n".join(indent + line if line else line for line in new.splitlines())

    return re.sub(pattern, repl, source, count=1)


def _patch_remote_smart_vad_arg(source: str) -> str:
    """Pass smart VAD explicitly to upstream infer.py when that version supports it."""
    new = textwrap.dedent('''
        if job["enable_batching"]:
            cmd.append("--enable_batching")
            if job["batch_size"]:
                cmd.extend(["--batch_size", str(job["batch_size"])])
            cmd.extend(["--max_batch_size", str(job["max_batch_size"])])

        if job.get("supports_smart_vad"):
            smart_vad_value = "true" if job.get("smart_split_with_vad") else "false"
            cmd.extend(["--smart_split_with_vad", smart_vad_value])

        cmd.extend(job["remote_inputs"])
    ''').strip()
    pattern = (
        r'(?P<indent>[ \t]*)if job\["enable_batching"\]:\n'
        r'(?P=indent)[ \t]+cmd\.append\("--enable_batching"\)\n'
        r'(?P=indent)[ \t]+if job\["batch_size"\]:\n'
        r'(?P=indent)[ \t]+cmd\.extend\(\["--batch_size", str\(job\["batch_size"\]\)\]\)\n'
        r'(?P=indent)[ \t]+cmd\.extend\(\["--max_batch_size", str\(job\["max_batch_size"\]\)\]\)\n'
        r'\n'
        r'(?P=indent)cmd\.extend\(job\["remote_inputs"\]\)'
    )

    def repl(match: re.Match) -> str:
        indent = match.group("indent")
        return "\n".join(indent + line if line else line for line in new.splitlines())

    return re.sub(pattern, repl, source, count=1)


def _patch_remote_call_retry(source: str) -> str:
    """Retry result retrieval for the same Modal FunctionCall after a transient disconnect."""
    replacement = textwrap.dedent('''
        function_call = modal_pipeline.spawn(payload)
        for reconnect_attempt in range(2):
            try:
                result = function_call.get(timeout=selection.timeout_minutes * 60)
                break
            except (
                modal.exception.ConnectionError,
                __import__("grpclib.exceptions", fromlist=["StreamTerminatedError"]).StreamTerminatedError,
            ):
                if reconnect_attempt >= 1:
                    raise
                logging.warning("Modal connection interrupted; retrying the same function call in 5 seconds")
                __import__("time").sleep(5)
    ''').strip()
    pattern = r'(?P<indent>[ \t]*)result = modal_pipeline\.remote\(payload\)'

    def repl(match: re.Match) -> str:
        indent = match.group("indent")
        return "\n".join(indent + line if line else line for line in replacement.splitlines())

    return re.sub(pattern, repl, source)


class ModalRunner:
    def __init__(self, config: AppConfig, cache_dir: Path):
        self.config = config
        self.cache_dir = cache_dir

    def run(self, audio_path: Path, output_dir: Path, formats: list[str], timeout_seconds: int | None = None) -> ModalResult:
        """All-in-one blocking run (kept for backward compatibility)."""
        handle = self.launch(audio_path, output_dir, formats, timeout_seconds)
        handle.wait_for_submit()
        return handle.wait(timeout_seconds=modal_client_wait_timeout(timeout_seconds or self.config.default_timeout_seconds))

    def launch(self, audio_path: Path, output_dir: Path, formats: list[str], timeout_seconds: int | None = None, model: str | None = None) -> ModalRunHandle:
        """Launch Modal bridge script, return handle after local prep work is done."""
        if not self.config.modal_token_id or not self.config.modal_token_secret:
            raise RuntimeError("Modal token is missing. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")
        if shutil.which("git") is None:
            raise RuntimeError("git is not installed in this container")

        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = self.cache_dir / "modal-repo"
        self._ensure_repo(work_dir)
        self._patch_modal_infer(work_dir)
        self._configure_smart_vad(work_dir)
        bridge = self._write_bridge_script(work_dir)

        env = os.environ.copy()
        env["MODAL_TOKEN_ID"] = self.config.modal_token_id
        env["MODAL_TOKEN_SECRET"] = self.config.modal_token_secret
        if self.config.hf_token:
            env["HF_TOKEN"] = self.config.hf_token

        before = self._snapshot(output_dir, formats)
        command = [
            "python",
            str(bridge),
            "--repo-dir",
            str(work_dir),
            "--audio-path",
            str(audio_path),
            "--output-dir",
            str(output_dir),
            "--gpu",
            self.config.default_gpu,
            "--model",
            model or self.config.default_model,
            "--formats",
            ",".join(formats),
            "--timeout-minutes",
            str(max(1, int((timeout_seconds or self.config.default_timeout_seconds) / 60))),
            "--repo-ref",
            self.config.repo_branch,
            "--enable-smart-vad",
            "true" if self.config.enable_smart_vad else "false",
        ]
        proc = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return ModalRunHandle(proc, output_dir, formats, before)

    def _ensure_repo(self, work_dir: Path) -> None:
        if (work_dir / ".git").exists():
            import time as _time
            stamp = work_dir / ".git" / "last_fetch"
            now = _time.time()
            last_ref = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
            if last_ref == self.config.repo_branch and stamp.exists() and now - stamp.stat().st_mtime < 3600:
                return  # skip fetch if done within the last hour
            subprocess.run(["git", "fetch", "--depth", "1", "origin", self.config.repo_branch], cwd=work_dir, check=True)
            subprocess.run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=work_dir, check=True)
            stamp.write_text(self.config.repo_branch, encoding="utf-8")
            return
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", self.config.repo_url, str(work_dir)],
            check=True,
        )
        subprocess.run(["git", "fetch", "--depth", "1", "origin", self.config.repo_branch], cwd=work_dir, check=True)
        subprocess.run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=work_dir, check=True)
        (work_dir / ".git" / "last_fetch").write_text(self.config.repo_branch, encoding="utf-8")

    def _patch_modal_infer(self, work_dir: Path) -> None:
        target = work_dir / "modal_infer.py"
        if not target.exists():
            raise RuntimeError(f"modal_infer.py not found under repo dir: {work_dir}")
        source = target.read_text(encoding="utf-8")

        patched = _patch_remote_repo_ref(source)
        patched = _patch_remote_smart_vad_arg(patched)
        patched = _patch_remote_call_retry(patched)

        if _all_apps_have_include_source(patched):
            if patched != source:
                target.write_text(patched, encoding="utf-8")
            return

        for match in reversed(list(re.finditer(r"\bmodal\.App\s*\(", patched))):
            start = match.end() - 1
            if _paren_block_has_include_source(patched, start):
                continue
            close = _find_matching_paren(patched, start)
            args_content = patched[start + 1 : close].strip()
            if args_content:
                insertion = (
                    ",\n    include_source=True"
                    if not args_content.rstrip().endswith(",")
                    else "\n    include_source=True,"
                )
                patched = patched[:close] + insertion + patched[close:]
            else:
                patched = patched[:close] + "include_source=True" + patched[close:]

        target.write_text(patched, encoding="utf-8")

    def _configure_smart_vad(self, work_dir: Path) -> None:
        """Toggle smart VAD in upstream ChickenRice config when that version supports it."""
        if not self._supports_smart_vad(work_dir):
            return

        target = work_dir / "generation_config.json5"
        if not target.exists():
            return

        enabled = "true" if self.config.enable_smart_vad else "false"
        source = target.read_text(encoding="utf-8")
        pattern = r'("smart_split_with_vad"\s*:\s*)(true|false)'
        if re.search(pattern, source):
            patched = re.sub(pattern, rf"\g<1>{enabled}", source, count=1)
        else:
            close = source.rfind("}")
            if close == -1:
                return
            prefix = source[:close].rstrip()
            separator = "," if not prefix.endswith("{") else ""
            patched = source[:close].rstrip() + f'{separator}\n    "smart_split_with_vad": {enabled},\n' + source[close:]

        if patched != source:
            target.write_text(patched, encoding="utf-8")

    @staticmethod
    def _supports_smart_vad(work_dir: Path) -> bool:
        candidates = [
            work_dir / "src" / "faster_whisper_transwithai_chickenrice" / "infer.py",
            work_dir / "infer.py",
        ]
        for candidate in candidates:
            if candidate.exists() and "smart_split_with_vad" in candidate.read_text(encoding="utf-8", errors="ignore"):
                return True
        return False

    def _write_bridge_script(self, repo_dir: Path) -> Path:
        bridge = self.cache_dir / "modal_web_entry.py"
        bridge.parent.mkdir(parents=True, exist_ok=True)
        bridge.write_text(textwrap.dedent(r'''
            import argparse
            import sys
            import time
            from pathlib import Path

            def log_stage(stage):
                print(f"[modal_stage] {stage}", flush=True)

            def parse_args():
                parser = argparse.ArgumentParser()
                parser.add_argument("--repo-dir", required=True)
                parser.add_argument("--audio-path", required=True)
                parser.add_argument("--output-dir", required=True)
                parser.add_argument("--gpu", required=True)
                parser.add_argument("--model", required=True)
                parser.add_argument("--formats", required=True)
                parser.add_argument("--timeout-minutes", type=int, default=120)
                parser.add_argument("--repo-ref", required=True)
                parser.add_argument("--enable-smart-vad", choices=("true", "false"), required=True)
                return parser.parse_args()

            def main():
                args = parse_args()
                repo_dir = Path(args.repo_dir).resolve()

                log_stage("import_modal")
                sys.path.insert(0, str(repo_dir))
                import modal
                import modal_infer

                log_stage("patch_build_image")
                _original_build = modal_infer.build_modal_image
                repo = str(repo_dir)
                def _patched_build():
                    image = _original_build()
                    return image.add_local_dir(
                        repo, remote_path="/modal_infer_src", copy=True
                    ).env({"PYTHONPATH": "/modal_infer_src:${PYTHONPATH}"})
                modal_infer.build_modal_image = _patched_build
                print("[modal_stage] patch_build_image_done", flush=True)

                log_stage("validate_model")

                # 自动注入 jim-ja-transcribe（兼容旧版 ChickenRice 无此预设）
                if "jim-ja-transcribe" not in modal_infer.MODEL_PRESETS:
                    try:
                        modal_infer.MODEL_PRESETS["jim-ja-transcribe"] = modal_infer.ModelProfile(
                            key="jim-ja-transcribe",
                            label="TransWithAI \u65e5\u6587\u8f6c\u5f55\uff08whisper-ja-1.5B bf16\uff09",
                            hf_repo="TransWithAI/whisper-ja-1.5B-ct2",
                            target_dir="whisper-ja-1.5B-ct2",
                            description="\u65e5\u6587\u539f\u6587\u8f6c\u5f55 bf16 \u6a21\u578b",
                            task="transcribe",
                        )
                    except TypeError:
                        modal_infer.MODEL_PRESETS["jim-ja-transcribe"] = modal_infer.ModelProfile(
                            key="jim-ja-transcribe",
                            label="TransWithAI \u65e5\u6587\u8f6c\u5f55\uff08whisper-ja-1.5B bf16\uff09",
                            hf_repo="TransWithAI/whisper-ja-1.5B-ct2",
                            target_dir="whisper-ja-1.5B-ct2",
                            description="\u65e5\u6587\u539f\u6587\u8f6c\u5f55 bf16 \u6a21\u578b",
                        )

                if args.model not in modal_infer.MODEL_PRESETS:
                    available = ", ".join(sorted(modal_infer.MODEL_PRESETS))
                    raise RuntimeError(f"Model preset {args.model!r} not found. Available presets: {available}")

                profile = modal_infer.MODEL_PRESETS[args.model]
                modal_infer.SUB_FORMATS = args.formats
                modal_infer.SUB_SUFFIXES = {"." + item.strip().lstrip(".") for item in args.formats.split(",") if item.strip()}

                selection = modal_infer.UserSelection(
                    run_mode="once",
                    gpu_choice=args.gpu,
                    input_path=Path(args.audio_path),
                    model_profile=profile,
                    custom_repo=None,
                    custom_target_dir=None,
                    enable_batching=False,
                    batch_size=None,
                    max_batch_size=8,
                    timeout_minutes=args.timeout_minutes,
                )

                output_dir = Path(args.output_dir)

                log_stage("volume_connect")
                volume = modal.Volume.from_name(modal_infer.VOLUME_NAME, create_if_missing=True)

                log_stage("upload_audio")
                manifest = modal_infer.upload_single_file(volume, selection, selection.input_path, output_dir)

                log_stage("build_payload")
                payload = modal_infer.build_job_payload(selection, manifest)
                payload["repo_ref"] = args.repo_ref
                payload["smart_split_with_vad"] = args.enable_smart_vad == "true"
                payload["supports_smart_vad"] = any(
                    candidate.exists() and "smart_split_with_vad" in candidate.read_text(encoding="utf-8", errors="ignore")
                    for candidate in (
                        repo_dir / "src" / "faster_whisper_transwithai_chickenrice" / "infer.py",
                        repo_dir / "infer.py",
                    )
                )

                log_stage("run_remote_pipeline")
                result = modal_infer.run_remote_pipeline(volume, selection, manifest, payload)

                log_stage("download_outputs")
                modal_infer.download_outputs(manifest, result)

                log_stage("done")
                return 0

            if __name__ == "__main__":
                raise SystemExit(main())
        '''), encoding="utf-8")
        return bridge

    @staticmethod
    def _snapshot(output_dir: Path, formats: list[str]) -> dict[Path, float]:
        """Snapshot output dir: returns {path: mtime} for matching files."""
        suffixes = {"." + fmt.strip().lstrip(".").lower() for fmt in formats}
        if not output_dir.exists():
            return {}
        return {path: path.stat().st_mtime for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in suffixes}
