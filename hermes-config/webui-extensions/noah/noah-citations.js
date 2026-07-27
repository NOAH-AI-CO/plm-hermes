/*
 * Noah Medical - Citations popover extension
 *
 * 功能：
 * 1. 扫描 .msg-body 里的 (作者, 年份) 内文引用
 * 2. 从末尾"## 参考文献"里提取每条参考的 APA 全文 + 原文摘录
 * 3. 将内文引用变成 <sup class="noah-cite" data-key="..."> 可点击元素
 * 4. 悬停时显示卡片预览，点击时固定卡片直到再次点击或按 ESC
 *
 * 依赖：无（原生 DOM + 官方 EXTENSIONS 允许的操作）
 *
 * 触发格式：
 *   - 正文：(Smith, 2024) / (Smith & Lee, 2020) / (Smith et al., 2019) / (NCCN, 2025)
 *   - 参考文献列表：以 ### (Smith, 2024) 开头的 h3
 */

(function () {
    "use strict";

    // 匹配 (作者, 年份) —— 支持多种复杂形式：
    //   (Smith, 2024)
    //   (Smith & Lee, 2020)
    //   (Smith et al., 2019)
    //   (Forde et al., 2022)
    //   (NCCN, 2025)
    //   (CACA、中华医学会, 2024)
    //   (张三 等, 2023)
    // 但**不匹配**含分号的（如 CheckMate 816, Forde et al., 2022; OS final 2025）
    // 允许作者含: 中文字符、英文字母、点、连字符、空格、& 号、逗号（如"作者 A, 作者 B, 2020"）、et al.、"等"
    const CITE_REGEX = /\(([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z\.\-\s&,、等]{0,80}?),\s*(\d{4}[a-z]?)\)/g;

    // 全局卡片状态
    let _activeCard = null;      // DOM 元素
    let _isPinned = false;       // 是否被点击固定
    let _hoverTimer = null;

    // ============================================================
    // 步骤 1: 从消息末尾"## 参考文献"提取所有条目
    // 返回 Map<citeKey, {apa, original, url}>
    //
    // 优先用 window.__noahMdRefs（workspace preview enhancer 从原始 md 解析的，最可靠）
    // fallback: 从 DOM 解析（消息气泡场景，没有原始 md 可用）
    // ============================================================
    function parseReferences(msgBody) {
        // 优先 raw md 解析（workspace preview 场景）
        if (msgBody.id === "previewMd" && window.__noahMdRefs && window.__noahMdRefs.size > 0) {
            return window.__noahMdRefs;
        }

        const refs = new Map();

        // 找 "## 参考文献" 或 "## References" heading
        const headings = msgBody.querySelectorAll("h2");
        let refHeading = null;
        for (const h of headings) {
            const t = (h.textContent || "").trim();
            if (t === "参考文献" || t === "References" || t.includes("参考文献") || t.includes("References")) {
                refHeading = h;
                break;
            }
        }
        if (!refHeading) return refs;

        // 遍历 refHeading 之后的所有兄弟元素，直到遇到下一个 h2 或末尾
        let node = refHeading.nextElementSibling;
        let currentKey = null;
        let currentApa = [];
        let currentQuote = [];
        let currentUrl = null;

        function flush() {
            if (currentKey) {
                refs.set(currentKey, {
                    apa: currentApa.join(" ").trim(),
                    original: currentQuote.join("\n").trim(),
                    url: currentUrl,
                });
            }
            currentApa = [];
            currentQuote = [];
            currentUrl = null;
        }

        while (node && node.tagName !== "H2") {
            // h3 是新条目开始
            if (node.tagName === "H3") {
                flush();
                const t = (node.textContent || "").trim();
                // 匹配 (Author, Year) 格式
                const m = t.match(/^\(([^)]+)\)$/);
                if (m) {
                    currentKey = normalizeKey(m[1]);
                } else {
                    currentKey = null;
                }
            } else if (currentKey) {
                // 兼容各种可能的渲染结果
                if (node.tagName === "BLOCKQUOTE") {
                    const txt = (node.textContent || "").trim();
                    if (txt) currentQuote.push(txt);
                } else if (node.tagName === "UL" || node.tagName === "OL") {
                    node.querySelectorAll("li").forEach((li) => {
                        const t = extractTextPreservingLinks(li);
                        if (t) currentApa.push(t);
                        const link = li.querySelector("a[href^='http']");
                        if (link && !currentUrl) currentUrl = link.href;
                    });
                } else {
                    // ⭐ 关键：用 extractTextPreservingLinks 保留完整 URL
                    // （textContent 会把 <a href="...(24)01756-2">https://...(24</a>) 变成两段文字）
                    const txt = extractTextPreservingLinks(node);
                    if (txt) currentApa.push(txt);
                    // 抓 URL（用 <a href> 而不是从文本解析）
                    const link = (node.querySelector && node.querySelector("a[href^='http']"))
                              || (node.tagName === "A" && node.href.startsWith("http") ? node : null);
                    if (link && !currentUrl) currentUrl = link.href;
                }
            }
            node = node.nextElementSibling;
        }
        flush();

        // 如果 refs 为空但 h2 存在，可能是"扁平"结构（无 h3，每段是一条引用）
        // 例如：AI 用 "1. Xxx (2024). ..." 列表式列出。这种情况尝试解析。
        if (refs.size === 0) {
            let n = refHeading.nextElementSibling;
            while (n && n.tagName !== "H2") {
                if (n.tagName === "P" || n.tagName === "LI") {
                    const txt = (n.textContent || "").trim();
                    // 从段落里抽 (Author, Year)
                    const m = txt.match(/\(([\u4e00-\u9fa5A-Za-z][^)]{0,80}?),\s*(\d{4}[a-z]?)\)/);
                    if (m) {
                        const key = normalizeKey(`${m[1]}, ${m[2]}`);
                        const link = n.querySelector("a[href^='http']");
                        refs.set(key, {
                            apa: txt,
                            original: "",
                            url: link ? link.href : null,
                        });
                    }
                }
                n = n.nextElementSibling;
            }
        }

        return refs;
    }

    // 规范化 key：去多余空白，供匹配
    function normalizeKey(s) {
        return s.trim().replace(/\s+/g, " ");
    }

    // 从元素里提取文本，但对 <a href> 使用其 href 而非可见文本
    // 关键：markdown 渲染器把 `https://doi.org/xxx(24)yyy` 截断成
    //   <a href="...(24)yyy">https://doi.org/xxx(24</a>)yyy
    // textContent 会拼成 "https://doi.org/xxx(24)yyy"（错的位置多个字符）
    // 或者干脆丢失 URL 后半段。用 href 拿完整 URL 才可靠。
    function extractTextPreservingLinks(el) {
        if (!el) return "";
        if (el.nodeType === Node.TEXT_NODE) return el.nodeValue || "";
        if (el.nodeType !== Node.ELEMENT_NODE) return "";

        // <a href="http..."> 用 href 覆盖可见文本
        if (el.tagName === "A" && el.href && el.href.startsWith("http")) {
            // 如果可见文本就是 URL（可能被截断），用 href
            const visible = (el.textContent || "").trim();
            if (visible.startsWith("http") || visible.length < el.href.length) {
                return el.href;
            }
            // 否则可能是 [title](url) 形式，保留可见文本
            return visible;
        }

        // 递归拼接子节点
        let out = "";
        for (const child of el.childNodes) {
            out += extractTextPreservingLinks(child);
        }
        return out.trim().replace(/\s+/g, " ");
    }

    // ============================================================
    // 步骤 2: 扫描正文，将 (Author, Year) 变成 <span class="noah-cite">
    // ============================================================
    function decorateCitations(msgBody, refs) {
        if (!refs.size) return;
        if (msgBody.dataset.noahCiteDone === "1") return;

        // 遍历文本节点，跳过 code/pre/已包过的 noah-cite / 参考文献 h3
        const walker = document.createTreeWalker(msgBody, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const p = node.parentNode;
                if (!p) return NodeFilter.FILTER_REJECT;
                const tag = p.tagName;
                if (tag === "CODE" || tag === "PRE" || tag === "SCRIPT" || tag === "STYLE") {
                    return NodeFilter.FILTER_REJECT;
                }
                // 关键：跳过已经在 noah-cite 内部的文本，防止死循环
                if (p.classList && p.classList.contains("noah-cite")) {
                    return NodeFilter.FILTER_REJECT;
                }
                // 祖先里有 noah-cite 也跳过
                if (p.closest && p.closest(".noah-cite")) {
                    return NodeFilter.FILTER_REJECT;
                }
                // 跳过参考文献章节里的 (Author, Year)（那是 h3 本身，不需要变卡片）
                if (tag === "H3") return NodeFilter.FILTER_REJECT;
                if (!node.nodeValue || !CITE_REGEX.test(node.nodeValue)) {
                    CITE_REGEX.lastIndex = 0;
                    return NodeFilter.FILTER_REJECT;
                }
                CITE_REGEX.lastIndex = 0;
                return NodeFilter.FILTER_ACCEPT;
            },
        });

        const toReplace = [];
        let n;
        while ((n = walker.nextNode())) toReplace.push(n);

        for (const node of toReplace) {
            const text = node.nodeValue;
            const frag = document.createDocumentFragment();
            let lastIndex = 0;
            CITE_REGEX.lastIndex = 0;
            let match;
            while ((match = CITE_REGEX.exec(text)) !== null) {
                const [full, author, year] = match;
                const key = normalizeKey(`${author}, ${year}`);
                if (!refs.has(key)) continue; // 引用不在参考列表里，跳过

                // 前面文字
                if (match.index > lastIndex) {
                    frag.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
                }

                // 引用元素（用 span 而不是 sup，避免 sup 默认样式冲突）
                const cite = document.createElement("span");
                cite.className = "noah-cite";
                cite.setAttribute("data-cite-key", key);
                cite.setAttribute("tabindex", "0");
                cite.setAttribute("role", "button");
                cite.setAttribute("aria-label", `引用: ${key}`);
                cite.textContent = full; // 保留 (Author, Year) 原文本
                frag.appendChild(cite);

                lastIndex = match.index + full.length;
            }
            if (lastIndex < text.length) {
                frag.appendChild(document.createTextNode(text.slice(lastIndex)));
            }
            if (lastIndex > 0) {
                node.parentNode.replaceChild(frag, node);
            }
        }

        msgBody.dataset.noahCiteDone = "1";
    }

    // ============================================================
    // 步骤 3: 卡片渲染
    // ============================================================
    function buildCard(citeKey, refData) {
        const card = document.createElement("div");
        card.className = "noah-cite-card";
        card.setAttribute("role", "dialog");
        card.setAttribute("aria-label", `引用详情: ${citeKey}`);

        // 关闭按钮（浮在右上角）
        const closeBtn = document.createElement("button");
        closeBtn.className = "noah-cite-card-close";
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", "关闭卡片");
        closeBtn.textContent = "×";
        closeBtn.onclick = (e) => { e.stopPropagation(); hideCard(true); };
        card.appendChild(closeBtn);

        // 引用键（小标签）
        const keyLabel = document.createElement("div");
        keyLabel.className = "noah-cite-card-key";
        keyLabel.textContent = citeKey;
        card.appendChild(keyLabel);

        // ⭐ APA 全文（顶部核心内容）
        const apaDiv = document.createElement("div");
        apaDiv.className = "noah-cite-card-apa";
        if (refData.apa) {
            apaDiv.innerHTML = renderInlineHtml(refData.apa);
        } else {
            apaDiv.innerHTML = '<em style="opacity:0.6">（未解析到 APA 引用全文，请检查 md 里 ### (Key) 下方是否有空行分隔）</em>';
        }
        card.appendChild(apaDiv);

        // URL（可点跳外部）
        if (refData.url) {
            const urlDiv = document.createElement("div");
            urlDiv.className = "noah-cite-card-url";
            const a = document.createElement("a");
            a.href = refData.url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = "查看原文 →";
            urlDiv.appendChild(a);
            card.appendChild(urlDiv);
        }

        // 原文摘录
        if (refData.original) {
            const sepDiv = document.createElement("div");
            sepDiv.className = "noah-cite-card-sep";
            sepDiv.textContent = "原文摘录";
            card.appendChild(sepDiv);

            const quoteDiv = document.createElement("div");
            quoteDiv.className = "noah-cite-card-quote";
            quoteDiv.textContent = refData.original;
            card.appendChild(quoteDiv);
        }

        return card;
    }

    // 简单 inline 渲染（保留 <em>斜体<em>，转 https:// 链接，其他转义）
    function renderInlineHtml(text) {
        const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        let out = escape(text);
        // *xxx* → <em>xxx</em>
        out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
        // URL 匹配：允许括号内嵌（DOI 常见 S0140-6736(24)01756-2）
        // 匹配到空格/引号/尖括号才停
        out = out.replace(/(https?:\/\/[^\s"'<>]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
        return out;
    }

    // ============================================================
    // 步骤 4: 显示 / 隐藏卡片
    // ============================================================
    function showCard(anchor, refData, citeKey, pin) {
        hideCard(true); // 先清

        const card = buildCard(citeKey, refData);
        document.body.appendChild(card);
        _activeCard = card;
        _isPinned = !!pin;
        card.classList.toggle("pinned", _isPinned);

        // 定位：优先在 anchor 上方，空间不够放下方
        positionCard(card, anchor);

        // 点击卡片外部关闭（仅 pinned 时）
        setTimeout(() => {
            document.addEventListener("click", _outsideClickHandler, true);
            document.addEventListener("keydown", _escHandler);
        }, 10);
    }

    function positionCard(card, anchor) {
        const rect = anchor.getBoundingClientRect();
        const cardW = 380;
        const cardH = card.offsetHeight || 200;
        const gap = 8;
        const scrollY = window.scrollY;
        const scrollX = window.scrollX;
        const viewportH = window.innerHeight;
        const viewportW = window.innerWidth;

        let top, left;

        // ⭐ 默认下方（不遮挡引用），除非下方空间不够
        const spaceBelow = viewportH - rect.bottom - gap - 10;
        const spaceAbove = rect.top - gap - 10;
        if (spaceBelow >= cardH || spaceBelow >= spaceAbove) {
            // 放下方（就算不够也放这里，因为卡片可滚）
            top = scrollY + rect.bottom + gap;
        } else {
            // 放上方
            top = scrollY + rect.top - cardH - gap;
        }

        // 水平：左对齐 anchor（更符合"就在引用下方"的直觉），越界时收回
        left = scrollX + rect.left;
        if (left + cardW > scrollX + viewportW - 12) {
            left = scrollX + viewportW - cardW - 12;
        }
        if (left < scrollX + 12) left = scrollX + 12;

        card.style.top = top + "px";
        card.style.left = left + "px";
        card.style.width = cardW + "px";
    }

    function hideCard(force) {
        if (!_activeCard) return;
        if (_isPinned && !force) return;
        _activeCard.remove();
        _activeCard = null;
        _isPinned = false;
        document.removeEventListener("click", _outsideClickHandler, true);
        document.removeEventListener("keydown", _escHandler);
    }

    function _outsideClickHandler(e) {
        if (!_activeCard) return;
        if (_activeCard.contains(e.target)) return;
        // 点击其他 cite 会由 handleClick 重新 showCard，无需在这里处理
        if (e.target.classList && e.target.classList.contains("noah-cite")) return;
        hideCard(true);
    }

    function _escHandler(e) {
        if (e.key === "Escape") hideCard(true);
    }

    // ============================================================
    // 步骤 5: 事件绑定 (delegate 到 document.body)
    //
    // 注意点：
    //   - mouseenter/mouseleave 不冒泡，必须用 mouseover/mouseout
    //   - closest(".msg-body, #previewMd") 兼容消息气泡 + workspace 预览
    // ============================================================
    function bindEvents() {
        if (document.body.dataset.noahCiteBound === "1") return;
        document.body.dataset.noahCiteBound = "1";

        // 悬停 -> 显示（mouseover 冒泡）
        document.body.addEventListener("mouseover", (e) => {
            const t = e.target;
            if (!t.classList || !t.classList.contains("noah-cite")) return;
            if (_isPinned) return;
            clearTimeout(_hoverTimer);
            _hoverTimer = setTimeout(() => {
                const key = t.getAttribute("data-cite-key");
                const container = t.closest(".msg-body, #previewMd");
                if (!container) return;
                const refs = _refsCache.get(container) || parseReferences(container);
                _refsCache.set(container, refs);
                if (refs.has(key)) {
                    showCard(t, refs.get(key), key, false);
                }
            }, 150);
        });

        // 悬停离开 -> 隐藏（mouseout 冒泡）
        document.body.addEventListener("mouseout", (e) => {
            const t = e.target;
            if (!t.classList || !t.classList.contains("noah-cite")) return;
            if (_isPinned) return;
            clearTimeout(_hoverTimer);
            _hoverTimer = setTimeout(() => {
                if (_activeCard && _activeCard.matches(":hover")) return;
                hideCard();
            }, 200);
        });

        // 点击 -> 固定
        document.body.addEventListener("click", (e) => {
            const t = e.target;
            if (!t.classList || !t.classList.contains("noah-cite")) return;
            e.preventDefault();
            e.stopPropagation();
            const key = t.getAttribute("data-cite-key");
            const container = t.closest(".msg-body, #previewMd");
            if (!container) return;
            const refs = _refsCache.get(container) || parseReferences(container);
            _refsCache.set(container, refs);
            if (refs.has(key)) {
                showCard(t, refs.get(key), key, true);
            }
        });

        // 键盘：Enter / Space 触发
        document.body.addEventListener("keydown", (e) => {
            const t = e.target;
            if (!t.classList || !t.classList.contains("noah-cite")) return;
            if (e.key !== "Enter" && e.key !== " ") return;
            e.preventDefault();
            t.click();
        });

        console.log("[Noah cite] events bound (mouseover + click on document.body)");
    }

    // 缓存：每个 .msg-body 的引用 map
    const _refsCache = new WeakMap();

    // ============================================================
    // 步骤 6: 定期扫描新消息 + workspace 预览
    // ============================================================
    function scanRoot(root) {
        if (!root) return;
        try {
            // 已扫过就跳过（不重复）
            if (root.dataset.noahCiteDone === "1") return;
            const refs = parseReferences(root);
            if (refs.size > 0) {
                decorateCitations(root, refs);
                _refsCache.set(root, refs);
            }
        } catch (e) {
            console.warn("[Noah cite] scan root error:", e);
        }
    }

    // 供外部（如切换文件）主动重置扫描状态
    function resetScan(root) {
        if (!root) return;
        // 先卸载已包的 span，还原为纯文本
        try {
            root.querySelectorAll(".noah-cite").forEach((el) => {
                const t = document.createTextNode(el.textContent);
                el.parentNode.replaceChild(t, el);
            });
            // 合并相邻文本节点，避免下次匹配失效
            root.normalize();
        } catch (e) {}
        delete root.dataset.noahCiteDone;
    }
    window.__noahResetCitations = resetScan;

    function scanAllMsgs() {
        try {
            const msgs = document.querySelectorAll(".msg-body");
            for (const msg of msgs) {
                if (msg.dataset.noahCiteDone === "1") continue;
                const refs = parseReferences(msg);
                if (refs.size > 0) {
                    decorateCitations(msg, refs);
                    _refsCache.set(msg, refs);
                }
            }
            // Workspace preview
            const preview = document.getElementById("previewMd");
            if (preview) scanRoot(preview);
        } catch (e) {
            console.warn("[Noah cite] scan error:", e);
        }
    }

    // 暴露给 preview-enhancer 用
    window.__noahScanCitations = scanRoot;

    function init() {
        bindEvents();
        scanAllMsgs();
        // MutationObserver: 监听新增消息
        const observer = new MutationObserver(() => {
            clearTimeout(observer._t);
            observer._t = setTimeout(scanAllMsgs, 400);
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
    window.addEventListener("load", scanAllMsgs);

    console.log("[Noah cite] Citation popover loaded");
})();
