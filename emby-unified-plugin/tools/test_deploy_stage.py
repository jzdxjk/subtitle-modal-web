import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import deploy_stage


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='subtitle-assistant-stage-test-')
        self.root = Path(self.temporary.name).resolve()
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.config = self.root / 'config'
        self.plugins = self.config / 'plugins'
        self.plugins.mkdir(parents=True)
        self.configurations = self.plugins / 'configurations'
        self.configurations.mkdir()
        self.backups = self.root / 'backups'
        self.payload = b'MZ' + bytes(256)
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def tearDown(self):
        self.temporary.cleanup()

    def test_only_expected_writable_production_mount_is_accepted(self):
        mounts = [{'Source':str(deploy_stage.EXPECTED_CONFIG),'Destination':'/config','RW':True}]
        self.assertEqual(deploy_stage.validate_config_mount(mounts),deploy_stage.EXPECTED_CONFIG.resolve())
        for source, writable in [('/volume1/docker/other/config',True),(str(deploy_stage.EXPECTED_CONFIG),False)]:
            with self.assertRaises(ValueError):
                deploy_stage.validate_config_mount([{'Source':source,'Destination':'/config','RW':writable}])
        for destination in ('/config/plugins','/config/data','/config/plugins/configurations'):
            with self.assertRaises(ValueError):
                deploy_stage.validate_config_mount(mounts + [{'Source':'/volume1/other','Destination':destination,'RW':True}])

    def test_stages_one_dll_retires_only_named_legacy_files_and_keeps_configs(self):
        for name in deploy_stage.LEGACY_DLLS: (self.plugins / name).write_bytes(b'old-'+name.encode())
        (self.plugins / 'OtherPlugin.dll').write_bytes(b'unchanged')
        old_configuration = self.configurations / 'SubtitleCloudPlugin.xml'
        old_configuration.write_text('<PluginConfiguration><ApiToken>dummy-secret</ApiToken></PluginConfiguration>')
        result = deploy_stage.stage(self.config,self.payload,self.digest,self.backups)
        self.assertEqual((self.plugins / 'Emby.SubtitleAssistant.dll').read_bytes(),self.payload)
        self.assertTrue(result['RestartRequired'])
        self.assertFalse(result['ProductionRestarted'])
        self.assertEqual(set(result['RetiredDLLs']),set(deploy_stage.LEGACY_DLLS))
        self.assertTrue(old_configuration.exists())
        self.assertEqual((self.plugins / 'OtherPlugin.dll').read_bytes(),b'unchanged')
        self.assertNotIn('dummy-secret',json.dumps(result))
        backup = Path(result['BackupDirectory'])
        for name in deploy_stage.LEGACY_DLLS:
            self.assertFalse((self.plugins / name).exists())
            self.assertEqual((backup / 'retired' / name).read_bytes(),b'old-'+name.encode())

    def test_bad_digest_does_not_create_backups_or_modify_originals(self):
        legacy = self.plugins / deploy_stage.LEGACY_DLLS[0]
        legacy.write_bytes(b'original')
        with self.assertRaises(ValueError): deploy_stage.stage(self.config,self.payload,'0'*64,self.backups)
        self.assertFalse(self.backups.exists())
        self.assertEqual(legacy.read_bytes(),b'original')
        self.assertFalse((self.plugins / 'Emby.SubtitleAssistant.dll').exists())

    def test_failed_install_restores_retired_files_and_original_target(self):
        legacy = self.plugins / deploy_stage.LEGACY_DLLS[0]; legacy.write_bytes(b'legacy')
        target = self.plugins / 'Emby.SubtitleAssistant.dll'; target.write_bytes(b'existing target')
        original_replace = os.replace
        def denied(source,destination):
            if str(source).endswith('.tmp'): raise OSError('simulated replace denied')
            return original_replace(source,destination)
        with patch('deploy_stage.os.replace',side_effect=denied):
            with self.assertRaises(OSError): deploy_stage.stage(self.config,self.payload,self.digest,self.backups)
        self.assertEqual(legacy.read_bytes(),b'legacy')
        self.assertEqual(target.read_bytes(),b'existing target')

    def test_database_snapshot_is_valid_and_contains_a_consistent_copy(self):
        database_directory = self.config / 'data'
        database_directory.mkdir()
        database = database_directory / 'library.db'
        connection = sqlite3.connect(database)
        try:
            connection.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
            connection.execute('INSERT INTO items (name) VALUES (?)',('fixture',))
            connection.commit()
        finally:
            connection.close()
        result = deploy_stage.stage(self.config,self.payload,self.digest,self.backups,include_database=True)
        snapshot = Path(result['BackupDirectory']) / 'library.snapshot.db'
        self.assertTrue(result['LibraryDatabaseSnapshot'])
        connection = sqlite3.connect(snapshot)
        try:
            self.assertEqual(connection.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(connection.execute('SELECT name FROM items').fetchone()[0],'fixture')
        finally:
            connection.close()

    def test_missing_or_corrupt_database_refuses_to_retire_plugins_or_install(self):
        legacy = self.plugins / deploy_stage.LEGACY_DLLS[0]
        legacy.write_bytes(b'legacy')
        with self.assertRaises((FileNotFoundError,ValueError)):
            deploy_stage.stage(self.config,self.payload,self.digest,self.backups,include_database=True)
        self.assertEqual(legacy.read_bytes(),b'legacy')
        self.assertFalse((self.plugins / 'Emby.SubtitleAssistant.dll').exists())
        database_directory = self.config / 'data'
        database_directory.mkdir()
        (database_directory / 'library.db').write_bytes(b'not a sqlite database')
        with self.assertRaises((sqlite3.DatabaseError,ValueError)):
            deploy_stage.stage(self.config,self.payload,self.digest,self.backups,include_database=True)
        self.assertEqual(legacy.read_bytes(),b'legacy')
        self.assertFalse((self.plugins / 'Emby.SubtitleAssistant.dll').exists())

    def test_incomplete_rollback_attempts_every_restore_and_reports_backup(self):
        for name in deploy_stage.LEGACY_DLLS: (self.plugins / name).write_bytes(b'old-'+name.encode())
        target = self.plugins / 'Emby.SubtitleAssistant.dll'
        target.write_bytes(b'previous-assistant')
        previous_write = deploy_stage.write_private
        previous_rename = Path.rename

        def fail_journal(path,value):
            if path.name == 'stage.json': raise OSError('simulated journal failure')
            return previous_write(path,value)

        def fail_one_restore(path,destination):
            if path.name == deploy_stage.LEGACY_DLLS[-1] and path.parent.name == 'retired' and Path(destination).parent == self.plugins:
                raise PermissionError('simulated one-file restore failure')
            return previous_rename(path,destination)

        with patch('deploy_stage.write_private',side_effect=fail_journal), patch.object(Path,'rename',new=fail_one_restore):
            with self.assertRaises(RuntimeError) as failure:
                deploy_stage.stage(self.config,self.payload,self.digest,self.backups)
        self.assertIn('Rollback incomplete',str(failure.exception))
        backup = Path(str(failure.exception).split('backup retained at ',1)[1].split(';',1)[0])
        self.assertTrue(backup.is_dir())
        self.assertEqual(target.read_bytes(),b'previous-assistant')
        for name in deploy_stage.LEGACY_DLLS[:-1]:
            self.assertEqual((self.plugins / name).read_bytes(),b'old-'+name.encode())
        self.assertFalse((self.plugins / deploy_stage.LEGACY_DLLS[-1]).exists())
        self.assertEqual((backup / 'retired' / deploy_stage.LEGACY_DLLS[-1]).read_bytes(),b'old-'+deploy_stage.LEGACY_DLLS[-1].encode())

    def test_symlink_aliases_are_refused_without_touching_their_targets(self):
        other = self.plugins / 'OtherPlugin.dll'
        other.write_bytes(b'untouched')
        assistant = self.plugins / 'Emby.SubtitleAssistant.dll'
        assistant.write_bytes(b'symlink placeholder')
        original_is_symlink = Path.is_symlink
        def mark_assistant_as_symlink(path):
            return path == assistant or original_is_symlink(path)
        with patch.object(Path,'is_symlink',new=mark_assistant_as_symlink):
            with self.assertRaises(ValueError): deploy_stage.stage(self.config,self.payload,self.digest,self.backups)
        self.assertEqual(assistant.read_bytes(),b'symlink placeholder')
        self.assertEqual(other.read_bytes(),b'untouched')

    def test_external_configurations_symlink_is_refused(self):
        (self.configurations / 'SubtitleCloudPlugin.xml').write_text('preserve')
        (self.plugins / deploy_stage.LEGACY_DLLS[0]).write_bytes(b'legacy')
        original_is_symlink = Path.is_symlink
        def mark_configurations_as_symlink(path):
            return path == self.configurations or original_is_symlink(path)
        with patch.object(Path,'is_symlink',new=mark_configurations_as_symlink):
            with self.assertRaises(ValueError): deploy_stage.stage(self.config,self.payload,self.digest,self.backups)
        self.assertEqual((self.configurations / 'SubtitleCloudPlugin.xml').read_text(),'preserve')
        self.assertEqual((self.plugins / deploy_stage.LEGACY_DLLS[0]).read_bytes(),b'legacy')


if __name__ == '__main__': unittest.main()
