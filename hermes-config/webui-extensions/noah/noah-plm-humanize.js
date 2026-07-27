/*
 * Noah PLM 步骤通俗化 —— 保留"思考过程", 把工具执行条(curl / 已读取某某技能 / JSON)
 * 换成医生看得懂的中文一句话。用 MutationObserver 即时响应渲染, 避免轮询造成的闪烁/高度跳动。
 */
(function () {
    "use strict";

    function labelFor(raw) {
        if (/search-guidelines|检索指南|正在检索匹配的临床指南/.test(raw)) return "🔎 正在检索匹配的临床指南…";
        if (/select_guideline/.test(raw)) return "📑 正在确认所选指南…";
        if (/clarify/.test(raw)) return "📋 正在梳理需要向您确认的信息…";
        if (/run[_-]?report|\/plm\/report|run-report/.test(raw)) return "📝 正在生成循证诊疗报告…";
        if (/plm-quick|quick/.test(raw)) return "💬 正在结合指南为您解答…";
        if (/extract_and_check|extract/.test(raw)) return "🧩 正在核对患者信息…";
        if (/curl|Shell|\b技能\b|skill|plm_evidence/.test(raw)) return "⏳ 正在处理…";
        return null;
    }

    function humanizeRows() {
        document.querySelectorAll(".tool-card-row").forEach(function (row) {
            var raw = row.textContent || "";                // textContent 忽略 display:none, 原文始终可匹配
            var label = labelFor(raw);
            if (!label) return;
            var chip = row.querySelector(":scope > .noah-tool-friendly");
            if (!chip) {
                chip = document.createElement("div");
                chip.className = "noah-tool-friendly";
                row.insertBefore(chip, row.firstChild);
            }
            if (chip.textContent !== label) chip.textContent = label;
            if (!row.classList.contains("noah-tool-humanized")) row.classList.add("noah-tool-humanized");
        });
        // 分组标题"正在运行命令和已读取技能" → "处理进度"
        document.querySelectorAll(".tool-call-group-label, .tool-worklog-label").forEach(function (el) {
            if (el.dataset.noahRelabeled) return;
            if (/命令|技能|tool|command|skill/i.test(el.textContent || "")) {
                el.textContent = "处理进度";
                el.dataset.noahRelabeled = "1";
            }
        });
    }

    function normalizeLegacyCitationLabels() {
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        var node;
        while ((node = walker.nextNode())) {
            var value = node.nodeValue || "";
            if (!/legacy_content_window\s*\|\s*page\d+/i.test(value)) continue;
            node.nodeValue = value.replace(
                /legacy_content_window\s*\|\s*page(\d+(?:\s*,\s*page\d+)*)/gi,
                function (_, pages) {
                    return "检索内容片段 " + pages.replace(/\s*,\s*page/gi, "、");
                }
            );
        }
    }

    function placeQuickModeProgress() {
        document.querySelectorAll(".agent-activity-group.tool-worklog-group").forEach(function (group) {
            var friendly = Array.prototype.slice.call(
                group.querySelectorAll(".noah-tool-friendly")
            );
            var isQuickMode = friendly.some(function (chip) {
                return /正在结合指南为您解答/.test(chip.textContent || "");
            });
            if (!isQuickMode || group.dataset.noahQuickPlaced) return;

            var reason = group.querySelector(".wl-reason");
            var blocks = group.closest(".assistant-turn-blocks");
            if (!reason || !blocks || reason.children.length < 2) return;

            var finalSegment = document.createElement("div");
            finalSegment.className = "assistant-segment noah-plm-final-answer";
            var finalBody = document.createElement("div");
            finalBody.className = "msg-body";
            while (reason.children.length > 1) {
                finalBody.appendChild(reason.children[1]);
            }
            finalSegment.appendChild(finalBody);
            group.insertAdjacentElement("afterend", finalSegment);
            group.dataset.noahQuickPlaced = "1";
        });
    }

    // 同一回合内, 已定稿(settled)的重复思考段去重 —— 消除"两个请选卡片"这类流式冗余。
    // 只处理 data-thinking-key 以 settled: 开头的(已定稿), 不碰流式中的块, 避免误伤。
    function dedupeThinking() {
        var seen = {};
        document.querySelectorAll(".agent-activity-thinking").forEach(function (el) {
            var key = el.getAttribute("data-thinking-key") || "";
            if (key.indexOf("settled:") !== 0) return;
            var turn = key.split(":")[1] || "";
            var t = (el.innerText || "").replace(/^思考过程/, "").replace(/\s+/g, "").replace(/[，。,.、；;：:]/g, "").slice(0, 24);
            if (!t) return;
            var k = turn + "|" + t;
            if (seen[k]) { el.style.display = "none"; } else { seen[k] = 1; }
        });
    }

    var scheduled = false;
    function schedule() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(function () {
            scheduled = false;
            try { humanizeRows(); } catch (e) {}
            try { normalizeLegacyCitationLabels(); } catch (e) {}
            try { placeQuickModeProgress(); } catch (e) {}
            try { dedupeThinking(); } catch (e) {}
        });
    }

    function start() {
        try { humanizeRows(); } catch (e) {}
        try { normalizeLegacyCitationLabels(); } catch (e) {}
        try { placeQuickModeProgress(); } catch (e) {}
        var root = document.getElementById("mainChat") || document.body;
        new MutationObserver(schedule).observe(root, { childList: true, subtree: true, characterData: true });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
    console.log("[Noah] PLM humanize (observer) loaded");
})();
