from __future__ import annotations

import json
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


class ModalRunHandle:
    """Handle to a running Modal cloud job started via ModalRunner.launch()."""

    def __init__(self, proc: subprocess.Popen, output_dir: Path, formats: list[str], before: dict[Path, float],
                 expected: list[Path] | None = None):
        self._proc = proc
        self._output_dir = output_dir
        self._formats = formats
        self._before = before
        self._expected = expected
        self._submitted_lines: list[str] = []
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
                pass  # 消费掉防止管道死锁

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
            stderr_remainder = self._proc.stderr.read()
            stdout_tail = "\n".join(self._submitted_lines[-30:])
            raise RuntimeError(f"Modal bridge failed before cloud submission:\n{stdout_tail}\n{stderr_remainder}")

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
            if stderr_tail.strip():
                detail += f"\n--- stderr tail ---\n{stderr_tail.strip()}"
            raise RuntimeError(f"Modal run failed at stage [{last_stage}]: {detail}")

        after = ModalRunner._snapshot(self._output_dir, self._formats, self._expected)
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


class ModalRunner:
    def __init__(self, config: AppConfig, cache_dir: Path):
        self.config = config
        self.cache_dir = cache_dir

    def run(self, audio_path: Path, output_dir: Path, formats: list[str], timeout_seconds: int | None = None) -> ModalResult:
        """All-in-one blocking run (kept for backward compatibility)."""
        handle = self.launch(audio_path, output_dir, formats, timeout_seconds)
        handle.wait_for_submit()
        return handle.wait(timeout_seconds=(timeout_seconds or self.config.default_timeout_seconds) + 300)

    def launch(self, audio_path: Path, output_dir: Path, formats: list[str], timeout_seconds: int | None = None,
               expected: list[Path] | None = None) -> ModalRunHandle:
        """Launch Modal bridge script, return handle after local prep work is done."""
        if not self.config.modal_token_id or not self.config.modal_token_secret:
            raise RuntimeError("Modal token is missing. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")
        if shutil.which("git") is None:
            raise RuntimeError("git is not installed in this container")

        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = self.cache_dir / "modal-repo"
        self._ensure_repo(work_dir)
        self._patch_modal_infer(work_dir)
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
            self.config.default_model,
            "--formats",
            ",".join(formats),
            "--timeout-minutes",
            str(max(1, int((timeout_seconds or self.config.default_timeout_seconds) / 60))),
        ]
        proc = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return ModalRunHandle(proc, output_dir, formats, before, expected)

    def _ensure_repo(self, work_dir: Path) -> None:
        if (work_dir / ".git").exists():
            import time as _time
            stamp = work_dir / ".git" / "last_fetch"
            now = _time.time()
            if stamp.exists() and now - stamp.stat().st_mtime < 3600:
                return  # skip fetch if done within the last hour
            subprocess.run(["git", "fetch", "--depth", "1", "origin", self.config.repo_branch], cwd=work_dir, check=False)
            subprocess.run(["git", "checkout", self.config.repo_branch], cwd=work_dir, check=False)
            subprocess.run(["git", "pull", "--ff-only"], cwd=work_dir, check=False)
            stamp.write_text(str(now))
            return
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", self.config.repo_branch, self.config.repo_url, str(work_dir)],
            check=True,
        )

    def _patch_modal_infer(self, work_dir: Path) -> None:
        target = work_dir / "modal_infer.py"
        if not target.exists():
            raise RuntimeError(f"modal_infer.py not found under repo dir: {work_dir}")
        source = target.read_text(encoding="utf-8")

        if _all_apps_have_include_source(source):
            return

        patched = source
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
    def _snapshot(output_dir: Path, formats: list[str], expected: list[Path] | None = None) -> dict[Path, float]:
        """Snapshot output dir: returns {path: mtime} for matching files.
        If expected is given, only track those specific files (scoped snapshot).
        """
        if expected is not None:
            return {p: p.stat().st_mtime if p.exists() else 0.0 for p in expected}
        suffixes = {"." + fmt.strip().lstrip(".").lower() for fmt in formats}
        if not output_dir.exists():
            return {}
        return {path: path.stat().st_mtime for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in suffixes}