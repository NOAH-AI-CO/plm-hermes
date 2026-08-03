/*
 * Noah Medical Brand Extension - v3.0
 * 主色 #00B0A0 (Noah logo)
 */
(function () {
    "use strict";

    const BRAND = {
        name: "Noah Medical AI",
        botName: "Noah",
        faviconUrl: "extensions/logo.png",
    };

    // ============================================================
    // 1. 注册 Noah skin（官方 API + 我们的 CSS 提供完整变量）
    // ============================================================
    function registerNoahSkin() {
        if (typeof window.registerHermesSkin !== "function") {
            setTimeout(registerNoahSkin, 100);
            return;
        }

        window.registerHermesSkin({
            name: "Noah Medical",
            value: "noah",
            label: "Noah Medical",
            colors: ["#00B0A0", "#007268", "#EFFAF9"],
            tokens: {
                "--accent": "#00B0A0",
                "--accent-hover": "#009588",
                "--accent-bg": "rgba(0, 176, 160, 0.08)",
                "--accent-bg-strong": "rgba(0, 176, 160, 0.18)",
                "--accent-text": "#007268",
                "--accent-rgb": "0, 176, 160",
                "--link": "#00B0A0",
            },
        });

        try {
            // 强制 noah 品牌皮:不再只在无 skin 时设, 避免 localStorage 残留
            // 导致整套青绿主题不生效(用户反馈"没感觉是 #00B0A0")。
            document.documentElement.dataset.skin = "noah";
            localStorage.setItem("hermes-skin", "noah");
        } catch (e) {}
    }

    // ============================================================
    // 2. 品牌 title / favicon / botName
    // ============================================================
    function forceTitle() {
        const cur = document.title || "";
        if (cur === BRAND.name) return;
        const hasUnread = cur.startsWith("● ");
        document.title = hasUnread ? "● " + BRAND.name : BRAND.name;
    }

    function replaceFavicon() {
        document.querySelectorAll('link[rel*="icon"]').forEach((link) => {
            if (link.href.indexOf(BRAND.faviconUrl) === -1) {
                link.href = BRAND.faviconUrl;
            }
        });
    }

    function forceBotName() {
        window._botName = BRAND.botName;
    }

    function localizeEmptyState() {
        const empty = document.getElementById("emptyState");
        if (!empty || empty.dataset.noahDone) return;
        const h2 = empty.querySelector("h2");
        const p = empty.querySelector("p");
        if (h2) h2.textContent = "有什么可以帮您的?";
        if (p) p.textContent = "循证医学 AI 助手 · 病例分析 · 指南查询 · 诊疗建议";
        empty.querySelectorAll(".empty-suggestion, .empty-suggestions button").forEach(
            (btn) => (btn.style.display = "none")
        );
        empty.dataset.noahDone = "1";
    }

    // ============================================================
    // 3. 主题切换按钮（浮在右下）
    // ============================================================
    const SUN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
    const MOON_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
    const SYSTEM_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>';

    // 官方 theme key = "hermes-theme"，值 = "light"/"dark"/"system"
    function getEffectiveTheme() {
        const t = localStorage.getItem("hermes-theme") || "system";
        return t;
    }

    function applyTheme(theme) {
        localStorage.setItem("hermes-theme", theme);
        let effective = theme;
        if (theme === "system") {
            effective = window.matchMedia("(prefers-color-scheme: dark)").matches
                ? "dark"
                : "light";
        }
        if (effective === "dark") {
            document.documentElement.classList.add("dark");
        } else {
            document.documentElement.classList.remove("dark");
        }
        // 更新按钮 active 状态
        updateActiveButton(theme);
    }

    function updateActiveButton(theme) {
        const wrap = document.getElementById("noah-theme-toggle");
        if (!wrap) return;
        wrap.querySelectorAll("button").forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.theme === theme);
        });
    }

    function buildThemeToggle() {
        if (document.getElementById("noah-theme-toggle")) return;
        if (!document.body) return;

        const wrap = document.createElement("div");
        wrap.id = "noah-theme-toggle";

        const themes = [
            { key: "light", icon: SUN_ICON, label: "浅色" },
            { key: "dark", icon: MOON_ICON, label: "深色" },
            { key: "system", icon: SYSTEM_ICON, label: "跟随系统" },
        ];

        for (const t of themes) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.dataset.theme = t.key;
            btn.title = t.label;
            btn.setAttribute("aria-label", t.label);
            btn.innerHTML = t.icon;
            btn.onclick = () => applyTheme(t.key);
            wrap.appendChild(btn);
        }
        document.body.appendChild(wrap);
        updateActiveButton(getEffectiveTheme());
    }

    // 监听系统深色模式变化（仅 system 模式时生效）
    function watchSystemScheme() {
        try {
            const mql = window.matchMedia("(prefers-color-scheme: dark)");
            mql.addEventListener("change", () => {
                if (getEffectiveTheme() === "system") {
                    applyTheme("system");
                }
            });
        } catch (e) {}
    }

    // ============================================================
    // 应用
    // ============================================================
    // 强制中文界面 + 亮色白底(用户要求)
    function forceLangAndLight() {
        try {
            // 主题: 默认亮色白底, 但尊重用户用右下角开关所选(存 hermes-theme), 不再每次强制回亮色,
            // 否则 setInterval 每 1.5s 抹掉 dark, 深色一点就被弹回白色。
            var _t = localStorage.getItem("hermes-theme");
            if (!_t) { _t = "light"; localStorage.setItem("hermes-theme", "light"); }
            var _eff = _t === "system"
                ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
                : _t;
            document.documentElement.classList.toggle("dark", _eff === "dark");
            // 中文:hermes-lang 在 boot 时读取, 改后需重载一次才全量翻译
            if (localStorage.getItem("hermes-lang") !== "zh-CN") {
                localStorage.setItem("hermes-lang", "zh-CN");
                if (!sessionStorage.getItem("noah-lang-reloaded")) {
                    sessionStorage.setItem("noah-lang-reloaded", "1");
                    location.reload();
                }
            }
        } catch (e) {}
    }

    function applyBrand() {
        try {
            forceLangAndLight();
            forceTitle();
            replaceFavicon();
            forceBotName();
            localizeEmptyState();
            buildThemeToggle();
        } catch (e) {
            console.warn("[Noah] Apply error:", e);
        }
    }

    registerNoahSkin();
    applyBrand();

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", applyBrand);
    }
    window.addEventListener("load", () => {
        applyBrand();
        watchSystemScheme();
    });

    setInterval(applyBrand, 1500);

    console.log("[Noah] Extension v3.0 loaded (logo color + theme toggle)");
})();
