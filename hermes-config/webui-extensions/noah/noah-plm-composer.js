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

    // 模式/指南范围原本是一份全局状态, 切会话时不跟着走: 在 A 会话选了完整报告模式,
    // 去 B 会话选了快速模式, 再切回 A 仍显示快速模式(且发送时会带错的前缀)。
    // 改为按会话记忆; 没有记录的会话(比如刷新后)从它自己的历史消息里推断 —— 每条用户
    // 消息发送时都带了 【模式·指南X】 前缀, 那才是这个会话真正用过的设置。
    var TAG_PARSE_RE = /【(快速模式|完整报告模式)(?:·指南([A-Za-z]+))?】/;
    var _bySession = Object.create(null);
    var _lastSid = null;
    var _inferTries = 0;

    function currentSid() {
        try {
            var st = (typeof S !== "undefined" && S) || window.S;
            return (st && st.session && st.session.session_id) || null;
        } catch (e) { return null; }
    }

    function inferFromMessages() {
        try {
            var st = (typeof S !== "undefined" && S) || window.S;
            var msgs = (st && st.messages) || [];
            for (var i = msgs.length - 1; i >= 0; i--) {
                var m = msgs[i];
                if (!m || m.role !== "user") continue;
                var hit = TAG_PARSE_RE.exec(String(m.content || ""));
                if (hit) return { mode: hit[1], org: hit[2] || state.org };
            }
        } catch (e) {}
        return null;
    }

    function applyState(next) {
        if (!next) return false;
        if (next.mode) state.mode = next.mode;
        if (next.org) state.org = next.org;
        var bar = document.getElementById("noahComposerBar");
        if (bar) paint(bar);
        return true;
    }

    function rememberCurrent() {
        var sid = currentSid();
        if (sid) _bySession[sid] = { mode: state.mode, org: state.org };
    }

    function syncSessionState() {
        var sid = currentSid();
        if (sid !== _lastSid) {
            if (_lastSid) _bySession[_lastSid] = { mode: state.mode, org: state.org };
            _lastSid = sid;
            _inferTries = 0;
            if (sid && _bySession[sid]) { applyState(_bySession[sid]); return; }
        }
        // 切过来时 messages 可能还没加载完, 再试几拍(约 3 秒)。
        if (sid && !_bySession[sid] && _inferTries < 10) {
            _inferTries++;
            var guess = inferFromMessages();
            if (guess) { applyState(guess); _bySession[sid] = { mode: state.mode, org: state.org }; }
        }
    }

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
            b.onclick = function () { state.mode = m; rememberCurrent(); paint(bar); };
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
                rememberCurrent();
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
        wrapFetchForTag();
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

    var _stopIdleSince = 0;
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
        // 忙碌状态在收尾阶段会短暂反复(取消/重连时 activeStreamId 会先清后置), 这个函数
        // 每 300ms 跑一次, 直接跟随就会让按钮反复出现消失, 表现为发送区抽搐(Firefox 明显)。
        // 出现即时, 隐藏则要连续空闲 1 秒, 抖动就被吃掉了。
        var busy = chatBusy || reportBusy;
        if (busy) {
            _stopIdleSince = 0;
            if (stop.style.display === "none") stop.style.display = "inline-flex";
            return;
        }
        if (!_stopIdleSince) _stopIdleSince = Date.now();
        if (Date.now() - _stopIdleSince >= 1000 && stop.style.display !== "none") {
            stop.style.display = "none";
        }
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

    // 前缀只注入到发出去的请求体里, 不写进可见输入框 —— 它是给 agent 识别模式用的,
    // 不该让医生看到(以前写进 textarea, 用户能看见 "【完整报告模式·指南NCCN】 你好",
    // 而且它还会被服务端当成首条消息拿去生成会话标题, 把标题也污染了)。
    function _tagPayload(bodyStr) {
        var d;
        try { d = JSON.parse(bodyStr); } catch (e) { return null; }
        if (!d || typeof d !== "object") return null;
        var key = ("message" in d) ? "message" : (("text" in d) ? "text" : null);
        if (!key) return null;
        var v = String(d[key] == null ? "" : d[key]);
        if (!v.trim() || /^【[^】]*】/.test(v.trim())) return null;
        d[key] = buildTag() + " " + v;
        try { return JSON.stringify(d); } catch (e) { return null; }
    }

    function wrapFetchForTag() {
        if (window._noahPLMFetchTagWrapped || typeof window.fetch !== "function") return;
        var of = window.fetch;
        window.fetch = function (input, init) {
            try {
                var url = String((input && input.url) || input || "");
                if (/\/api\/chat\/(start|steer)(\?|$)/.test(url) && init && typeof init.body === "string") {
                    var next = _tagPayload(init.body);
                    if (next) init = Object.assign({}, init, { body: next });
                }
            } catch (e) {}
            return of.call(this, input, init);
        };
        window._noahPLMFetchTagWrapped = true;
    }

    // 旧的"写进输入框"实现保留为空操作: 发送路径已改为网络层注入。
    function injectTag() {}

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
    setInterval(function () { try { syncStopBtn(); } catch (e) {} try { fixSendTooltip(); } catch (e) {} try { syncSessionState(); } catch (e) {} }, 300);  // 停止键跟手 + 发送键中文提示
    console.log("[Noah] PLM composer bar v2 loaded");
})();
