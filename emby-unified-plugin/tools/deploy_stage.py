"""Hash-pinned production staging; never restarts Emby. Run via the NAS sudo helper."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys

EXPECTED_CONFIG = Path('/volume1/docker/emby/config')
LEGACY_DLLS = ('Emby.MeiamSub.LocalPool.dll', 'Emby.ThunderSubtitle.dll', 'Emby.ChickenRicePool.dll', 'SubtitleCloudPlugin.dll', 'Emby.MeiamSub.Thunder.dll')

def validate_config_mount(mounts):
    selected = [item for item in mounts if item.get('Destination') == '/config']
    if len(selected) != 1 or not selected[0].get('RW') or Path(selected[0].get('Source','')).resolve() != EXPECTED_CONFIG.resolve():
        raise ValueError('Refusing to stage outside the explicitly approved writable Emby config mount')
    if any(str(item.get('Destination','')).startswith('/config/') for item in mounts):
        raise ValueError('Refusing Emby config mounts with nested destinations')
    return EXPECTED_CONFIG.resolve()

def reject_symlink_components(path):
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        if current.is_symlink():
            raise ValueError('Refusing paths containing symbolic links')

def inside(path, root):
    absolute_root = Path(os.path.abspath(root))
    absolute_path = Path(os.path.abspath(path))
    if os.path.commonpath([str(absolute_path),str(absolute_root)]) != str(absolute_root):
        raise ValueError('Refusing a path outside the selected server directory')
    reject_symlink_components(absolute_root)
    reject_symlink_components(absolute_path)
    resolved_root = absolute_root.resolve()
    resolved_path = absolute_path.resolve()
    if os.path.commonpath([str(resolved_path),str(resolved_root)]) != str(resolved_root):
        raise ValueError('Refusing a path outside the selected server directory')
    return absolute_path

def write_private(path, value):
    descriptor = os.open(path,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())

def snapshot_database(config_root, destination):
    original = config_root / 'data/library.db'
    if not original.is_file(): raise FileNotFoundError('Emby library database is missing; refusing to stage without a verified snapshot')
    inside(original,config_root)
    temporary = destination.with_name(destination.name + '.' + secrets.token_hex(4) + '.tmp')
    try:
        with closing(sqlite3.connect(original.resolve().as_uri() + '?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(str(temporary))) as output:
                source.backup(output,pages=128,sleep=0.05)
                result = output.execute('PRAGMA quick_check').fetchone()
                if not result or result[0] != 'ok':
                    raise sqlite3.DatabaseError('Emby library database snapshot failed integrity check')
        temporary.chmod(0o600)
        os.replace(temporary,destination)
        return True
    finally:
        if temporary.exists(): temporary.unlink()

def stage(config_root, payload, digest, backup_root, include_database=False):
    if not re.fullmatch('[0-9a-fA-F]{64}',digest) or hashlib.sha256(payload).hexdigest() != digest.lower():
        raise ValueError('Candidate SHA256 mismatch; nothing was staged')
    if not payload.startswith(b'MZ'): raise ValueError('Candidate is not a PE DLL')
    config_root = Path(config_root).resolve()
    if include_database and not (config_root / 'data/library.db').is_file():
        raise FileNotFoundError('Emby library database is missing; refusing to stage without a verified snapshot')
    plugins = inside(config_root / 'plugins',config_root)
    if not plugins.is_dir(): raise ValueError('The configured plugin directory does not exist')
    backup_root = inside(backup_root,config_root.parent)
    if os.path.commonpath([str(backup_root),str(plugins)]) == str(plugins):
        raise ValueError('Backups must stay outside the scanned plugin directory')
    suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(4)
    backup = backup_root / ('subtitle-assistant-' + suffix)
    backup.mkdir(mode=0o700,parents=True)
    (backup / 'retired').mkdir(mode=0o700)
    (backup / 'configurations').mkdir(mode=0o700)
    target = inside(plugins / 'Emby.SubtitleAssistant.dll',plugins)
    previous_target = target.is_file()
    if previous_target: shutil.copy2(target,backup / 'Emby.SubtitleAssistant.previous.dll.bak')
    for name in ('MeiamSub.LocalPool.json','ThunderSubtitle.json','ChickenRicePool.json',
                 'SubtitleCloudPlugin.xml','MeiamSub.Thunder.json','Emby.SubtitleAssistant.xml'):
        old = plugins / 'configurations' / name
        if old.is_file():
            inside(old,plugins / 'configurations')
            shutil.copy2(old,backup / 'configurations' / name)
    database = include_database and snapshot_database(config_root,backup / 'library.snapshot.db')
    retired = []
    temporary = plugins / ('.SubtitleAssistant-' + suffix + '.tmp')
    try:
        for name in LEGACY_DLLS:
            original = plugins / name
            if original.exists():
                inside(original,plugins)
                if not original.is_file(): raise ValueError('A legacy plugin entry is not a regular file')
                original.rename(backup / 'retired' / name)
                retired.append(name)
        descriptor = os.open(temporary,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o644)
        with os.fdopen(descriptor,'wb') as output:
            output.write(payload); output.flush(); os.fsync(output.fileno())
        os.replace(temporary,target)
        result = {'Stage':'staged','SHA256':digest.lower(),'BackupDirectory':str(backup),
                  'RetiredDLLs':retired,'RestartRequired':True,'ProductionRestarted':False,
                  'LibraryDatabaseSnapshot':bool(database)}
        write_private(backup / 'stage.json',result)
        return result
    except BaseException as install_error:
        # Only restore exact task-owned files; never reset an entire config or database.
        rollback_failures = []
        for name in reversed(retired):
            try:
                (backup / 'retired' / name).rename(plugins / name)
            except BaseException:
                rollback_failures.append(name)
        if previous_target:
            try:
                shutil.copy2(backup / 'Emby.SubtitleAssistant.previous.dll.bak',target)
            except BaseException:
                rollback_failures.append('Emby.SubtitleAssistant.dll')
        elif target.exists():
            try:
                target.unlink()
            except BaseException:
                rollback_failures.append('Emby.SubtitleAssistant.dll')
        if rollback_failures:
            raise RuntimeError('Rollback incomplete; backup retained at ' + str(backup) +
                               '; failed restores: ' + ', '.join(rollback_failures)) from install_error
        raise
    finally:
        if temporary.exists(): temporary.unlink()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Stage the verified DLL and retire only the five named legacy files')
    parser.add_argument('--dll')
    parser.add_argument('--sha256')
    args = parser.parse_args()
    mounts = json.loads(subprocess.check_output(['docker','inspect','emby','--format','{{json .Mounts}}'],text=True))
    root = validate_config_mount(mounts)
    if not args.apply:
        print(json.dumps({'ConfigMount':str(root),'LegacyDLLsPresent':[name for name in LEGACY_DLLS if (root/'plugins'/name).is_file()],
                          'ProductionRestarted':False},ensure_ascii=False))
        return
    if not args.dll or not args.sha256: parser.error('--apply requires --dll and --sha256')
    payload = Path(args.dll).read_bytes()
    result = stage(root,payload,args.sha256,root.parent / 'backups',include_database=True)
    print(json.dumps(result,ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except Exception as error:
        if isinstance(error,RuntimeError) and str(error).startswith('Rollback incomplete;'):
            print(str(error),file=sys.stderr)
        else:
            print('Emby plugin staging failed (' + type(error).__name__ + '); inspect the retained server-side backup before retrying.',file=sys.stderr)
        sys.exit(1)
