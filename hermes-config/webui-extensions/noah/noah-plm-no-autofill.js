/*
 * Noah PLM: 阻止浏览器把保存的邮箱自动填进会话搜索框(#sessionSearch)。
 * Chrome 常无视 autocomplete=off, webui 虽在 boot 时清过一次, Chrome 之后又填回来。
 * 手法: 平时给输入框加 readonly(只读时浏览器不自动填充), 用户聚焦/点击时才解锁可输入。
 * 只操作 DOM, 不改核心。
 */
(function () {
    "use strict";

    function harden() {
        var s = document.getElementById("sessionSearch");
        if (!s || s.dataset.noahAf === "1") return;
        s.dataset.noahAf = "1";
        if (s.value) s.value = "";                  // 清掉已被自动填充的邮箱
        s.setAttribute("autocomplete", "off");
        s.setAttribute("readonly", "readonly");     // 只读 → 浏览器不会自动填充
        var unlock = function () { s.removeAttribute("readonly"); };
        s.addEventListener("focus", unlock);
        s.addEventListener("pointerdown", unlock);
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", harden);
    else harden();
    setInterval(harden, 1500);   // 侧栏重渲染后 input 可能被重建, 持续处理
})();
