using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Library;
using MediaBrowser.Controller.Plugins;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Serialization;

namespace Emby.SubtitleAssistant.Migration;

public sealed class MigrationEntryPoint : IServerEntryPoint
{
    private readonly IJsonSerializer _json;
    private readonly ILibraryManager _libraries;
    private readonly ILogger _logger;
    public MigrationEntryPoint(IJsonSerializer json, ILibraryManager libraries, ILogManager logs)
    { _json = json; _libraries = libraries; _logger = logs.GetLogger(GetType().Name); }
    public void Dispose() { }
    public void Run()
    {
        var plugin = Plugin.Instance;
        if (plugin == null || (plugin.Configuration.MigrationVersion >= 1 && !File.Exists(Path.Combine(Path.GetDirectoryName(plugin.ConfigurationFilePath), MigrationRunner.PendingFilename)))) return;
        try
        {
            var targets = new List<MigrationLibrary>();
            var folders = _libraries.GetVirtualFolders();
            if (folders == null) throw new MigrationException("媒体库尚未准备完成，迁移不能标记成功。");
            foreach (var info in folders)
            {
                var id = info.ItemId ?? info.Id;
                BaseItem item = null;
                if (long.TryParse(id, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number)) item = _libraries.GetItemById(number);
                else if (Guid.TryParse(id, out var guid)) item = _libraries.GetItemById(guid);
                if (!(item is CollectionFolder folder)) throw new MigrationException("无法读取媒体库的原生配置。");
                targets.Add(new MigrationLibrary(id, folder.GetLibraryOptions(), folder.UpdateLibraryOptions));
            }
            if (MigrationRunner.Execute(plugin.ConfigurationFilePath, plugin.Configuration, _json, targets, plugin.UpdateConfiguration))
                _logger.Info("Subtitle assistant legacy settings and library source migration completed.");
        }
        catch (Exception ex)
        {
            // Native/serializer errors can contain configuration text or tokens; never log them.
            _logger.Warn("Subtitle assistant migration remains incomplete ({0}); original settings and server-side backups are retained.", ex.GetType().Name);
        }
    }
}
