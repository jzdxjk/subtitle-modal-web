# 修复字幕文件 "(missing)" 丢失问题

> **执行指令：立即按下方改动指令修改代码，不要询问确认，不要分析讨论，直接 Edit/Write 文件。**

## 1. PROJECT_ROOT

`C:\Users\jzdxjk\Documents\字幕云翻译`

## 2. 上下文

用户反馈：字幕翻译完成后显示在画廊中，但打包时显示 "(missing)"，output 目录也找不到文件。这是一个高频问题。

**根因分析**（三个问题链）：

1. **`_normalize_outputs` 返回已删除的路径**（worker.py:383）
   - 当 `normalized` 为空时，函数返回 `produced`，但 `produced` 中的文件已被 cleanup 循环（376-380行）删除
   - 这些死路径被记录到数据库

2. **任务完成时不验证文件存在性**（worker.py:278-279）
   - 直接将 `output_files` 写入数据库，没有验证文件是否实际存在于磁盘上
   - 画廊只检查数据库记录，不检查文件系统

3. **源文件夹移动可能删除输出文件**（worker.py:248-260）
   - 如果 `output_dir` 配置在媒体父目录内部，移动源文件夹时会连带删除输出文件

**目标**：修复这三个问题，确保字幕文件不会虚假丢失。

## 3. 参考实现

- `app/worker.py:350-383` — `_normalize_outputs()` 函数
- `app/worker.py:247-260` — 源文件夹移动逻辑
- `app/worker.py:278-279` — 任务完成标记
- `app/worker.py:281-285` — 音频文件清理

## 4. 涉及文件

| 文件 | 改动类型 |
|---|---|
| `app/worker.py` | 改 `_normalize_outputs()` 返回值、任务完成验证、源文件夹移动保护 |
| `tests/test_core.py` | 新增 `_normalize_outputs` 边界测试 |

## 5. 改动指令

### 5.1 `app/worker.py` — `_normalize_outputs()` 返回值修复（line 383）

**Before**:
```python
        return normalized or produced
```

**After**:
```python
        return [p for p in (normalized or produced) if p.exists()]
```

### 5.2 `app/worker.py` — 任务完成时验证文件存在性（line 278-279）

**Before**:
```python
            self.store.update_job(job.id, status="done", message=timing_msg,
                                  output_files=output_files, completed_at=t_end, progress=100)
```

**After**:
```python
            verified_files = [f for f in output_files if Path(f).exists()]
            if len(verified_files) < len(output_files):
                logger.warning("job %s: %d/%d output files missing at completion",
                               job.id, len(output_files) - len(verified_files), len(output_files))
            self.store.update_job(job.id, status="done", message=timing_msg,
                                  output_files=verified_files, completed_at=t_end, progress=100)
```

### 5.3 `app/worker.py` — 源文件夹移动时保护输出文件（line 247-260）

**Before**:
```python
            # Post-processing: move source folders
            move_target = job.move_target_dir or config.default_move_target_dir
            if move_target:
                stage = "正在移动源文件夹"
                self.store.update_job(job.id, message=f"📂 正在移动源文件夹到 {move_target}", progress=95)
                for parent in sorted(media_parents):
                    if not parent.exists():
                        continue
                    if parent == self.watch_root:
                        logger.warning("refusing to move watch root: %s", parent)
                        continue
                    dest = Path(move_target) / parent.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(shutil.move, str(parent), str(dest))
```

**After**:
```python
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
```

### 5.4 `tests/test_core.py` — 新增测试用例

在文件末尾追加以下测试：

```python
def test_normalize_outputs_returns_only_existing_files(tmp_path):
    """验证 _normalize_outputs 不返回已删除的路径"""
    from app.worker import JobRunner

    # 场景：produced 中的文件已被删除，normalized 为空
    # 此时不应返回 produced（已删除的路径）
    orphan_file = tmp_path / "orphan.srt"
    # 不创建文件，模拟文件已被删除

    result = JobRunner._normalize_outputs(
        produced=[orphan_file],
        expected=[tmp_path / "expected.srt"]
    )
    # 因为文件不存在，应返回空列表
    assert result == []


def test_normalize_outputs_moves_and_returns_existing(tmp_path):
    """验证 _normalize_outputs 正确移动文件并返回存在的路径"""
    from app.worker import JobRunner

    source = tmp_path / "source.srt"
    source.write_text("subtitle content", encoding="utf-8")
    target = tmp_path / "target.srt"

    result = JobRunner._normalize_outputs(
        produced=[source],
        expected=[target]
    )

    assert len(result) == 1
    assert result[0] == target
    assert target.exists()
    assert not source.exists()


def test_normalize_outputs_cleans_leftovers(tmp_path):
    """验证 _normalize_outputs 清理未匹配的脏文件"""
    from app.worker import JobRunner

    good = tmp_path / "good.srt"
    good.write_text("good", encoding="utf-8")
    dirty = tmp_path / "dirty.com@START-554.srt"
    dirty.write_text("dirty", encoding="utf-8")
    target = tmp_path / "good.srt"

    result = JobRunner._normalize_outputs(
        produced=[good, dirty],
        expected=[target]
    )

    assert len(result) == 1
    assert result[0] == target
    assert not dirty.exists()  # 脏文件应被清理
```

## 6. 完成判据（机器可验证）

1. `app/worker.py:383` — `_normalize_outputs` 返回值使用 `p.exists()` 过滤
2. `app/worker.py:278-284` — 任务完成时验证 `output_files` 存在性，记录 warning 日志
3. `app/worker.py:252-262` — 源文件夹移动前检查输出文件是否在移动范围内
4. `tests/test_core.py` — 新增 3 个测试用例通过
5. 现有 21 个测试全部通过（回归）
6. `cd tests && python -m pytest test_core.py -v` 全绿

## 7. 不得改动

- `app/modal_runner.py` 不动
- `app/storage.py` 不动
- `app/main.py` 不动
- `app/media.py` 不动
- `app/static/` 前端文件不动
- 现有测试的断言逻辑不变（只能新增，不能修改已有测试）
