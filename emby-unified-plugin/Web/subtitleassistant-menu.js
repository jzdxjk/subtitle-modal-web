define([], function () {
    "use strict";
    return function () {
        if (globalThis.__subtitleAssistantCommandSourceRegistered) return;
        return Promise.all([Emby.importModule("./modules/toast/toast.js"), Emby.importModule("./modules/common/itemmanager/itemmanager.js")]).then(function (modules) {
                if (globalThis.__subtitleAssistantCommandSourceRegistered) return;
                var toast = modules[0].default || modules[0], itemmanager = modules[1].default || modules[1];
                itemmanager.registerCommandSource({
                    getCommands: function (options) {
                        // Emby's command source contract is synchronous; its options carry the current user.
                        var client = options && options.apiClient || ApiClient;
                        var user = options && (options.user || options.users && options.users[client.serverId()]);
                        if (!user || !user.Policy || !user.Policy.IsAdministrator || String(user.Id) !== String(client.getCurrentUserId())) return [];
                        var items = options && (options.items || options.item && [options.item]) || [];
                        if (items.length !== 1 || !(items[0].Type === "Movie" || items[0].Type === "Episode")) return [];
                        return [{ name: "生成云字幕", id: "subtitle_assistant_cloud", icon: "closed_caption" }];
                    },
                    executeCommand: function (command, items, options) {
                        if (command !== "subtitle_assistant_cloud") return;
                        var client = options && options.apiClient || ApiClient;
                        var item = items && items[0];
                        if (!item || !(item.Type === "Movie" || item.Type === "Episode")) return;
                        return client.getCurrentUser().then(function (currentUser) {
                            if (!currentUser || !currentUser.Policy || !currentUser.Policy.IsAdministrator || String(currentUser.Id) !== String(client.getCurrentUserId())) throw Error("管理员登录已失效。");
                            var providers = item.ProviderIds || {}, poster = "";
                            if (item.ImageTags && item.ImageTags.Primary && client.getScaledImageUrl)
                                poster = client.getScaledImageUrl(item.Id, { type: "Primary", tag: item.ImageTags.Primary, maxWidth: 600 });
                            return client.ajax({ type: "POST", url: client.getUrl("SubtitleAssistant/cloud/submit"), contentType: "application/json", dataType: "json",
                                data: JSON.stringify({ ItemId: item.Id, AvCode: providers["AV视频"] || providers.AvCode || "", PosterUrl: poster }) });
                        }).then(function (result) {
                            if (!result || !result.Ok) throw Error("提交失败");
                            toast("云字幕任务已提交。");
                        }).catch(function () { toast("云字幕任务提交失败，请检查管理员登录和字幕云服务配置。"); });
                    }
                });
                globalThis.__subtitleAssistantCommandSourceRegistered = true;
        }).catch(function () { /* The server independently rejects non-administrator operations. */ });
    };
});
