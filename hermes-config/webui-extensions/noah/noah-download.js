/*
 * Noah Medical - Workspace 一键下载按钮
 *
 * 在 workspace panel 顶部加一个"下载 zip"按钮
 * 点击后调用官方 /api/folder/download?session_id=xxx&path=xxx 打包当前 workspace
 */
(function () {
    "use strict";

    const BTN_ID = "noah-download-workspace";

    function getCurrentSessionId() {
        // 从全局状态拿（hermes-webui 里 S.session.session_id）
        try {
            if (window.S && window.S.session && window.S.session.session_id) {
                return window.S.session.session_id;
            }
        } catch (e) {}
        // 兜底：从 URL 抓
        const m = location.pathname.match(/\/session\/([a-f0-9]+)/);
        return m ? m[1] : null;
    }

    function currentWorkspacePath() {
        // 当前 workspace 里选中的目录（如 medical-consult/20260703_case/）
        // 简化：默认打包整个 workspace（path=""），因为用户通常想要全部
        // 若你在文件浏览器点开了某个子目录，可用 window.__currentWorkspaceRelDir（若 Hermes 暴露）
        try {
            if (window.__noahCurrentDir) return window.__noahCurrentDir;
        } catch (e) {}
        return "";
    }

    function triggerDownload() {
        const sid = getCurrentSessionId();
        if (!sid) {
            alert("未识别到当前 session，请刷新页面后重试");
            return;
        }
        const path = currentWorkspacePath();
        const url = "/api/folder/download?session_id=" + encodeURIComponent(sid)
                  + "&path=" + encodeURIComponent(path);
        // 直接跳转触发下载
        window.location.href = url;
    }

    function ensureButton() {
        // 找 workspace 面板顶部的 panel-actions 容器
        const rightPanel = document.querySelector(".rightpanel");
        if (!rightPanel) return;
        const actions = rightPanel.querySelector(".panel-actions");
        if (!actions) return;
        if (actions.querySelector("#" + BTN_ID)) return; // 已存在

        const btn = document.createElement("button");
        btn.id = BTN_ID;
        btn.type = "button";
        btn.className = "icon-btn has-tooltip";
        btn.setAttribute("data-tooltip", "下载整个 workspace 为 zip");
        btn.setAttribute("aria-label", "下载 workspace");
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
        `;
        btn.onclick = triggerDownload;
        // 插到 actions 的第一位（在 + / 文件夹 / 刷新 / 上传 等按钮左边）
        actions.insertBefore(btn, actions.firstChild);
    }

    function init() {
        ensureButton();
        // MutationObserver: 面板可能延迟渲染，看到 .rightpanel 出现就装按钮
        const observer = new MutationObserver(() => {
            ensureButton();
        });
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
    window.addEventListener("load", init);

    console.log("[Noah] Download workspace button loaded");
})();
