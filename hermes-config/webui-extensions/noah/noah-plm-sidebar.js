/*
 * Noah PLM 侧栏增强:
 *  1) 顶部"+"新建会话按钮补上"新建会话"文字标签(原本只有图标)。
 *  2) 侧栏底部加"清除历史记录"——列出当前用户会话后逐个删除, 再刷新。
 * 只操作 DOM + 调 webui 现成同源接口(/api/sessions、/api/session/delete), 不改核心。
 */
(function () {
    "use strict";

    var css =
        '#btnNewChat.noah-newchat-labeled{width:auto;padding:0 10px;gap:6px;display:inline-flex;align-items:center;border-radius:8px;}' +
        '#btnNewChat .noah-newchat-txt{font-size:13px;font-weight:600;white-space:nowrap;line-height:1;}' +
        // 底部一行:折叠把手 + "管理" + "清除历史", 不再各自浮动重叠
        '.noah-sidebar-footer{margin-top:auto;display:flex;align-items:center;gap:8px;' +
        'padding:8px 10px 10px;border-top:1px solid var(--border-color,rgba(0,0,0,.08));}' +
        // 折叠把手
        '.noah-footer-toggle{flex:0 0 auto;width:26px;height:28px;display:inline-flex;align-items:center;justify-content:center;' +
        'font-size:13px;color:#888;background:transparent;border:1px solid var(--border-color,rgba(0,0,0,.12));' +
        'border-radius:7px;cursor:pointer;transition:background .15s,color .15s;}' +
        '.noah-footer-toggle:hover{background:rgba(0,0,0,.05);color:#333;}' +
        // 把原本 position:fixed 的"管理"收进 footer, 归为普通流内元素
        '#noah-admin-btn.noah-admin-docked{position:static!important;left:auto!important;right:auto!important;' +
        'top:auto!important;bottom:auto!important;z-index:auto!important;margin:0!important;flex:0 0 auto;}' +
        '.noah-clear-history{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;' +
        'padding:7px 10px;font-size:13px;color:#c0392b;background:transparent;border:1px solid #f0d0cc;' +
        'border-radius:8px;cursor:pointer;transition:background .15s;white-space:nowrap;}' +
        '.noah-clear-history:hover{background:#fdecea;}' +
        '.noah-clear-history[disabled]{opacity:.6;cursor:default;}' +
        // 折叠态:只留把手, 隐藏管理 + 清除历史
        '.noah-sidebar-footer.noah-footer-collapsed{gap:0;padding:6px 10px;}' +
        '.noah-sidebar-footer.noah-footer-collapsed #noah-admin-btn,' +
        '.noah-sidebar-footer.noah-footer-collapsed #noah-clear-history{display:none!important;}';
    var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

    // 1) 新建会话标签
    function labelNewChat() {
        var b = document.getElementById("btnNewChat");
        if (!b || b.querySelector(".noah-newchat-txt")) return;
        var span = document.createElement("span");
        span.className = "noah-newchat-txt"; span.textContent = "新建会话";
        b.appendChild(span);
        b.classList.add("noah-newchat-labeled");
    }

    // 2) 清除历史记录
    async function clearHistory(btn) {
        if (!window.confirm("确定清除全部聊天历史记录吗?此操作不可恢复。")) return;
        var old = btn.textContent; btn.disabled = true; btn.textContent = "清除中…";
        try {
            var r = await fetch("/api/sessions", { headers: { "Accept": "application/json" } });
            var d = await r.json();
            var list = (d && d.sessions) || [];
            var n = 0;
            for (var i = 0; i < list.length; i++) {
                var sid = list[i].session_id; if (!sid) continue;
                try {
                    var dr = await fetch("/api/session/delete", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ session_id: sid }),
                    });
                    if (dr.ok) n++;
                } catch (e) {}
            }
            btn.textContent = "已清除 " + n + " 条,刷新中…";
            setTimeout(function () { location.reload(); }, 400);
        } catch (e) {
            alert("清除失败:" + ((e && e.message) || e)); btn.disabled = false; btn.textContent = old;
        }
    }

    function syncToggle(foot) {
        var tg = document.getElementById("noah-footer-toggle");
        if (!tg) return;
        var collapsed = foot.classList.contains("noah-footer-collapsed");
        tg.textContent = collapsed ? "»" : "«";                 // »=展开, «=收起
        tg.title = collapsed ? "展开工具栏" : "收起工具栏";
    }
    function toggleCollapse(foot) {
        foot.classList.toggle("noah-footer-collapsed");
        try { localStorage.setItem("noahFooterCollapsed", foot.classList.contains("noah-footer-collapsed") ? "1" : "0"); } catch (e) {}
        syncToggle(foot);
    }

    function mountFooter() {
        var panel = document.getElementById("panelChat");
        if (!panel) return;
        var foot = document.getElementById("noah-sidebar-footer");
        if (!foot) {
            foot = document.createElement("div"); foot.className = "noah-sidebar-footer"; foot.id = "noah-sidebar-footer";
            var tg = document.createElement("button");
            tg.id = "noah-footer-toggle"; tg.className = "noah-footer-toggle"; tg.type = "button";
            tg.addEventListener("click", function () { toggleCollapse(foot); });
            var btn = document.createElement("button");
            btn.id = "noah-clear-history"; btn.className = "noah-clear-history"; btn.type = "button";
            btn.innerHTML = "🗑 清除历史记录";
            btn.addEventListener("click", function () { clearHistory(btn); });
            foot.appendChild(tg);
            foot.appendChild(btn);
            panel.appendChild(foot);
            try { if (localStorage.getItem("noahFooterCollapsed") === "1") foot.classList.add("noah-footer-collapsed"); } catch (e) {}
            syncToggle(foot);
        }
        // "管理"原本 position:fixed 浮在左下角, 与本 footer 重叠 → 收编进 footer(把手右侧、清除历史左侧)
        var admin = document.getElementById("noah-admin-btn");
        if (admin && admin.parentNode !== foot) {
            admin.classList.add("noah-admin-docked");
            var clear = document.getElementById("noah-clear-history");
            foot.insertBefore(admin, clear);
        }
    }

    function tick() { try { labelNewChat(); } catch (e) {} try { mountFooter(); } catch (e) {} }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick);
    else tick();
    setInterval(tick, 1500);
    console.log("[Noah] PLM sidebar enhance loaded");
})();
