/*
 * Noah PLM 首页(空状态)定制 v1
 * 运行时把 Hermes 默认空状态换成 PLM 循证诊疗欢迎页:
 *   Noah logo + 中文欢迎 + 模式说明 + PLM 起手建议
 * 只操作 DOM, 不改 webui 核心。
 */
(function () {
    "use strict";

    var STARTERS = [
        {
            label: "65岁女性,HER2阳性乳腺癌术后,想了解术后辅助治疗方案",
            msg: "患者:65岁女性,确诊HER2阳性乳腺癌,已手术,想了解术后辅助治疗方案。",
        },
        {
            label: "60岁男性,II期结肠癌根治术后,辅助化疗要不要做、怎么选",
            msg: "患者:60岁男性,II期结肠癌根治术后,想了解辅助化疗要不要做、怎么选。",
        },
        {
            label: "58岁男性,晚期非小细胞肺癌 EGFR突变,一线治疗方案怎么选",
            msg: "患者:58岁男性,晚期非小细胞肺癌,EGFR突变阳性,想了解一线治疗方案怎么选。",
        },
    ];

    function fillComposer(text) {
        // 找到输入框, 填入并聚焦(尽量兼容不同版本)
        var box =
            document.querySelector("#composerInput") ||
            document.querySelector("#composer textarea") ||
            document.querySelector('textarea[placeholder]') ||
            document.querySelector("textarea");
        if (!box) return false;
        box.value = text;
        box.dispatchEvent(new Event("input", { bubbles: true }));
        box.focus();
        return true;
    }

    function customize() {
        var empty = document.getElementById("emptyState");
        if (!empty || empty.dataset.noahPlmHome) return;

        // logo → Noah
        var logo = empty.querySelector(".empty-logo");
        if (logo) {
            logo.innerHTML =
                '<img src="/extensions/logo.png" alt="Noah Medical" ' +
                'style="width:76px;height:76px;object-fit:contain;border-radius:16px" />';
        }

        var h2 = empty.querySelector("h2");
        if (h2) { h2.textContent = "循证诊疗助手"; h2.removeAttribute("data-i18n"); }

        var p = empty.querySelector("p");
        if (p) { p.style.display = "none"; p.removeAttribute("data-i18n"); }

        // 模式 / 指南范围选择已移至输入框上方的常驻控件条 (noah-plm-composer.js)

        var grid = empty.querySelector(".suggestion-grid");
        if (grid) {
            grid.innerHTML = "";
            STARTERS.forEach(function (s) {
                var btn = document.createElement("button");
                btn.className = "suggestion";
                btn.type = "button";
                btn.textContent = s.label;
                btn.addEventListener("click", function () {
                    // 优先复用官方 data-msg 行为: 填入输入框(不直接发送, 让用户可改)
                    fillComposer(s.msg);
                });
                grid.appendChild(btn);
            });
        }

        empty.dataset.noahPlmHome = "1";
    }

    function loop() { try { customize(); } catch (e) {} }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", loop);
    } else {
        loop();
    }
    window.addEventListener("load", loop);
    // 空状态可能在切换会话时重新渲染, 定期补
    setInterval(loop, 1200);
    console.log("[Noah] PLM home v1 loaded");
})();
