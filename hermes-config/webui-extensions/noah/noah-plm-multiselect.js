/*
 * Noah PLM 多选重设计(只操作 DOM + 复用核心全局函数, 不改核心):
 *  1) 入口挪到右上角标题栏一个图标按钮(隐藏底部原「选择」文字按钮);
 *  2) 点它进入多选(toggleSessionSelectMode)→ 每条出现勾选框;
 *  3) 顶部常驻批量条: [全选] 已选 N 项 …… [删除] [取消](0 选时也显示, 便于先全选);
 *     - 全选/取消全选 → selectAllSessions/deselectAllSessions
 *     - 删除 → 转发点击核心隐藏的删除按钮(.batch-action-btn-danger, 带核心二次确认)
 *     - 取消 → exitSessionSelectMode
 */
(function () {
    "use strict";

    var ICON =
        '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>';

    function call(fn) { try { if (typeof window[fn] === "function") window[fn](); } catch (e) {} }
    function tt(key, zh) { try { return typeof t === "function" ? t(key) : zh; } catch (e) { return zh; } }
    function total() { return document.querySelectorAll(".session-select-cb").length; }
    function checked() { return document.querySelectorAll(".session-select-cb:checked").length; }
    function inMode() { return total() > 0; }   // 多选模式下每行才有勾选框

    // 找核心批量栏里的按钮(转发点击)
    function coreBtn(kind) {
        var bar = document.getElementById("batchActionBar");
        if (!bar) return null;
        if (kind === "delete") return bar.querySelector(".batch-action-btn-danger");
        var label = kind === "archive" ? tt("session_batch_archive", "归档") : tt("session_batch_move", "移到项目");
        var btns = bar.querySelectorAll(".batch-action-btn");
        for (var i = 0; i < btns.length; i++) { if (btns[i].textContent.trim() === label) return btns[i]; }
        return null;
    }

    // 右上角入口图标
    function ensureEntry() {
        var actions = document.querySelector("#panelChat .panel-head-actions");
        if (!actions) return;
        var btn = document.getElementById("noahMultiSelectBtn");
        if (!btn) {
            btn = document.createElement("button");
            btn.id = "noahMultiSelectBtn";
            btn.className = "panel-head-btn";
            btn.type = "button";
            btn.title = "多选";
            btn.setAttribute("aria-label", "多选");
            btn.innerHTML = ICON;
            btn.onclick = function (e) { e.preventDefault(); e.stopPropagation(); call("toggleSessionSelectMode"); };
            actions.insertBefore(btn, actions.firstChild);
        }
        btn.classList.toggle("on", inMode());
    }

    // 顶部常驻批量条(插在搜索框后, 不受列表重渲染影响)
    function ensureBar() {
        var panel = document.getElementById("panelChat");
        if (!panel) return null;
        var bar = document.getElementById("noahSelBar");
        if (!bar) {
            bar = document.createElement("div");
            bar.id = "noahSelBar";
            bar.innerHTML =
                '<label class="ms-selall"><input type="checkbox" id="msAll"><span id="msAllTxt"></span></label>' +
                '<span id="msCount" class="ms-count"></span>' +
                '<button type="button" id="msArchive" class="ms-btn"></button>' +
                '<button type="button" id="msMove" class="ms-btn"></button>' +
                '<button type="button" id="msDelete" class="ms-btn ms-del"></button>';
            var search = panel.querySelector(".sidebar-search");
            if (search && search.nextSibling) panel.insertBefore(bar, search.nextSibling);
            else panel.appendChild(bar);

            bar.querySelector("#msAll").onclick = function (e) {
                e.stopPropagation();
                if (checked() < total()) call("selectAllSessions"); else call("deselectAllSessions");
            };
            bar.querySelector("#msAllTxt").onclick = function (e) {
                e.stopPropagation();
                if (checked() < total()) call("selectAllSessions"); else call("deselectAllSessions");
            };
            bar.querySelector("#msArchive").onclick = function (e) {
                e.stopPropagation();
                if (checked() === 0) return;
                var a = coreBtn("archive");
                if (a) a.click();
            };
            bar.querySelector("#msMove").onclick = function (e) {
                e.stopPropagation();
                if (checked() === 0) return;
                var m = coreBtn("move");
                if (m) m.click();
            };
            bar.querySelector("#msDelete").onclick = function (e) {
                e.stopPropagation();
                if (checked() === 0) return;
                var d = coreBtn("delete");
                if (d) d.click();   // 转发到核心删除(带确认+真正删除)
            };
        }
        return bar;
    }

    function refresh() {
        var on = inMode();
        document.documentElement.classList.toggle("noah-selmode", on);
        var btn = document.getElementById("noahMultiSelectBtn");
        if (btn) btn.classList.toggle("on", on);
        if (!on) return;
        var all = total(), sel = checked();
        var allTxt = document.getElementById("msAllTxt");
        var allCb = document.getElementById("msAll");
        var cnt = document.getElementById("msCount");
        var del = document.getElementById("msDelete");
        if (allTxt) { var lab = (sel > 0 && sel === all) ? tt("session_deselect_all", "取消全选") : tt("session_select_all", "全选"); if (allTxt.textContent !== lab) allTxt.textContent = lab; }
        if (allCb) allCb.checked = sel > 0 && sel === all;
        if (cnt) { var c = tt("session_selected_count", "已选 " + sel + " 项"); if (typeof c === "string" && c.indexOf("{0}") >= 0) c = c.replace("{0}", sel); if (cnt.textContent !== c) cnt.textContent = c; }
        var arch = document.getElementById("msArchive");
        var move = document.getElementById("msMove");
        if (arch) { arch.disabled = sel === 0; if (arch.textContent !== "归档") arch.textContent = "归档"; }
        if (move) { move.disabled = sel === 0; if (move.textContent !== "移动") move.textContent = "移动"; }
        if (del) { del.disabled = sel === 0; if (del.textContent !== "删除") del.textContent = "删除"; }
    }

    function tick() { ensureEntry(); ensureBar(); refresh(); }
    new MutationObserver(tick).observe(document.body || document.documentElement, { childList: true, subtree: true });
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick);
    else tick();
    setInterval(tick, 600);
})();
