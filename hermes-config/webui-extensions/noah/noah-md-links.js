/*
 * Noah Medical - MD Links Auto-Preview (v4.3 新增)
 *
 * 官方现状：消息里的 `.md` 文件链接（📎 1-诊疗历程总结.md）默认触发下载。
 * 用户体验：想看内容却拿到 zip，很反直觉。
 *
 * 本扩展：
 *   1. 拦截消息里所有 .md 链接的点击
 *   2. 从链接的 href 提取 path
 *   3. 调用官方 openFile(path) → 右侧预览面板打开该 md
 *   4. 手机端 → 同时展开 workspace slide-over（触发 toggleWorkspacePanel）
 *
 * 依赖官方 API:
 *   window.openFile(path)                    - 触发文件预览（workspace.js:1043）
 *   window.toggleWorkspacePanel()            - 展开/收起右侧面板
 */

(function () {
    "use strict";

    const MOBILE_MQ = window.matchMedia("(max-width: 640px)");

    /**
     * 从下载链接的 href 提取 workspace 相对路径
     * 链接形如：
     *   /api/media?path=/home/ubuntu/workspace/sessions/xxx/medical-consult/yyy/1-诊疗历程总结.md&download=1
     *   或者带 &session_id=xxx
     */
    function extractPathFromHref(href) {
        if (!href) return null;
        try {
            // 相对路径也能解析
            const url = new URL(href, window.location.origin);
            if (!url.pathname.includes("/api/media")) return null;
            const p = url.searchParams.get("path");
            if (!p) return null;
            return p;
        } catch (_) {
            return null;
        }
    }

    /**
     * 从绝对路径提取 workspace 相对部分
     * /home/ubuntu/workspace/sessions/<sid>/medical-consult/xxx/1.md → medical-consult/xxx/1.md
     */
    function absToWorkspaceRelative(absPath) {
        if (!absPath) return null;
        // 尝试用当前 session 的 workspace 前缀去掉
        const sid = (window.S && window.S.session && window.S.session.session_id) ? String(window.S.session.session_id) : "";
        if (sid) {
            const prefix1 = "/home/ubuntu/workspace/sessions/" + sid + "/";
            const prefix2 = "/root/workspace/sessions/" + sid + "/";
            for (const pre of [prefix1, prefix2]) {
                if (absPath.startsWith(pre)) {
                    return absPath.slice(pre.length);
                }
            }
        }
        // Fallback：切到 workspace/ 之后
        const idx = absPath.indexOf("/workspace/");
        if (idx >= 0) {
            const after = absPath.slice(idx + "/workspace/".length);
            // 去掉 sessions/<sid>/ 前缀
            const m = after.match(/^sessions\/[^\/]+\/(.+)$/);
            if (m) return m[1];
            return after;
        }
        return absPath;
    }

    /**
     * 判断是不是 md/csv/pdf/html 等能预览的文件
     * （只拦截可预览的，非可预览的仍走下载）
     */
    const PREVIEW_EXTS = /\.(md|csv|pdf|html|txt|json|yaml|yml|xml|log|diff|patch)$/i;

    /**
     * 主拦截逻辑：捕获阶段绑定 click，抢在官方 handler 之前
     */
    function interceptMdLinks() {
        document.addEventListener("click", function (e) {
            const link = e.target && e.target.closest && e.target.closest("a.msg-media-link");
            if (!link) return;

            // 只处理 .md/.csv/.pdf 等可预览的
            const href = link.getAttribute("href") || "";
            const linkText = link.textContent || "";
            const isPreviewable = PREVIEW_EXTS.test(href) || PREVIEW_EXTS.test(linkText);
            if (!isPreviewable) return;

            // 提取 path
            const absPath = extractPathFromHref(href);
            if (!absPath) {
                console.warn("[Noah md-links] 无法提取 path:", href);
                return;
            }

            const relPath = absToWorkspaceRelative(absPath);
            if (!relPath) {
                console.warn("[Noah md-links] 无法转换为 workspace 相对路径:", absPath);
                return;
            }

            // 阻止官方下载行为
            e.preventDefault();
            e.stopPropagation();

            // 调 openFile
            if (typeof window.openFile !== "function") {
                console.warn("[Noah md-links] openFile 未定义，回退到默认下载");
                window.location.href = href;
                return;
            }

            // 手机端：先展开 workspace 面板
            if (MOBILE_MQ.matches) {
                if (typeof window.toggleWorkspacePanel === "function") {
                    // 只在 closed 状态下 toggle（避免关闭已开的面板）
                    const state = document.documentElement.getAttribute("data-workspace-panel");
                    if (state !== "open") {
                        window.toggleWorkspacePanel();
                    }
                }
            }

            // 打开文件（会自动切到 preview 视图 + 加载内容 + 触发 renderMarkdownPreviewContent）
            console.log("[Noah md-links] 预览:", relPath);
            window.openFile(relPath).catch(err => {
                console.error("[Noah md-links] openFile 失败:", err);
                // 失败回退到官方下载行为
                window.location.href = href;
            });
        }, true); // ⭐ 捕获阶段，抢在 <a href> 默认行为之前
    }

    // ============================================================
    // 应用
    // ============================================================
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", interceptMdLinks);
    } else {
        interceptMdLinks();
    }

    console.log("[Noah md-links] v4.3 loaded (点 .md/.csv/.pdf 链接自动侧边预览)");
})();
