/*
 * Noah PLM 指南候选卡 v1
 * 检测助手消息里的 ```plm-guidelines JSON 块 → 渲染 TOP-5 可点选卡片。
 * 点卡片 = 把"我选定第N个:<name>"填入输入框并发送, 继续澄清流程。
 * 只操作 DOM, 不改 webui 核心。
 */
(function () {
    "use strict";

    var API = (window.__PLM_API_BASE__ || "");   // 同源, nginx 把 /plm* 路由到引擎

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function findComposer() {
        return document.querySelector("#composerInput")
            || document.querySelector("#composer textarea")
            || document.querySelector('textarea[placeholder]')
            || document.querySelector("textarea");
    }
    function findSendBtn() {
        return document.querySelector("#btnSend")
            || document.querySelector('#composer button[type="submit"]')
            || document.querySelector('button[aria-label*="end" i]')
            || document.querySelector(".composer-send, #sendBtn");
    }
    function sendMessage(text) {
        var box = findComposer();
        if (!box) return false;
        box.value = text;
        box.dispatchEvent(new Event("input", { bubbles: true }));
        box.focus();
        var btn = findSendBtn();
        if (btn) { btn.click(); return true; }
        // 回车兜底
        box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
        return true;
    }

    function caseTextFor(wrap) {
        var current = wrap.closest(".msg-body");
        var messages = Array.prototype.slice.call(document.querySelectorAll(".msg-body"));
        var end = current ? messages.indexOf(current) : messages.length;
        if (end < 0) end = messages.length;
        for (var i = end - 1; i >= 0; i--) {
            var text = (messages[i].innerText || "").trim();
            var match = text.match(/^【(?:快速模式|完整报告模式)·指南(?:NCCN|CSCO|ESMO|CACA)】\s*(?!我选定第)(.+)$/m);
            if (match) return match[1].trim();
            if (text && text.indexOf("我选定第") !== 0 &&
                text.indexOf("请从下方卡片中选择") === -1 &&
                text.indexOf("PLM-GUIDELINES") === -1) {
                return text;
            }
        }
        return "";
    }

    function tryParse(raw) {
        if (!raw || raw.indexOf("__plm_guidelines__") === -1) return null;
        var s = raw.trim().replace(/^```[a-zA-Z-]*\s*/, "").replace(/```\s*$/, "").trim();
        try { var o = JSON.parse(s); if (o && o.__plm_guidelines__) return o; } catch (e) {}
        return null;
    }

    function build(data) {
        var cands = data.candidates || [];
        var wrap = document.createElement("div");
        wrap.className = "noah-gl-wrap";
        wrap.innerHTML = '<div class="noah-gl-hint">请从以下候选指南中选择一份(点击卡片):</div>';
        var grid = document.createElement("div");
        grid.className = "noah-gl-grid";
        cands.forEach(function (c, i) {
            var org = (c.organization || "").toUpperCase();
            var card = document.createElement("button");
            card.type = "button";
            card.className = "noah-gl-card";
            card.innerHTML =
                '<span class="noah-gl-idx">' + (i + 1) + "</span>" +
                '<span class="noah-gl-main">' +
                    '<span class="noah-gl-row1">' +
                        (org ? '<span class="noah-gl-org" data-org="' + esc(org) + '">' + esc(org) + "</span>" : "") +
                        (c.year ? '<span class="noah-gl-year">' + esc(c.year) + "</span>" : "") +
                    "</span>" +
                    '<span class="noah-gl-name">' + esc(c.name || "") + "</span>" +
                    (c.summary ? '<span class="noah-gl-sum">' + esc(c.summary) + "</span>" : "") +
                "</span>" +
                '<span class="noah-gl-pick">选定 →</span>';
            card.addEventListener("click", function () {
                if (wrap.dataset.picked) return;        // 已选定, 禁止再点(防重复触发澄清/报告)
                wrap.dataset.picked = "1";
                wrap.classList.add("locked");
                card.classList.add("picked");
                var name = c.name || ("第" + (i + 1) + "个");
                sendMessage(
                    "我选定第 " + (i + 1) + " 个:" + name
                );
            });
            grid.appendChild(card);
        });
        wrap.appendChild(grid);
        return wrap;
    }

    // 会话里若在"本指南块之后、下一个指南块之前"存在"我选定第 N 个"消息, 才锁定本块并标出已选那张。
    // 用范围限定(而非全局最后一次), 避免多轮会话里用上一轮的选择误锁/高亮当前块。
    function lockIfSelected(wrap) {
        try {
            var myMsg = wrap.closest(".msg-body");
            var msgs = Array.prototype.slice.call(document.querySelectorAll(".msg-body"));
            var start = myMsg ? msgs.indexOf(myMsg) : -1;
            if (start < 0) return;
            for (var i = start + 1; i < msgs.length; i++) {
                if (msgs[i].querySelector(".noah-gl-wrap")) return;   // 到了下一轮指南块, 本块之后没选择, 不锁
                var m = (msgs[i].innerText || "").match(/我选定第\s*(\d+)\s*个/);
                if (m) {
                    var idx = parseInt(m[1], 10) - 1;
                    wrap.dataset.picked = "1";
                    wrap.classList.add("locked");
                    var cards = wrap.querySelectorAll(".noah-gl-card");
                    if (cards[idx]) cards[idx].classList.add("picked");
                    return;
                }
            }
        } catch (e) {}
    }

    // 渲染: 优先用内联 candidates(兼容旧格式); 只有 guidelines_id 时去后端拉候选再渲染
    // (compact 模式 —— agent 不再重吐整段候选 JSON, 省 token/延迟、杜绝吐错漏)。
    function renderInto(target, data) {
        if (data.candidates && data.candidates.length) {
            var el = build(data);
            target.parentNode.replaceChild(el, target);
            lockIfSelected(el);
            return;
        }
        if (data.guidelines_id) {
            var ph = document.createElement("div");
            ph.className = "noah-gl-wrap";
            ph.innerHTML = '<div class="noah-gl-hint">正在加载候选指南…</div>';
            target.parentNode.replaceChild(ph, target);
            var _t = (document.cookie.match(/(?:^|;\s*)noahAccessToken=([^;]+)/) || [])[1];
            var _h = _t ? { Authorization: "Token " + decodeURIComponent(_t) } : {};
            fetch(API + "/plm/guidelines_candidates/" + encodeURIComponent(data.guidelines_id), { headers: _h })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (j) {
                    if (!j || !(j.candidates || []).length) {
                        ph.querySelector(".noah-gl-hint").textContent = "候选已过期或加载失败, 请重新描述病情。"; return;
                    }
                    var el = build({ candidates: j.candidates });
                    ph.parentNode.replaceChild(el, ph);
                    lockIfSelected(el);
                })
                .catch(function () { ph.querySelector(".noah-gl-hint").textContent = "候选加载失败, 请重试。"; });
        }
    }

    function scan(root) {
        if (!root || !root.querySelectorAll) return;
        var msgs = root.classList && root.classList.contains("msg-body")
            ? [root] : root.querySelectorAll(".msg-body");
        msgs.forEach(function (msg) {
            if (msg.dataset.noahGlDone) return;
            var blocks = msg.querySelectorAll("pre, code");
            for (var i = 0; i < blocks.length; i++) {
                var data = tryParse(blocks[i].textContent || "");
                if (data) {
                    var target = blocks[i].closest("pre") || blocks[i];
                    msg.dataset.noahGlDone = "1";
                    renderInto(target, data);
                    break;
                }
            }
        });
    }

    function init() {
        scan(document.body);
        new MutationObserver(function (ms) {
            ms.forEach(function (m) {
                m.addedNodes && m.addedNodes.forEach(function (n) {
                    if (n.nodeType === 1) scan(n);
                });
            });
        }).observe(document.body, { childList: true, subtree: true });
        setInterval(function () { scan(document.body); }, 1500);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
    console.log("[Noah] PLM guidelines cards v1 loaded");
})();
