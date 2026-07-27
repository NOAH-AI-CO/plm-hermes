/*
 * Noah PLM 报告分栏面板 v2
 * 检测助手消息里的 ```plm-report JSON 块, 渲染成 Tab:
 *   诊断 / 检查 / 治疗 / 综合报告 / 次要指南补充
 *
 * v2 关键改动:
 *  1) 前端直连驱动: 块里带 run 参数时, 前端自己 POST /plm_evidence_based(compact)
 *     拿 report_id 后立刻连 SSE 流 —— 报告一开始生成前端就在流式渲染, 不依赖 agent。
 *  2) 全局注册表按 key 复用面板: 助手消息 DOM 反复重渲染时, 把"正在流式的同一个面板"
 *     移动到新位置, 而不是重建/退回轮询 —— 修复流式内容一直到最后才一次性出现的问题。
 *  3) 每个分区首行提升为标题; 正文里的 [N] 依据 citations 渲染成可点击角标 + 参考文献列表。
 */
(function () {
    "use strict";

    var API = (window.__PLM_API_BASE__ || "");   // 同源(线上经 nginx /plm→引擎);本地由 apibase.js 注入 127.0.0.1:8002
    // 用户 token: 从 noahAccessToken cookie 读, 带给 plm-engine 做行级归属(检索/生成/下载/流式)。
    function noahToken() { var m = document.cookie.match(/(?:^|;\s*)noahAccessToken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
    function authHeaders(extra) { var t = noahToken(), h = Object.assign({}, extra || {}); if (t) h["Authorization"] = "Token " + t; return h; }
    var _reg = {};   // key -> { wrap }  面板节点复用, 跨 DOM 重渲染存活
    var LOADING = '<div class="noah-plm-loading"><span class="noah-plm-spin"></span>报告生成中,分区将陆续流式呈现…</div>';

    var TABS = [
        { key: "diagnosis", label: "诊断" },
        { key: "examination", label: "检查" },
        { key: "treatment", label: "治疗" },
        { key: "drug", label: "药物说明书" },
        { key: "secondary", label: "次要指南补充" },
        { key: "comprehensive", label: "综合报告" },
    ];
    // 引擎分区 → 前端 Tab 映射(药物独立 tab; summary 归综合报告, 结束时整体 reconcile)
    var SEC2TAB = {
        diagnosis: "diagnosis", examination: "examination", treatment: "treatment",
        drug: "drug", secondary_comparison: "secondary", summary: "comprehensive",
    };

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function hash(s) {
        var h = 5381, i = s.length;
        while (i) h = (h * 33) ^ s.charCodeAt(--i);
        return (h >>> 0).toString(36);
    }

    // 用 webui 全功能 markdown 渲染器(渲染 ## 标题/表格/列表等)
    function renderMd(text) {
        var t = text == null ? "" : String(text);
        try { if (typeof window.renderMd === "function") return window.renderMd(t); } catch (e) {}
        try { if (typeof window._renderUserMarkdown === "function") return window._renderUserMarkdown(t); } catch (e) {}
        return '<div style="white-space:pre-wrap">' + esc(t) + "</div>";
    }

    // 分区正文首行(如"诊断建议及依据")本是纯文本, 提升为二级标题以突出层级。
    // 已是 markdown 标题/加粗/列表/表格或过长(像正文句子)的首行不动。
    function promoteTitle(text) {
        var t = String(text == null ? "" : text);
        var nl = t.indexOf("\n");
        var first = (nl < 0 ? t : t.slice(0, nl)).trim();
        if (!first) return t;
        if (/^#{1,6}\s/.test(first) || /^[*\-|>0-9]/.test(first) ||
            first.length > 24 || /[。,；;]/.test(first)) return t;
        return "## " + first + (nl < 0 ? "" : t.slice(nl));
    }

    // citations 分区按名字关键词取 items(而非 tab 下标, 因为药物 tab 插入后下标会错位)
    function _citeSection(citations, kw) {
        if (!citations || !citations.length) return null;
        for (var i = 0; i < citations.length; i++) {
            if ((citations[i].section || "").indexOf(kw) >= 0 && citations[i].items && citations[i].items.length)
                return citations[i].items;
        }
        return null;
    }
    function citeItemsForTab(report, tabKey) {
        var c = report && report.citations;
        if (tabKey === "diagnosis") return _citeSection(c, "诊断");
        if (tabKey === "examination") return _citeSection(c, "检查");
        if (tabKey === "treatment") return _citeSection(c, "治疗");
        if (tabKey === "secondary") return _citeSection(c, "次要") || _citeSection(c, "对比");
        return null;   // drug / comprehensive 另行处理
    }

    // 点击 [N] 弹出小窗显示该条参考文献
    var _citePop = null;
    function hideCitePopover() { if (_citePop) { try { _citePop.remove(); } catch (e) {} _citePop = null; } }
    function showCitePopover(anchor, text) {
        hideCitePopover();
        var pop = document.createElement("div");
        pop.className = "plm-cite-pop";
        pop.textContent = text;
        document.body.appendChild(pop);
        var r = anchor.getBoundingClientRect();
        var w = pop.offsetWidth || 320;
        var left = Math.max(8, Math.min(r.left, window.innerWidth - w - 12));
        var top = r.bottom + 6;
        if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 6);
        pop.style.left = left + "px";
        pop.style.top = top + "px";
        _citePop = pop;
        setTimeout(function () {
            document.addEventListener("click", hideCitePopover, { once: true });
            document.addEventListener("scroll", hideCitePopover, { once: true, capture: true });
        }, 0);
    }
    function _makeCiteSup(id, label) {
        var sup = document.createElement("sup");
        sup.className = "plm-cite";
        sup.textContent = "[" + id + "]";
        sup.addEventListener("click", function (ev) {
            ev.preventDefault(); ev.stopPropagation();
            showCitePopover(this, "[" + id + "] " + label);
        });
        return sup;
    }
    // 把一个文本节点里的 [N] 和 [N, M](逗号合并)都渲染成独立可点角标 [N][M]
    function _linkifyNode(node, map) {
        var txt = node.nodeValue, re = /\[(\d+(?:\s*,\s*\d+)*)\]/g, last = 0, m,
            frag = document.createDocumentFragment(), any = false;
        while ((m = re.exec(txt))) {
            var ids = m[1].split(",").map(function (x) { return parseInt(x.trim(), 10); });
            var known = ids.filter(function (id) { return id in map; });
            if (m.index > last) frag.appendChild(document.createTextNode(txt.slice(last, m.index)));
            if (known.length) {
                // 组内逐个处理: 已知→可点角标, 未知→保留为 [N] 文本(不丢弃)
                ids.forEach(function (id) {
                    if (id in map) frag.appendChild(_makeCiteSup(id, map[id]));
                    else frag.appendChild(document.createTextNode("[" + id + "]"));
                });
                any = true;
            } else {
                frag.appendChild(document.createTextNode(m[0]));
            }
            last = m.index + m[0].length;
        }
        if (!any) return;
        if (last < txt.length) frag.appendChild(document.createTextNode(txt.slice(last)));
        node.parentNode.replaceChild(frag, node);
    }
    function _skipNode(n) {
        var p = n.parentNode;
        return p && (p.nodeName === "SUP" || p.nodeName === "CODE" || p.nodeName === "PRE" || p.nodeName === "A");
    }

    // 单分区: 全篇用同一组 items
    function linkifyCitations(panelEl, items) {
        var map = {};
        items.forEach(function (it) { map[it.id] = it.label; });
        var walker = document.createTreeWalker(panelEl, NodeFilter.SHOW_TEXT, null, false), nodes = [], n;
        while ((n = walker.nextNode())) { if (!_skipNode(n) && /\[\d/.test(n.nodeValue)) nodes.push(n); }
        nodes.forEach(function (node) { _linkifyNode(node, map); });
    }

    // 综合报告: [N] 按所在子分区标题(## 1.诊断建议 / ## 2.进一步检查 / ## 3.治疗方案 / ## 二、临床关键风险)
    // 各自重新编号, 故走标题感知——遇到标题切换当前 citations 组, 摘要/沟通段无引用则清空。
    function linkifyComprehensive(panelEl, citations) {
        if (!citations || !citations.length) return;
        function mapFor(h) {
            var items = null;
            if (/诊断/.test(h)) items = _citeSection(citations, "诊断");
            else if (/检查/.test(h)) items = _citeSection(citations, "检查");
            else if (/治疗/.test(h)) items = _citeSection(citations, "治疗");
            else if (/风险|执行要点|关键/.test(h)) items = _citeSection(citations, "风险") || _citeSection(citations, "关键");
            else if (/次要|对比/.test(h)) items = _citeSection(citations, "次要") || _citeSection(citations, "对比");
            else return null;   // 摘要 / 医患沟通 / 汇总 / 权威共识 等无引用
            if (!items) return null;
            var m = {}; items.forEach(function (it) { m[it.id] = it.label; });
            return m;
        }
        var walker = document.createTreeWalker(panelEl, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, null, false);
        var cur = null, pending = [], node;
        while ((node = walker.nextNode())) {
            if (node.nodeType === 1 && /^H[1-6]$/.test(node.nodeName)) {
                // 只在识别到分区主标题时切换当前 citations 组; 无关键词的下级子标题(如"指南附加安全与执行说明")
                // 保持沿用当前组, 不清空, 否则会打断该分区后续 [N] 的链接。
                var mm = mapFor(node.textContent || "");
                if (mm) cur = mm;
            } else if (node.nodeType === 3 && cur && !_skipNode(node) && /\[\d/.test(node.nodeValue)) {
                pending.push({ node: node, map: cur });
            }
        }
        pending.forEach(function (e) { _linkifyNode(e.node, e.map); });
    }

    function applyContent(panelEl, content, report, tabKey) {
        if (content && String(content).trim()) {
            panelEl.innerHTML = renderMd(promoteTitle(content));
            // 正文本身已带"参考文献:"列表, 这里只把行内 [N] 变成可点角标(点击弹小窗), 不另加列表(避免重复)。
            if (tabKey === "comprehensive") {
                linkifyComprehensive(panelEl, report && report.citations);
            } else if (tabKey !== "drug") {
                var items = citeItemsForTab(report, tabKey);
                if (items && items.length) linkifyCitations(panelEl, items);
            }
        } else {
            panelEl.innerHTML = '<div class="noah-plm-empty">本节暂无内容</div>';
        }
    }

    // 在综合报告 tab 底部追加"下载整份报告"按钮(Word / PDF, 同 demo: 文件名 病例报告_<全名>)
    function appendDownloadBar(panelEl, rid, wrap) {
        var bar = document.createElement("div");
        bar.className = "noah-plm-dlbar";
        bar.innerHTML =
            '<span class="noah-plm-dl-label">下载整份报告:</span>' +
            '<button type="button" class="noah-plm-dlbtn" data-act="word">⬇ Word</button>' +
            '<button type="button" class="noah-plm-dlbtn" data-act="pdf">⬇ PDF</button>';
        function dl(fmt, btn) {
            var old = btn.textContent; btn.disabled = true; btn.textContent = "生成中…";
            var url = API + "/plm/report/" + encodeURIComponent(rid) + "/download?fmt=" + fmt;
            fetch(url, { headers: authHeaders() }).then(function (r) {
                if (!r.ok) throw new Error("HTTP " + r.status);
                var cd = r.headers.get("Content-Disposition") || "";
                var m = cd.match(/filename\*=UTF-8''([^;]+)/);
                var name = m ? decodeURIComponent(m[1]) : ("病例报告." + (fmt === "pdf" ? "pdf" : "docx"));
                return r.blob().then(function (b) {
                    var a = document.createElement("a");
                    a.href = URL.createObjectURL(b); a.download = name;
                    document.body.appendChild(a); a.click();
                    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
                });
            }).catch(function (e) { alert("下载失败:" + (e.message || e)); })
              .then(function () { btn.disabled = false; btn.textContent = old; });
        }
        bar.querySelector('[data-act="word"]').addEventListener("click", function () { dl("word", this); });
        bar.querySelector('[data-act="pdf"]').addEventListener("click", function () { dl("pdf", this); });
        panelEl.appendChild(bar);
    }

    // 把 5 个 Tab 渲染进给定 wrap(复用节点, 不新建), 返回 { panelByKey, activate }
    // streaming=true 时空分区显示"生成中…"而非"暂无内容"(报告检索阶段还没产出正文)
    function renderTabsInto(wrap, report, streaming) {
        var gl = report.guideline || report.primary_organization || "";
        var rid = wrap.dataset ? (wrap.dataset.rid || "") : "";
        wrap.innerHTML =
            '<div class="noah-plm-head">' +
            '<span class="noah-plm-title">循证诊疗报告</span>' +
            (gl ? '<span class="noah-plm-badge">' + esc(gl) + "</span>" : "") +
            "</div>";

        var tabsBar = document.createElement("div");
        tabsBar.className = "noah-plm-tabs";
        var body = document.createElement("div");
        body.className = "noah-plm-body";

        var panelByKey = {};
        var btnByKey = {};
        var firstWithContent = -1;
        TABS.forEach(function (tab, i) {
            var content = report[tab.key];
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "noah-plm-tab";
            btn.textContent = tab.label;

            var panel = document.createElement("div");
            panel.className = "noah-plm-panel";
            panel.setAttribute("data-label", tab.label);   // 打印时作分区标题
            panelByKey[tab.key] = panel;
            btnByKey[tab.key] = btn;
            if (content && String(content).trim()) {
                applyContent(panel, content, report, tab.key);
                if (firstWithContent < 0) firstWithContent = i;
                // 下载按钮只放"综合报告"tab 底部(整份报告下载), 且报告就绪时才出现
                if (tab.key === "comprehensive" && rid && !streaming) appendDownloadBar(panel, rid, wrap);
            } else {
                panel.innerHTML = streaming
                    ? '<div class="noah-plm-loading"><span class="noah-plm-spin"></span>本节生成中…</div>'
                    : '<div class="noah-plm-empty">本节暂无内容</div>';
            }

            btn.addEventListener("click", function () {
                tabsBar.querySelectorAll(".noah-plm-tab").forEach(function (b) { b.classList.remove("active"); });
                body.querySelectorAll(".noah-plm-panel").forEach(function (p) { p.classList.remove("active"); });
                btn.classList.add("active");
                panel.classList.add("active");
            });

            tabsBar.appendChild(btn);
            body.appendChild(panel);
        });

        wrap.appendChild(tabsBar);
        wrap.appendChild(body);

        function activate(idx) {
            var btns = tabsBar.querySelectorAll(".noah-plm-tab");
            var panels = body.querySelectorAll(".noah-plm-panel");
            btns.forEach(function (b) { b.classList.remove("active"); });
            panels.forEach(function (p) { p.classList.remove("active"); });
            if (btns[idx]) btns[idx].classList.add("active");
            if (panels[idx]) panels[idx].classList.add("active");
        }
        activate(firstWithContent < 0 ? 0 : firstWithContent);
        return { panelByKey: panelByKey, btnByKey: btnByKey, activate: activate };
    }

    // 分区流式: 把事件边收边渲染进 wrap 的各 Tab; 结束用权威全文校正(带 citations)
    function streamReport(rid, wrap) {
        if (wrap.dataset) wrap.dataset.rid = rid;     // 供报告头的下载按钮构造 URL
        var ctx = renderTabsInto(wrap, {}, true);     // 先建 Tab, 空的显示"生成中…"
        var panelByKey = ctx.panelByKey;
        var buffers = {}, activated = false;

        function paint(tabKey) {
            var el = panelByKey[tabKey];
            if (el) el.innerHTML = renderMd(promoteTitle(buffers[tabKey] || ""));
            if (ctx.btnByKey[tabKey]) ctx.btnByKey[tabKey].classList.add("noah-plm-tab-streaming");  // 该分区正在写入→亮脉冲点
            if (!activated) {
                var idx = -1;
                TABS.forEach(function (t, i) { if (t.key === tabKey) idx = i; });
                if (idx >= 0) { ctx.activate(idx); activated = true; }
            }
        }

        var es;
        try { es = new EventSource(API + "/plm/report_stream/" + encodeURIComponent(rid) + "?token=" + encodeURIComponent(noahToken())); }
        catch (e) { reconcile(rid, wrap); return; }
        // 报告流独立于主聊天流。每条流单独登记 + 各自停止句柄, 支持多报告并行、各停各的。
        var streams = (window._noahReportStreams = window._noahReportStreams || []);
        var _stopped = false;
        var ctrl = { es: es, wrap: wrap, rid: rid, stop: function () {
            if (_stopped) return; _stopped = true; es._noahStopped = true;
            try { es.close(); } catch (_) {}
            _finish();
            wrap.querySelectorAll("[class*=plm-panel]").forEach(function (p) {
                if (/生成中/.test(p.textContent || "")) p.innerHTML = '<div class="noah-plm-empty">已停止生成</div>';
            });
            wrap.querySelectorAll(".noah-plm-tab-streaming").forEach(function (b) { b.classList.remove("noah-plm-tab-streaming"); });
        } };
        streams.push(ctrl);
        window._noahReportStreaming = true;
        function _finish() {
            var i = streams.indexOf(ctrl); if (i >= 0) streams.splice(i, 1);
            window._noahReportStreaming = streams.length > 0;
        }

        es.onmessage = function (e) {
            if (!document.body.contains(wrap)) { try { es.close(); } catch (_) {} return; }  // 面板已移除→停流, 防泄漏
            var d; try { d = JSON.parse(e.data); } catch (_) { return; }
            var ev = d.event, p = d.payload || {};
            if (ev === "section_chunk") {
                var tk = SEC2TAB[p.section]; if (!tk) return;
                // 综合报告(summary)、药物说明书(多张药卡+互作分析并发)都是"多来源聚合"分区,
                // 逐块流会 token 级交错乱码。故流式期不逐块画, 结束时 reconcile 用后端权威全文整体呈现。
                // 诊断/检查/治疗/次要是单来源, 正常真流式。
                if (tk === "comprehensive" || tk === "drug") return;
                buffers[tk] = (buffers[tk] || "") + (p.text || "");
                paint(tk);
            } else if (ev === "section_done") {
                var tk2 = SEC2TAB[p.section];
                if (tk2 && tk2 !== "comprehensive" && tk2 !== "drug") paint(tk2);
                if (tk2 && ctx.btnByKey[tk2]) ctx.btnByKey[tk2].classList.remove("noah-plm-tab-streaming");  // 该分区写完→熄灭
            } else if (ev === "clarification_required") {
                wrap.innerHTML = '<div class="noah-plm-empty">需要先确认澄清信息后再生成报告</div>';
            } else if (ev === "error") {
                if (!activated) wrap.innerHTML = '<div class="noah-plm-empty">报告生成失败' + (p.error ? ':' + esc(p.error) : '') + '</div>';
            } else if (ev === "_done" || ev === "result") {
                try { es.close(); } catch (_) {}
                _finish();
                reconcile(rid, wrap);   // 用后端权威全文校正(补 citations / 防丢块)
            }
        };
        es.onerror = function () { try { es.close(); } catch (e) {} _finish(); if (es._noahStopped) return; reconcile(rid, wrap); };
    }

    // 全局停止(发送区"停止"键):停掉所有并行报告流。
    window.noahStopReport = function () {
        (window._noahReportStreams || []).slice().forEach(function (c) { try { c.stop(); } catch (e) {} });
        window._noahReportStreaming = false;
    };

    // 用 /plm/report/<id> 权威全文重填同一个 wrap(保持节点标识, 供重渲染复用)
    function reconcile(rid, wrap, tries) {
        tries = tries || 0;
        if (tries > 200) return;
        fetch(API + "/plm/report/" + encodeURIComponent(rid), { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!wrap) return;
                if (wrap.dataset) wrap.dataset.rid = rid;
                if (d && d.status === "ready") {
                    renderTabsInto(wrap, d);
                } else if (d && d.status === "generating") {
                    setTimeout(function () { reconcile(rid, wrap, tries + 1); }, 4000);
                } else if (d && d.status === "clarification_required") {
                    wrap.innerHTML = '<div class="noah-plm-empty">需要先确认澄清信息后再生成报告</div>';
                } else if (d && (d.status === "missing" || d.status === "error")) {
                    // 报告已过期/丢失(重启且未持久化, 或生成失败): 不再无限转圈, 给明确提示
                    wrap.innerHTML = '<div class="noah-plm-empty">该报告已过期或不可用,无法重新查看。如需请重新发起生成。</div>';
                } else {
                    setTimeout(function () { reconcile(rid, wrap, tries + 1); }, 4000);
                }
            })
            .catch(function () { setTimeout(function () { reconcile(rid, wrap, tries + 1); }, 4000); });
    }

    // 前端直连驱动: 用块里的 run 参数 POST 报告(compact 秒回 report_id), 立刻连流
    function postRun(run, wrap) {
        var payload = Object.assign(
            { product_scope: "yiyong", mode: "complex", compact: true, stream: false }, run);
        fetch(API + "/plm_evidence_based", {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(payload),
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.report_id) { streamReport(d.report_id, wrap); }
                else if (d && d.status === "clarification_required") {
                    wrap.innerHTML = '<div class="noah-plm-empty">需要先确认澄清信息后再生成报告</div>';
                } else {
                    wrap.innerHTML = '<div class="noah-plm-empty">报告启动失败' + (d && d.error ? ':' + esc(d.error) : '') + '</div>';
                }
            })
            .catch(function (e) { wrap.innerHTML = '<div class="noah-plm-empty">报告请求失败:' + esc(e && e.message) + '</div>'; });
    }

    function tryParseReport(raw) {
        if (!raw) return null;
        var s = raw.trim().replace(/^```[a-zA-Z-]*\s*/, "").replace(/```\s*$/, "").trim();
        if (s.indexOf("__plm_report__") === -1) return null;
        try { var obj = JSON.parse(s); if (obj && obj.__plm_report__) return obj; } catch (e) {}
        return null;
    }

    function keyOf(report) {
        // run 块用稳定标识(clarify_session_id)去重: 助手消息反复重渲染时 JSON 文本会微调,
        // 用整块 hash 会误判成新报告 → 重复 POST/重建面板。改用 session id 保证只 POST 一次。
        if (report.run) {
            var r = report.run;
            var sig = r.clarify_session_id || (r.selected_doc_id + "|" + (r.patient_input || "").slice(0, 40));
            return "run:" + sig;
        }
        if (report.report_id) return "rid:" + report.report_id;
        return "full:" + hash(JSON.stringify([report.diagnosis, report.treatment, report.comprehensive]).slice(0, 4000));
    }

    // 把某个 plm-report 块挂载到面板; 重复检测/DOM重渲染时复用同一面板节点
    function mount(target, report) {
        var key = keyOf(report);
        var entry = _reg[key];
        if (entry && entry.wrap) {
            // DOM 重渲染: 把已有的(可能正在流式的)面板移到当前位置, 不重建/不重连
            if (entry.wrap !== target && target.parentNode) {
                target.parentNode.replaceChild(entry.wrap, target);
            }
            return;
        }
        var wrap = document.createElement("div");
        wrap.className = "noah-plm-report";
        wrap.innerHTML = LOADING;
        if (target.parentNode) target.parentNode.replaceChild(wrap, target);
        _reg[key] = { wrap: wrap };

        if (report.run) postRun(report.run, wrap);
        else if (report.report_id && !report.diagnosis && !report.comprehensive) streamReport(report.report_id, wrap);
        else renderTabsInto(wrap, report);   // 内联全量报告(兼容)
    }

    function scanNode(root) {
        if (!root || !root.querySelectorAll) return;
        var msgs = root.classList && root.classList.contains("msg-body")
            ? [root] : root.querySelectorAll(".msg-body");
        msgs.forEach(function (msg) {
            var pres = msg.querySelectorAll("pre, code");
            for (var i = 0; i < pres.length; i++) {
                var report = tryParseReport(pres[i].textContent || "");
                if (report) {
                    mount(pres[i].closest("pre") || pres[i], report);
                    break;
                }
            }
        });
    }

    function init() {
        scanNode(document.body);
        var obs = new MutationObserver(function (muts) {
            muts.forEach(function (m) {
                m.addedNodes && m.addedNodes.forEach(function (n) {
                    if (n.nodeType === 1) scanNode(n);
                });
            });
        });
        obs.observe(document.body, { childList: true, subtree: true });
        setInterval(function () { scanNode(document.body); }, 1500);
        window.__noahScanPlmPanels = function () { scanNode(document.body); };
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
    window.__noahPlmVer = "v2";
    console.log("[Noah] PLM panels v2 loaded");
})();
