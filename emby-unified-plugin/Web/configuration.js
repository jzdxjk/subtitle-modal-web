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

    var PROVIDER_LABELS = { Local: "本地字幕", Thunder: "迅雷字幕" };
    var PROVIDER_DEFAULT_ORDER = ["Local", "Thunder"];
    function providerLabel(key) { return PROVIDER_LABELS[key] || key; }

    function View(view) {
        BaseView.apply(this, arguments);
        this.view = view; this.activeTab = "local"; this.active = false; this.admin = false; this.settings = null;
        this.form = view.querySelector("[data-settings-form]"); this.timer = null; this.polling = false;
        this.proxyResult = view.querySelector("[data-proxy-result]"); this.unsaved = view.querySelector("[data-unsaved]");
        var self = this;
        this.onSubmit = function (event) { self.save(event).catch(function () {}); };
        this.onClick = this.click.bind(this); this.onKeyDown = this.keyDown.bind(this);
        this.onInput = function () { self.updateDirty(); };
        this.onResize = function () { self.updateTabOverflow(); };
        this.form.addEventListener("submit", this.onSubmit);
        this.form.addEventListener("input", this.onInput);
        this.form.addEventListener("change", this.onInput);
        view.addEventListener("click", this.onClick);
        view.addEventListener("keydown", this.onKeyDown);
        window.addEventListener("resize", this.onResize);
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
        this.providerOrder = (settings.ProviderDisplayOrder && settings.ProviderDisplayOrder.length ? settings.ProviderDisplayOrder : PROVIDER_DEFAULT_ORDER).slice();
        this.renderOrder();
        this.updateDirty();
        this.updateTabOverflow();
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
        var order = this.providerOrder || [];
        var savedOrder = (settings && settings.ProviderDisplayOrder) || [];
        var orderChanged = order.length !== savedOrder.length || order.some(function (key, index) { return key !== savedOrder[index]; });
        if (orderChanged) result.ProviderDisplayOrder = order.slice();
        return result;
    };
    View.prototype.updateDirty = function () {
        if (!this.settings) return;
        var dirty = true;
        try { dirty = Object.keys(this.patch()).length > 0; } catch (error) { dirty = true; }
        this.unsaved.hidden = !dirty;
    };
    View.prototype.updateTabOverflow = function () {
        var tabs = this.view.querySelector(".sa-tabs");
        if (tabs) tabs.classList.toggle("sa-tabs-scrollable", tabs.scrollWidth > tabs.clientWidth + 1);
    };
    View.prototype.renderOrder = function () {
        var self = this, body = this.view.querySelector("[data-provider-order]");
        if (!body) return;
        body.textContent = "";
        (self.providerOrder || []).forEach(function (key) {
            var row = document.createElement("div");
            row.className = "sa-order-row"; row.setAttribute("role", "listitem"); row.setAttribute("data-provider-key", key);
            row.setAttribute("tabindex", "0"); row.setAttribute("aria-label", providerLabel(key) + "，使用上下方向键调整顺序");
            var handle = document.createElement("span");
            handle.className = "sa-order-handle"; handle.setAttribute("aria-hidden", "true"); handle.textContent = "≡";
            var name = document.createElement("span");
            name.className = "sa-order-name"; name.textContent = providerLabel(key);
            row.appendChild(handle); row.appendChild(name);
            row.addEventListener("pointerdown", function (event) { self.startOrderDrag(event, row, key); });
            row.addEventListener("touchstart", function (event) { self.startOrderTouch(event, row, key); }, { passive: false });
            row.addEventListener("keydown", function (event) { self.orderKeyDown(event, key); });
            body.appendChild(row);
        });
    };
    View.prototype.clearOrderDrag = function () {
        this.view.querySelectorAll(".sa-order-row").forEach(function (row) { row.classList.remove("sa-dragging", "sa-drop-target"); });
    };
    View.prototype.markOrderTarget = function (row) {
        this.clearOrderDrag();
        if (this.dragRow) this.dragRow.classList.add("sa-dragging");
        if (row) row.classList.add("sa-drop-target");
    };
    View.prototype.orderRowAt = function (x, y) {
        var body = this.view.querySelector("[data-provider-order]"), rows;
        if (!body) return null;
        var area = body.getBoundingClientRect();
        if (x < area.left - 48 || x > area.right + 48) return null;
        rows = Array.prototype.slice.call(body.querySelectorAll(".sa-order-row"));
        if (!rows.length) return null;
        for (var i = 0; i < rows.length; i++) {
            var box = rows[i].getBoundingClientRect();
            if (y < box.top + box.height / 2) return rows[i];
        }
        return rows[rows.length - 1];
    };
    View.prototype.startOrderDrag = function (event, row, key) {
        if (this.dragKey) return;
        if (event.button !== undefined && event.button !== 0) return;
        if (event.target && event.target.closest && event.target.closest("button, input, a, select")) return;
        event.preventDefault();
        this.dragKey = key; this.dragRow = row; row.classList.add("sa-dragging");
        if (row.focus) row.focus({ preventScroll: true });
        if (row.setPointerCapture && event.pointerId !== undefined) { try { row.setPointerCapture(event.pointerId); } catch (ignore) { } }
        this.onOrderPointerMove = this.orderPointerMove.bind(this);
        this.onOrderPointerUp = this.orderPointerEnd.bind(this);
        document.addEventListener("pointermove", this.onOrderPointerMove, { passive: false });
        document.addEventListener("pointerup", this.onOrderPointerUp);
        document.addEventListener("pointercancel", this.onOrderPointerUp);
    };
    View.prototype.startOrderTouch = function (event, row, key) {
        if (this.dragKey) return;
        if (!event.touches || event.touches.length !== 1) return;
        event.preventDefault();
        this.dragKey = key; this.dragRow = row; row.classList.add("sa-dragging");
        this.touchTargetKey = key;
        if (row.focus) row.focus({ preventScroll: true });
        this.onOrderTouchMove = this.orderTouchMove.bind(this);
        this.onOrderTouchEnd = this.orderTouchEnd.bind(this);
        document.addEventListener("touchmove", this.onOrderTouchMove, { passive: false });
        document.addEventListener("touchend", this.onOrderTouchEnd);
        document.addEventListener("touchcancel", this.onOrderTouchEnd);
    };
    View.prototype.orderTouchMove = function (event) {
        var touch, row;
        if (!this.dragKey) return;
        if (event.cancelable) event.preventDefault();
        touch = event.touches && event.touches[0];
        if (!touch) return;
        row = this.orderRowAt(touch.clientX, touch.clientY);
        if (row) {
            this.touchTargetKey = row.getAttribute("data-provider-key");
            this.markOrderTarget(row);
        }
    };
    View.prototype.orderTouchEnd = function (event) {
        var touch = event.changedTouches && event.changedTouches[0];
        var row = touch ? this.orderRowAt(touch.clientX, touch.clientY) : null;
        var target = row ? row.getAttribute("data-provider-key") : this.touchTargetKey;
        this.finishOrderDrag(target || null);
    };
    View.prototype.orderPointerMove = function (event) {
        var row;
        if (!this.dragKey) return;
        event.preventDefault();
        row = this.orderRowAt(event.clientX, event.clientY);
        if (row) this.markOrderTarget(row);
    };
    View.prototype.orderPointerEnd = function (event) {
        var row = this.orderRowAt(event.clientX, event.clientY);
        this.finishOrderDrag(row ? row.getAttribute("data-provider-key") : null);
    };
    View.prototype.finishOrderDrag = function (targetKey) {
        var key = this.dragKey;
        this.dragKey = null; this.dragRow = null; this.touchTargetKey = null; this.clearOrderDrag();
        if (this.onOrderPointerMove) document.removeEventListener("pointermove", this.onOrderPointerMove);
        if (this.onOrderPointerUp) {
            document.removeEventListener("pointerup", this.onOrderPointerUp);
            document.removeEventListener("pointercancel", this.onOrderPointerUp);
        }
        if (this.onOrderTouchMove) document.removeEventListener("touchmove", this.onOrderTouchMove);
        if (this.onOrderTouchEnd) {
            document.removeEventListener("touchend", this.onOrderTouchEnd);
            document.removeEventListener("touchcancel", this.onOrderTouchEnd);
        }
        if (key && targetKey) this.dropOrder(key, targetKey);
    };
    View.prototype.dropOrder = function (fromKey, targetKey) {
        var order = this.providerOrder || [];
        var from = order.indexOf(fromKey), to = order.indexOf(targetKey);
        if (from < 0 || to < 0 || from === to) return;
        var next = order.slice();
        var moved = next.splice(from, 1)[0];
        next.splice(to, 0, moved);
        this.providerOrder = next;
        this.renderOrder();
        this.updateDirty();
    };
    View.prototype.orderKeyDown = function (event, key) {
        var order = this.providerOrder || [], index = order.indexOf(key), target;
        if (event.key === "ArrowUp") target = index - 1;
        else if (event.key === "ArrowDown") target = index + 1;
        else if (event.key === "Home") target = 0;
        else if (event.key === "End") target = order.length - 1;
        else return;
        event.preventDefault();
        if (target < 0 || target >= order.length || target === index) return;
        var next = order.slice();
        next.splice(index, 1);
        next.splice(target, 0, key);
        this.providerOrder = next;
        this.renderOrder();
        this.updateDirty();
        var moved = this.view.querySelector('.sa-order-row[data-provider-key="' + key + '"]');
        if (moved && moved.focus) moved.focus({ preventScroll: true });
    };
    View.prototype.setProxyResult = function (text, state) {
        if (!this.proxyResult) return;
        this.proxyResult.textContent = text || "";
        this.proxyResult.className = "sa-test-result" + (state ? " " + state : "");
    };
    View.prototype.save = function (event) {
        if (event) event.preventDefault();
        var self = this;
        if (!self.admin || !self.settings) return Promise.reject(Error("仅限管理员。"));
        var patch;
        try { patch = self.patch(); } catch (error) { self.status(error.message); return Promise.reject(error); }
        var orderChanged = patch.ProviderDisplayOrder !== undefined;
        self.status("正在保存…");
        return request("settings", "POST", patch).then(function (result) {
            if (!result.Ok) throw Error(result.Error || "保存失败。");
            if (self.active) {
                self.fill(result.Settings);
                self.status(orderChanged ? "来源顺序已保存，重启 Emby 后生效。" : "设置已保存。");
            }
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
    View.prototype.testProxy = function (button) {
        var self = this;
        button.disabled = true;
        self.setProxyResult("测试中…", "");
        self.save().then(function () {
            return request("proxy/test", "POST", { Purpose: self.view.querySelector("[data-proxy-purpose]").value });
        }).then(function (result) {
            if (!self.active) return;
            if (result.Ok) {
                var route = result.Route === "Proxy" ? "代理" : "直连";
                var latency = typeof result.LatencyMs === "number" ? result.LatencyMs + " ms" : "未知";
                self.setProxyResult(route + " · 延迟 " + latency, "sa-test-ok");
            } else {
                self.setProxyResult(result.Error || "连接失败。", "sa-test-fail");
            }
        }).catch(function () {
            if (self.active) self.setProxyResult("测试未完成，请检查设置和管理员登录状态。", "sa-test-fail");
        }).then(function () { button.disabled = false; });
    };
    View.prototype.click = function (event) {
        var self = this, target = event.target.closest("button");
        if (!target || !self.admin) return;
        if (target.hasAttribute("data-tab")) self.selectTab(target.getAttribute("data-tab"));
        if (target.hasAttribute("data-refresh-jobs")) self.pollJobs();
        if (target.hasAttribute("data-proxy-test")) self.testProxy(target);
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
        this.finishOrderDrag(null);
        this.form.removeEventListener("submit", this.onSubmit);
        this.form.removeEventListener("input", this.onInput);
        this.form.removeEventListener("change", this.onInput);
        this.view.removeEventListener("click", this.onClick);
        this.view.removeEventListener("keydown", this.onKeyDown);
        window.removeEventListener("resize", this.onResize);
        BaseView.prototype.destroy.apply(this, arguments);
    };
    return View;
});
