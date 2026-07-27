/*
 * Noah Medical - Mobile UX Enhancements (v4.3)
 *
 * 变化 vs v4.2:
 *   1. Workspace 按钮挪到 titlebar 最右侧（脱离 +/refresh 组，暗示"侧滑面板"）
 *   2. 图标改成 📋 文档卡片风格（比 📁 更表意）
 *   3. 首次进入 tooltip 引导："点这里查看诊疗报告"（localStorage 记录已看过）
 *   4. workspace 按钮改带文字标签（"报告"），非纯图标
 */

(function () {
    "use strict";

    const MOBILE_MQ = window.matchMedia("(max-width: 640px)");
    const HINT_KEY = "noah-workspace-hint-seen-v1";

    // ============================================================
    // 1. 注入 workspace 按钮到 titlebar 最右侧
    // ============================================================
    function ensureMobileWorkspaceBtn() {
        if (!MOBILE_MQ.matches) {
            const existing = document.getElementById("noah-mobile-workspace-btn");
            if (existing) existing.remove();
            const hint = document.getElementById("noah-workspace-hint");
            if (hint) hint.remove();
            return;
        }

        if (document.getElementById("noah-mobile-workspace-btn")) return;

        const titlebar = document.querySelector(".app-titlebar");
        if (!titlebar) return;

        // 按钮容器：报告图标 + 文字标签
        const btn = document.createElement("button");
        btn.id = "noah-mobile-workspace-btn";
        btn.type = "button";
        btn.setAttribute("aria-label", "查看诊疗报告");
        btn.setAttribute("title", "查看诊疗报告（点击右侧滑出）");
        // 图标：clipboard 剪贴板样式，更接近"报告"隐喻
        btn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/>
                <rect x="9" y="3" width="6" height="4" rx="1"/>
                <line x1="9" y1="12" x2="15" y2="12"/>
                <line x1="9" y1="16" x2="13" y2="16"/>
            </svg>
            <span class="noah-mobile-workspace-label">报告</span>
        `;
        btn.onclick = () => {
            // 点击后隐藏 hint
            dismissHint();
            if (typeof window.toggleWorkspacePanel === "function") {
                window.toggleWorkspacePanel();
            }
        };

        // ⭐ 插入到 titlebar 最末尾（脱离 +/refresh 那组）
        titlebar.appendChild(btn);

        // 首次显示引导
        maybeShowHint(btn);
    }

    // ============================================================
    // 2. 首次进入 tooltip 引导
    // ============================================================
    function maybeShowHint(anchorBtn) {
        try {
            if (localStorage.getItem(HINT_KEY)) return;
        } catch (_) {
            // localStorage 不可用（隐私模式）→ 不显示引导（避免每次弹）
            return;
        }

        // 等 titlebar 布局稳定后再展示
        setTimeout(() => {
            if (!MOBILE_MQ.matches) return;
            const btn = document.getElementById("noah-mobile-workspace-btn");
            if (!btn) return;

            const hint = document.createElement("div");
            hint.id = "noah-workspace-hint";
            hint.innerHTML = `
                <div class="noah-hint-arrow"></div>
                <div class="noah-hint-content">
                    <strong>📋 点这里查看诊疗报告</strong>
                    <span class="noah-hint-sub">病例分析生成的 md 文件都在这里</span>
                </div>
                <button class="noah-hint-close" aria-label="关闭">×</button>
            `;
            document.body.appendChild(hint);

            // 定位到按钮下方
            positionHint(hint, btn);

            // 关闭按钮
            hint.querySelector(".noah-hint-close").onclick = (e) => {
                e.stopPropagation();
                dismissHint();
            };

            // 8 秒后自动消失
            hint._autoTimer = setTimeout(dismissHint, 8000);

            // 点击其他地方也关闭
            const outsideClick = (e) => {
                if (!hint.contains(e.target) && e.target !== btn) {
                    dismissHint();
                }
            };
            setTimeout(() => document.addEventListener("click", outsideClick, true), 100);
            hint._outsideClick = outsideClick;

            // 窗口 resize / scroll 时重新定位
            const reposition = () => positionHint(hint, btn);
            window.addEventListener("resize", reposition);
            window.addEventListener("scroll", reposition, true);
            hint._reposition = reposition;
        }, 800);
    }

    function positionHint(hint, btn) {
        const rect = btn.getBoundingClientRect();
        // 面板箭头指向按钮
        hint.style.top = (rect.bottom + 8) + "px";
        // 右对齐到按钮右边
        hint.style.right = (window.innerWidth - rect.right) + "px";
    }

    function dismissHint() {
        const hint = document.getElementById("noah-workspace-hint");
        if (!hint) return;
        try {
            localStorage.setItem(HINT_KEY, String(Date.now()));
        } catch (_) {}
        if (hint._autoTimer) clearTimeout(hint._autoTimer);
        if (hint._outsideClick) document.removeEventListener("click", hint._outsideClick, true);
        if (hint._reposition) {
            window.removeEventListener("resize", hint._reposition);
            window.removeEventListener("scroll", hint._reposition, true);
        }
        hint.classList.add("noah-hint-out");
        setTimeout(() => hint.remove(), 250);
    }

    // 提供全局 reset 方便调试
    window.__noahResetWorkspaceHint = () => {
        try {
            localStorage.removeItem(HINT_KEY);
        } catch (_) {}
        console.log("[Noah] workspace hint reset. 刷新页面看引导。");
    };

    // ============================================================
    // 3. 主题切换：手机端改为收缩模式（不变）
    // ============================================================
    function setupThemeCollapse() {
        const wrap = document.getElementById("noah-theme-toggle");
        if (!wrap) {
            setTimeout(setupThemeCollapse, 200);
            return;
        }
        if (wrap.dataset.noahCollapsed) return;
        wrap.dataset.noahCollapsed = "1";

        const isMobile = () => MOBILE_MQ.matches;

        wrap.querySelectorAll("button").forEach((btn) => {
            const origOnclick = btn.onclick;
            btn.onclick = (e) => {
                if (isMobile()) {
                    if (!wrap.classList.contains("expanded")) {
                        e.preventDefault();
                        e.stopPropagation();
                        wrap.classList.add("expanded");
                        clearTimeout(wrap._collapseTimer);
                        wrap._collapseTimer = setTimeout(() => {
                            wrap.classList.remove("expanded");
                        }, 5000);
                        return false;
                    }
                    if (typeof origOnclick === "function") origOnclick.call(btn, e);
                    setTimeout(() => wrap.classList.remove("expanded"), 100);
                } else {
                    if (typeof origOnclick === "function") origOnclick.call(btn, e);
                }
            };
        });

        document.addEventListener("click", (e) => {
            if (isMobile() && !wrap.contains(e.target)) {
                wrap.classList.remove("expanded");
            }
        }, true);
    }

    // ============================================================
    // 应用
    // ============================================================
    function apply() {
        ensureMobileWorkspaceBtn();
        setupThemeCollapse();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", apply);
    } else {
        apply();
    }
    window.addEventListener("load", apply);

    MOBILE_MQ.addEventListener("change", ensureMobileWorkspaceBtn);
    setInterval(ensureMobileWorkspaceBtn, 3000);

    console.log("[Noah mobile] v4.3 UX enhancements loaded (workspace hint + right-aligned btn)");
})();
