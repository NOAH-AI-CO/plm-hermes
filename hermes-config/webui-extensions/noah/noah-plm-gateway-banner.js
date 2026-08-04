/*
 * Noah PLM 网关掉线提示优化(只操作 DOM, 不改核心):
 *  1) 把技术性英文文案(Hermes agent is not responding / Gateway heartbeat failed…)
 *     改成用户能看懂的中文;
 *  2) 隐藏「Restart Service」按钮 —— 本部署里网关在远端、webui 容器无 hermes CLI,
 *     点它必报 FileNotFoundError: 'hermes';连接会自动恢复, 用户无需(也无法)手动重启。
 */
(function () {
    "use strict";

    var st = document.createElement("style");
    st.textContent = "#btnRestartGateway{display:none!important;}";
    (document.head || document.documentElement).appendChild(st);

    var TITLE = "连接暂时中断";
    var DETAILS = "与服务器的连接中断,正在自动重连。这期间消息可能延迟送达,请稍候片刻再发送。";

    function reword() {
        var b = document.getElementById("agentHealthBanner");
        if (!b || b.hidden) return;
        var t = document.getElementById("agentHealthTitle");
        var d = document.getElementById("agentHealthDetails");
        if (t && t.textContent !== TITLE) t.textContent = TITLE;
        if (d && d.textContent !== DETAILS) d.textContent = DETAILS;
    }

    function attach() {
        var b = document.getElementById("agentHealthBanner");
        if (b && b.dataset.noahRw !== "1") {
            b.dataset.noahRw = "1";
            new MutationObserver(reword).observe(b, { attributes: true, childList: true, subtree: true, characterData: true });
        }
        reword();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", attach);
    else attach();
    setInterval(attach, 1000);
})();
