/*
 * Noah PLM Composer 控件条 v2 —— 常驻输入框上方
 *   第一行: 快速模式 / 完整报告模式 (单选)
 *   第二行: 指南范围 NCCN / CSCO / ESMO / CACA (单选)
 * 点选只更新状态, 不写输入框; 发送(send)瞬间才把 【模式·指南X】 前缀注入待发消息。
 * 只操作 DOM + 包裹全局 send()。
 */
(function () {
    "use strict";

    var MODES = ["快速模式", "完整报告模式"];
    var ORGS = ["NCCN", "CSCO", "ESMO", "CACA"];
    // 指南范围必选, 默认 NCCN(与后端默认一致); 不允许取消到空。
    var state = (window._noahPLM = window._noahPLM || { mode: "完整报告模式", org: "NCCN" });
    if (!state.org) state.org = "NCCN";

    function buildTag() {
        var t = "【" + state.mode;
        if (state.org) t += "·指南" + state.org;
        return t + "】";
    }

    function paint(bar) {
        bar.querySelectorAll("[data-mode]").forEach(function (b) {
            b.classList.toggle("active", b.dataset.mode === state.mode);
        });
        bar.querySelectorAll("[data-org]").forEach(function (b) {
            b.classList.toggle("active", state.org === b.dataset.org);
        });
    }

    function build() {
        var bar = document.createElement("div");
        bar.className = "noah-composer-bar";
        bar.id = "noahComposerBar";

        // 第一行: 模式(单选)
        var row1 = document.createElement("div");
        row1.className = "ncb-row";
        var seg = document.createElement("div");
        seg.className = "ncb-seg";
        MODES.forEach(function (m) {
            var b = document.createElement("button");
            b.type = "button"; b.dataset.mode = m; b.textContent = m;
            b.onclick = function () { state.mode = m; paint(bar); };
            seg.appendChild(b);
        });
        row1.appendChild(seg);

        // 第二行: 指南范围(单选)
        var row2 = document.createElement("div");
        row2.className = "ncb-row ncb-orgs";
        row2.appendChild(_span("ncb-label", "指南范围"));
        ORGS.forEach(function (o) {
            var b = document.createElement("button");
            b.type = "button"; b.dataset.org = o; b.textContent = o;
            b.onclick = function () {
                state.org = o;   // 单选必选, 始终保留一个(默认 NCCN)
                paint(bar);
            };
            row2.appendChild(b);
        });

        bar.appendChild(row1);
        bar.appendChild(row2);
        paint(bar);
        return bar;
    }

    function _span(cls, txt) { var s = document.createElement("span"); s.className = cls; s.textContent = txt; return s; }

    function mount() {
        var boxEl = document.querySelector(".composer-box") || document.getElementById("composerBox");
        if (boxEl && !document.getElementById("noahComposerBar")) {
            boxEl.insertBefore(build(), boxEl.firstChild);
        }
        wrapSend();
        bindSendEvents();
        try { stripTagsInBubbles(); } catch (e) {}
        try { syncStopBtn(); } catch (e) {}
        try { fixSendTooltip(); } catch (e) {}
    }

    // 发送键的 has-tooltip 走 data-tooltip, 核心里是英文 "Send message"(与其中文 title 不一致, 看着像 bug)。
    // 统一成中文; 核心重渲染会重置, 故放进 300ms tick 保持。
    function fixSendTooltip() {
        var send = document.getElementById("btnSend");
        if (send && /send message/i.test(send.getAttribute("data-tooltip") || "")) {
            send.setAttribute("data-tooltip", "发送消息");
        }
    }

    // 常驻停止键: agent 流式/忙碌时显示在发送键左侧, 一键中止(不受输入框有无内容影响)。
    function syncStopBtn() {
        var send = document.getElementById("btnSend");
        if (!send || !send.parentNode) return;
        var stop = document.getElementById("noahStopBtn");
        if (!stop) {
            stop = document.createElement("button");
            stop.id = "noahStopBtn"; stop.type = "button";
            stop.title = "停止生成"; stop.setAttribute("aria-label", "停止生成");
            stop.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg><span>停止</span>';
            stop.onclick = function () {
                try { if (typeof cancelStream === "function") cancelStream("user-stop"); } catch (e) {}
                try { if (typeof window.noahStopReport === "function") window.noahStopReport(); } catch (e) {}
            };
            send.parentNode.insertBefore(stop, send);
        }
        // 只在"当前正看的这个会话"真有流在跑时才显示。
        // 早先用 btnSend 的 data-action + 全局 _noahReportStreaming 判定, 两者都是全局的:
        // 别的会话在跑时新建/切到空会话, 这里会误显示停止键(data-action 会是 queue)。
        // S.activeStreamId 由 loadSession/newSession 按当前会话维护, 是准确信号;
        // 报告流则看它的面板节点还在不在当前视图里。
        var chatBusy = false;
        try {
            var st = (typeof S !== "undefined" && S) || window.S;
            chatBusy = !!(st && st.activeStreamId);
        } catch (e) {}
        var reportBusy = (window._noahReportStreams || []).some(function (c) {
            return c && c.wrap && document.body.contains(c.wrap);
        });
        stop.style.display = (chatBusy || reportBusy) ? "inline-flex" : "none";
    }

    // 发送带的 【模式·指南X】 前缀是给 agent 识别用的; 在渲染的用户气泡里把它视觉抹掉。
    var TAG_RE = /^\s*【(?:快速模式|完整报告模式)[^】]*】\s*/;
    var INTERNAL_SELECTION_CONTEXT_RE = /[；;]\s*selected_doc_id=[\s\S]*$/;
    function stripTagsInBubbles() {
        var bodies = document.querySelectorAll(".msg-body");
        for (var i = 0; i < bodies.length; i++) {
            var el = bodies[i];
            if (el.dataset.noahTagStripped) continue;
            // 找第一个文本节点(markdown 渲染后通常在首个 <p>)
            var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
            var node = walker.nextNode();
            if (node && TAG_RE.test(node.nodeValue)) {
                node.nodeValue = node.nodeValue.replace(TAG_RE, "");
                el.dataset.noahTagStripped = "1";
            } else if (node && node.nodeValue && node.nodeValue.indexOf("【") === -1) {
                // 首节点没 tag(assistant 消息或已处理)→ 标记跳过, 避免重复扫
                el.dataset.noahTagStripped = "1";
            }
            if (node && INTERNAL_SELECTION_CONTEXT_RE.test(node.nodeValue || "")) {
                node.nodeValue = node.nodeValue.replace(INTERNAL_SELECTION_CONTEXT_RE, "。");
            }
        }
    }

    function observeMessageBubbles() {
        if (window._noahPLMBubbleObserver || !document.body) return;
        window._noahPLMBubbleObserver = new MutationObserver(function (records) {
            for (var i = 0; i < records.length; i++) {
                if (records[i].addedNodes.length) {
                    stripTagsInBubbles();
                    return;
                }
            }
        });
        window._noahPLMBubbleObserver.observe(document.body, { childList: true, subtree: true });
    }

    function injectTag() {
        var box = document.getElementById("msg");
        if (!box) return;
        var value = box.value || "";
        if (value.trim() && !/^【[^】]*】/.test(value.trim())) {
            box.value = buildTag() + " " + value;
            box.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }

    // 兼容旧版仍暴露全局 send() 的 WebUI。
    function wrapSend() {
        if (window._noahSendWrapped || typeof window.send !== "function") return;
        var orig = window.send;
        window.send = async function () {
            try { injectTag(); } catch (e) {}
            return orig.apply(this, arguments);
        };
        window._noahSendWrapped = true;
    }

    // 新版核心将 send() 封装在模块作用域内。捕获阶段先于核心按钮/键盘处理器运行，
    // 因此可确保 POST /api/chat/start 收到 PLM 前缀。
    function bindSendEvents() {
        if (window._noahPLMSendEventsBound) return;
        document.addEventListener("click", function (event) {
            var button = event.target && event.target.closest && event.target.closest("#btnSend");
            if (button) injectTag();
        }, true);
        document.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey && !event.isComposing) injectTag();
        }, true);
        window._noahPLMSendEventsBound = true;
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
    else mount();
    observeMessageBubbles();
    setInterval(mount, 1500);
    setInterval(function () { try { syncStopBtn(); } catch (e) {} try { fixSendTooltip(); } catch (e) {} }, 300);  // 停止键跟手 + 发送键中文提示
    console.log("[Noah] PLM composer bar v2 loaded");
})();
