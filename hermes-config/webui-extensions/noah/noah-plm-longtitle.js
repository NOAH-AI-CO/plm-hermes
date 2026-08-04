/*
 * Noah PLM 超长标题处理(只操作 DOM, 不改核心):
 *  1) 项目 chip 补 title 属性 → 悬停显示全名(配合 CSS 截断);
 *  2) 项目右键菜单(.project-ctx-menu)夹取进视口 → 长标题右击不再弹到屏幕外;
 *  3) 改写「删除项目」确认文案 → 更清楚的中文表达(原文是英文且措辞含糊)。
 */
(function () {
    "use strict";

    // ---- 1) 项目 chip 悬停提示 ----
    function addChipTitles() {
        var chips = document.querySelectorAll(".project-chip");
        for (var i = 0; i < chips.length; i++) {
            if (chips[i].getAttribute("title")) continue;
            var span = chips[i].querySelector("span:not(.color-dot)");
            var txt = span ? (span.textContent || "").trim() : "";
            if (txt) chips[i].setAttribute("title", txt);
        }
    }

    // ---- 2) 右键菜单视口夹取 ----
    function clampMenu(m) {
        try {
            var r = m.getBoundingClientRect();
            var pad = 8, vw = window.innerWidth, vh = window.innerHeight;
            var left = r.left, top = r.top;
            if (r.right > vw - pad) left = vw - r.width - pad;
            if (r.bottom > vh - pad) top = vh - r.height - pad;
            if (left < pad) left = pad;
            if (top < pad) top = pad;
            m.style.left = left + "px";
            m.style.top = top + "px";
        } catch (e) {}
    }

    // ---- 3) 删除项目确认文案改写 ----
    var DEL_RE = /^Delete project "([\s\S]*)"\? Sessions will be unassigned but not deleted\.$/;
    function reword(msg) {
        if (typeof msg !== "string") return msg;
        var m = msg.match(DEL_RE);
        if (m) return "确定删除项目「" + m[1] + "」吗?项目内的会话不会被删除,只会移出该项目(变为未分类)。";
        return msg;
    }
    if (typeof window.showConfirmDialog === "function" && !window.__noahConfirmWrap) {
        window.__noahConfirmWrap = true;
        var orig = window.showConfirmDialog;
        window.showConfirmDialog = function (opts) {
            try {
                if (opts && typeof opts.message === "string") {
                    var o = {};
                    for (var k in opts) if (Object.prototype.hasOwnProperty.call(opts, k)) o[k] = opts[k];
                    o.message = reword(opts.message);
                    return orig.call(this, o);
                }
            } catch (e) {}
            return orig.apply(this, arguments);
        };
    }

    // ---- 观察 DOM ----
    function scan(node) {
        if (!node || node.nodeType !== 1) return;
        if (node.classList && node.classList.contains("project-ctx-menu")) clampMenu(node);
        else if (node.querySelector) {
            var m = node.querySelector(".project-ctx-menu");
            if (m) clampMenu(m);
        }
    }
    new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
            var a = muts[i].addedNodes;
            for (var j = 0; j < a.length; j++) scan(a[j]);
        }
        addChipTitles();
        // 兜底: 若函数包裹未拦到(极端情况), 直接改 DOM 里的英文文案
        var desc = document.getElementById("appDialogDesc");
        if (desc) { var r = reword(desc.textContent); if (r !== desc.textContent) desc.textContent = r; }
    }).observe(document.body || document.documentElement, { childList: true, subtree: true });

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addChipTitles);
    else addChipTitles();
    setInterval(addChipTitles, 2000);
})();
