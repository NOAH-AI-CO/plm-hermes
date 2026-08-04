/*
 * Noah PLM 会话右键菜单修正:空会话(message_count===0)时禁用「依赖对话内容」的菜单项——
 * 重新生成标题(点了会报 empty_user_message)、导出 HTML、复制会话——置灰不可点。
 * 手段:只读嗅探 /api/sessions 拿 session_id→message_count 映射;观察菜单弹出后按标签禁用。
 * 未知会话(映射里没有)一律不动(fail-open),避免误伤有内容的会话。只操作 DOM,不改核心。
 */
(function () {
    "use strict";

    var MC = Object.create(null);   // session_id -> message_count

    // ---- 只读嗅探 /api/sessions ----
    function ingestArr(arr) {
        if (!Array.isArray(arr)) return;
        for (var i = 0; i < arr.length; i++) {
            var s = arr[i];
            if (s && s.session_id != null && s.message_count != null) {
                MC[String(s.session_id)] = Number(s.message_count) || 0;
            }
        }
    }
    function ingest(data) {
        if (Array.isArray(data)) { ingestArr(data); return; }
        if (!data || typeof data !== "object") return;
        ingestArr(data.sessions);
        ingestArr(data.sidebar_reference_sessions);
        ingestArr(data.items);
    }
    if (typeof window.fetch === "function" && !window.__noahMenuFetchWrap) {
        window.__noahMenuFetchWrap = true;
        var orig = window.fetch;
        window.fetch = function (input) {
            var p = orig.apply(this, arguments);
            try {
                var u = typeof input === "string" ? input : (input && (input.url || input.href)) || "";
                if (u.indexOf("api/sessions") !== -1 && u.indexOf("gateway") === -1) {
                    p.then(function (res) {
                        try { res.clone().json().then(ingest).catch(function () {}); } catch (e) {}
                    }).catch(function () {});
                }
            } catch (e) {}
            return p;
        };
    }

    // ---- 目标菜单项标签(当前语言 via t() + 常见兜底)----
    function targetLabels() {
        var set = Object.create(null);
        function add(v) { if (v) set[String(v).trim()] = 1; }
        try { add(t("session_title_regenerate")); add(t("session_export_html")); add(t("session_duplicate")); } catch (e) {}
        ["重新生成标题", "Regenerate title", "Export as HTML", "导出为 HTML",
         "复制会话", "Duplicate conversation"].forEach(add);
        return set;
    }

    function disableEmptyActions(menu) {
        var row = document.querySelector(".session-item.menu-open, .session-child-session.menu-open");
        var sid = row ? row.getAttribute("data-sid") : null;
        if (!sid || !(sid in MC) || MC[sid] !== 0) return;   // 未知或有内容 → 不动
        var labels = targetLabels();
        var opts = menu.querySelectorAll(".session-action-opt");
        for (var i = 0; i < opts.length; i++) {
            var nameEl = opts[i].querySelector(".ws-opt-name");
            var name = nameEl ? nameEl.textContent.trim() : "";
            if (labels[name]) {
                opts[i].disabled = true;                       // <button disabled> 原生阻止 click
                opts[i].setAttribute("aria-disabled", "true");
                opts[i].classList.add("noah-opt-disabled");
                opts[i].title = "无对话内容,暂不可用";
            }
        }
    }

    // ---- 样式 ----
    var style = document.createElement("style");
    style.textContent =
        ".session-action-menu .session-action-opt.noah-opt-disabled{opacity:.4;cursor:not-allowed;}";
    (document.head || document.documentElement).appendChild(style);

    // ---- 观察菜单弹出 ----
    function handle(m) {
        disableEmptyActions(m);
        try { requestAnimationFrame(function () { disableEmptyActions(m); }); } catch (e) {}
    }
    function scan(node) {
        if (!node || node.nodeType !== 1) return;
        if (node.classList && node.classList.contains("session-action-menu")) handle(node);
        else if (node.querySelector) {
            var m = node.querySelector(".session-action-menu");
            if (m) handle(m);
        }
    }
    new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
            var added = muts[i].addedNodes;
            for (var j = 0; j < added.length; j++) scan(added[j]);
        }
    }).observe(document.body || document.documentElement, { childList: true, subtree: true });
})();
