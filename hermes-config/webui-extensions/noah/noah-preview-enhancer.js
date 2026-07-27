/*
 * Noah Medical - Workspace preview enhancer (v3 - 从原始 md 解析引用)
 *
 * v3 变化：
 *   Hook renderMarkdownPreviewContent 时截获原始 markdown 文本 content
 *   直接从 md 源文解析参考文献（不依赖 DOM，绕过 renderMd 的破坏性渲染）
 *   把解析结果存到 window.__noahMdRefs 供 noah-citations.js 使用
 */
(function () {
    "use strict";

    // 从原始 markdown 解析参考文献段
    // 返回 Map<citeKey, {apa, original, url}>
    function parseMdReferences(md) {
        const refs = new Map();
        if (!md) return refs;

        const lines = md.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");

        // 找 "## 参考文献" 或 "## References"
        let refStartIdx = -1;
        for (let i = 0; i < lines.length; i++) {
            const m = lines[i].match(/^##\s+(.+)/);
            if (m && (m[1].includes("参考文献") || m[1].includes("References"))) {
                refStartIdx = i + 1;
                break;
            }
        }
        if (refStartIdx < 0) return refs;

        // 逐条解析 ### (Key) 后的内容
        let currentKey = null;
        let apaLines = [];
        let quoteLines = [];
        let inQuote = false;

        function flush() {
            if (!currentKey) return;
            // APA 拼接：跨行合并为单行，去多余空白
            const apa = apaLines.join(" ").replace(/\s+/g, " ").trim();
            const quote = quoteLines.join("\n").trim();
            // 从 APA 里提取 URL（第一个 https://...）
            const urlMatch = apa.match(/https?:\/\/\S+/);
            const url = urlMatch ? urlMatch[0].replace(/[.,;]+$/, "") : null;
            refs.set(currentKey, { apa, original: quote, url });
            apaLines = [];
            quoteLines = [];
            inQuote = false;
        }

        for (let i = refStartIdx; i < lines.length; i++) {
            const line = lines[i];

            // 遇到下一个 ## heading 停止
            if (/^##\s/.test(line) && !/^###/.test(line)) break;

            // ### (Key) 新条目
            const h3 = line.match(/^###\s+\(([^)]+)\)\s*$/);
            if (h3) {
                flush();
                currentKey = h3[1].trim().replace(/\s+/g, " ");
                continue;
            }

            if (!currentKey) continue;

            // > blockquote (原文摘录)
            if (line.startsWith(">")) {
                inQuote = true;
                quoteLines.push(line.replace(/^>\s?/, ""));
                continue;
            }

            // 空行 → 结束 quote（如果正在 quote 中），否则忽略
            if (line.trim() === "") {
                inQuote = false;
                continue;
            }

            // 普通行 → 加进 APA
            if (!inQuote) {
                apaLines.push(line.trim());
            } else {
                // quote 后紧跟非 > 的行 → 结束 quote，作为下一段 APA 的开始
                inQuote = false;
                apaLines.push(line.trim());
            }
        }
        flush();

        return refs;
    }

    // 触发一次增强
    function enhancePreview(root) {
        if (!root) return;
        try {
            if (typeof window.renderMermaidBlocks === "function") {
                window.renderMermaidBlocks(root);
            }
            if (typeof window.renderKatexBlocks === "function") {
                window.renderKatexBlocks(root);
            }
            if (typeof window.__noahScanCitations === "function") {
                window.__noahScanCitations(root);
            }
        } catch (e) {
            console.warn("[Noah preview] enhance error:", e);
        }
    }

    // Hook 官方 renderMarkdownPreviewContent
    function hookOfficial() {
        if (typeof window.renderMarkdownPreviewContent !== "function") return false;
        if (window.__noahPreviewHooked) return true;

        const orig = window.renderMarkdownPreviewContent;
        window.renderMarkdownPreviewContent = function (data) {
            const target = (data && data.el) || document.getElementById("previewMd");
            const rawMd = (data && data.content) || "";

            // ⭐ 关键：从原始 md 解析参考文献（不依赖 DOM）
            const refs = parseMdReferences(rawMd);
            window.__noahMdRefs = refs;
            console.log("[Noah preview] parsed", refs.size, "refs from raw md");

            // 卸载旧引用 span
            if (target && typeof window.__noahResetCitations === "function") {
                window.__noahResetCitations(target);
            }

            const ret = orig.apply(this, arguments);

            requestAnimationFrame(() => {
                setTimeout(() => enhancePreview(target), 0);
            });
            return ret;
        };
        window.__noahPreviewHooked = true;
        console.log("[Noah preview] hook installed (v3 - raw md parsing)");
        return true;
    }

    if (!hookOfficial()) {
        window.addEventListener("load", () => {
            let tries = 0;
            const timer = setInterval(() => {
                if (hookOfficial() || ++tries > 40) clearInterval(timer);
            }, 250);
        });
    }

    console.log("[Noah preview] enhancer v3 loaded (raw md parsing)");
})();


