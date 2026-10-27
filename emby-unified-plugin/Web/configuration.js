define(["baseView"], function (BaseView) {
    "use strict";

    function readPath(object, path) { return path.split(".").reduce(function (value, key) { return value && value[key]; }, object); }
    function writePath(object, path, value) {
        var keys = path.split("."), target = object;
        keys.slice(0, -1).forEach(function (key) { target = target[key] || (target[key] = {}); });
        target[keys[keys.length - 1]] = value;
    }
    function request(path, method, payload) {
        var options = { type: method || "GET", url: ApiClient.getUrl("SubtitleAssistant/" + path), dataType: "json" };
        if (payload !== undefined) { options.contentType = "application/json"; options.data = JSON.stringify(payload); }
        return ApiClient.ajax(options);
    }

    function View(view) {
        BaseView.apply(this, arguments);
        this.view = view; this.activeTab = "local"; this.active = false; this.admin = false; this.settings = null;
        this.form = view.querySelector("[data-settings-form]"); this.timer = null; this.polling = false;
        var self = this;
        this.onSubmit = function (event) { self.save(event).catch(function () {}); }; this.onClick = this.click.bind(this); this.onKeyDown = this.keyDown.bind(this);
        this.form.addEventListener("submit", this.onSubmit); view.addEventListener("click", this.onClick); view.addEventListener("keydown", this.onKeyDown);
    }
    Object.assign(View.prototype, BaseView.prototype);

    View.prototype.status = function (text) { this.view.querySelector("[data-status]").textContent = text; };
    View.prototype.fill = function (settings) {
        this.settings = settings;
        this.view.querySelector("[data-version]").textContent = settings.Version || "—";
        this.form.querySelectorAll("[data-field]").forEach(function (field) {
            var secret = field.getAttribute("data-secret");
            if (secret) {
                field.value = "";
                field.placeholder = readPath(settings, secret) ? "已保存，留空保留" : "未设置";
                return;
            }
            var value = readPath(settings, field.getAttribute("data-field"));
            if (field.type === "checkbox") field.checked = !!value;
            else field.value = value === undefined || value === null ? "" : String(value);
        });
        this.form.querySelectorAll("[data-clear]").forEach(function (field) { field.checked = false; });
    };
    View.prototype.patch = function () {
        var result = {}, settings = this.settings;
        this.form.querySelectorAll("[data-field]").forEach(function (field) {
            var path = field.getAttribute("data-field"), value = field.type === "checkbox" ? field.checked : field.value;
            if (field.getAttribute("data-secret")) { if (value) writePath(result, path, value); return; }
            if (field.type === "number") {
                value = Number(value);
                if (!Number.isInteger(value) || value < 1) throw Error("数量和超时必须是正整数。");
            }
            if (readPath(settings, path) !== value) writePath(result, path, value);
        });
        this.form.querySelectorAll("[data-clear]").forEach(function (field) {
            if (field.checked) writePath(result, field.getAttribute("data-clear"), true);
        });
        return result;
    };
    View.prototype.save = function (event) {
        if (event) event.preventDefault();
        var self = this;
        if (!self.admin || !self.settings) return Promise.reject(Error("仅限管理员。"));
        var patch;
        try { patch = self.patch(); } catch (error) { self.status(error.message); return Promise.reject(error); }
        self.status("正在保存…");
        return request("settings", "POST", patch).then(function (result) {
            if (!result.Ok) throw Error(result.Error || "保存失败。");
            if (self.active) { self.fill(result.Settings); self.status("设置已保存。"); }
            return result;
        }).catch(function (error) { if (self.active) self.status("保存失败，请检查设置和管理员登录状态。"); throw error; });
    };
    View.prototype.selectTab = function (tab) {
        this.activeTab = tab;
        this.view.querySelectorAll("[data-tab]").forEach(function (button) {
            var selected = button.getAttribute("data-tab") === tab;
            button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
        });
        this.view.querySelectorAll("[data-panel]").forEach(function (panel) { panel.hidden = panel.getAttribute("data-panel") !== tab; });
        this.startPolling();
    };
    View.prototype.keyDown = function (event) {
        if (!event.target.hasAttribute("data-tab") || ["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(event.key) < 0) return;
        event.preventDefault();
        var buttons = Array.prototype.slice.call(this.view.querySelectorAll("[data-tab]")), index = buttons.indexOf(event.target);
        index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        this.selectTab(buttons[index].getAttribute("data-tab")); buttons[index].focus();
    };
    View.prototype.click = function (event) {
        var self = this, target = event.target.closest("button");
        if (!target || !self.admin) return;
        if (target.hasAttribute("data-tab")) self.selectTab(target.getAttribute("data-tab"));
        if (target.hasAttribute("data-refresh-jobs")) self.pollJobs();
        if (target.hasAttribute("data-proxy-test")) {
            self.save().then(function () {
                self.status("正在测试已保存的流量路由…");
                return request("proxy/test", "POST", { Url: self.view.querySelector("[data-proxy-test-url]").value, Purpose: self.view.querySelector("[data-proxy-purpose]").value });
            }).then(function (result) { if (self.active) self.status(result.Ok ? "连接成功。" : result.Error || "连接失败。"); }).catch(function () { if (self.active) self.status("测试未完成，请检查设置和管理员登录状态。"); });
        }
        if (target.hasAttribute("data-update")) {
            self.status("正在启动更新任务…");
            ApiClient.ajax({ type: "GET", url: ApiClient.getUrl("ScheduledTasks"), dataType: "json" }).then(function (tasks) {
                var task = tasks.filter(function (entry) { return entry.Key === "SubtitleAssistantUpdate"; })[0];
                if (!task) throw Error("任务不存在");
                return ApiClient.ajax({ type: "POST", url: ApiClient.getUrl("ScheduledTasks/Running/" + task.Id) });
            }).then(function () { if (self.active) self.status("更新任务已启动，需要重启时由 Emby 提示。"); }).catch(function () { if (self.active) self.status("无法启动更新，请前往 Emby 计划任务查看。"); });
        }
    };
    View.prototype.pollJobs = function () {
        var self = this;
        if (!self.active || !self.admin || self.polling || self.activeTab !== "cloud" || document.hidden) return;
        self.polling = true;
        request("cloud/jobs").then(function (result) {
            if (!self.active) return;
            if (!result.Ok) throw Error("连接失败");
            var jobs = (result.Jobs || []).sort(function (a, b) { return b.UpdatedAt - a.UpdatedAt; });
            ["active", "done", "failed"].forEach(function (group) {
                var body = self.view.querySelector('[data-jobs="' + group + '"]');
                body.textContent = "";
                var selected = jobs.filter(function (job) { return group === "active" ? ["queued", "running", "cancelling"].indexOf(job.Status) >= 0 : job.Status === group; });
                if (group !== "active") selected = selected.slice(0, 5);
                selected.forEach(function (job) {
                    var row = document.createElement("tr");
                    [job.Title || job.Id, job.Status, job.Phase, String(job.Progress || 0) + "%", job.Message].forEach(function (text) {
                        var cell = document.createElement("td"); cell.textContent = text || ""; row.appendChild(cell);
                    });
                    body.appendChild(row);
                });
            });
            self.view.querySelector("[data-jobs-status]").textContent = "";
        }).catch(function () { if (self.active) self.view.querySelector("[data-jobs-status]").textContent = "无法获取任务，请检查字幕云服务配置。"; }).then(function () { self.polling = false; });
    };
    View.prototype.startPolling = function () {
        var self = this;
        clearInterval(self.timer); self.timer = null;
        if (self.active && self.admin && self.activeTab === "cloud") { self.pollJobs(); self.timer = setInterval(function () { self.pollJobs(); }, 5000); }
    };
    View.prototype.onResume = function () {
        BaseView.prototype.onResume.apply(this, arguments);
        var self = this; self.active = true; self.admin = false; self.form.hidden = true;
        ApiClient.getCurrentUser().then(function (user) {
            if (!self.active) return;
            self.admin = !!(user && user.Policy && user.Policy.IsAdministrator);
            self.view.querySelector("[data-admin-warning]").hidden = self.admin;
            if (!self.admin) return;
            return request("settings").then(function (settings) {
                if (!self.active) return;
                self.fill(settings); self.form.hidden = false; self.startPolling();
            });
        }).catch(function () { if (self.active) self.view.querySelector("[data-admin-warning]").hidden = false; });
    };
    View.prototype.onPause = function () {
        this.active = false; this.admin = false; clearInterval(this.timer); this.timer = null;
        BaseView.prototype.onPause.apply(this, arguments);
    };
    View.prototype.destroy = function () {
        this.active = false; clearInterval(this.timer);
        this.form.removeEventListener("submit", this.onSubmit); this.view.removeEventListener("click", this.onClick); this.view.removeEventListener("keydown", this.onKeyDown);
        BaseView.prototype.destroy.apply(this, arguments);
    };
    return View;
});
