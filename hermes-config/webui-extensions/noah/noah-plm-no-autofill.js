/*
 * Noah PLM 会话侧栏修正(只操作 DOM, 不改核心):
 *  1) 阻止浏览器把保存的邮箱自动填进会话搜索框(#sessionSearch)——用 readonly-直到聚焦。
 *  2) 无(可见)会话时隐藏「选择」按钮(.session-select-toggle)——核心是无条件加它。
 */
(function () {
    "use strict";

    // ---- 1) 禁止邮箱自动填充 ----
    function hardenSearch() {
        var s = document.getElementById("sessionSearch");
        if (!s) return;
        if (s.dataset.noahAf !== "1") {             // 属性/监听只绑一次
            s.dataset.noahAf = "1";
            s.setAttribute("autocomplete", "off");
            s.setAttribute("readonly", "readonly"); // 只读 → 浏览器不会自动填充
            var unlock = function () { s.removeAttribute("readonly"); };
            s.addEventListener("focus", unlock);
            s.addEventListener("pointerdown", unlock);
        }
        // 每次 tick: 用户未交互过(仍只读)且被自动填了值 → 清掉; 不动用户已输入的筛选
        if (s.readOnly && document.activeElement !== s && s.value) s.value = "";
    }

    // ---- 2) 无可见会话时隐藏「选择」按钮 ----
    function updateSelectToggle() {
        var list = document.getElementById("sessionList");
        if (!list) return;
        var toggle = list.querySelector(".session-select-toggle");
        if (!toggle) return;
        var rows = list.querySelectorAll(".session-item[data-sid]");
        var hasVisible = false;
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].offsetParent !== null) { hasVisible = true; break; }
        }
        var want = hasVisible ? "" : "none";
        if (toggle.style.display !== want) toggle.style.display = want;   // 只在变化时改, 防抖动/死循环
    }

    var _obsAttached = false;
    function attachObserver() {
        var list = document.getElementById("sessionList");
        if (list && !_obsAttached) {
            _obsAttached = true;
            new MutationObserver(updateSelectToggle).observe(list, {
                childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class"],
            });
        }
        updateSelectToggle();
    }

    function tick() { hardenSearch(); attachObserver(); }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick);
    else tick();
    setInterval(tick, 1500);
})();
