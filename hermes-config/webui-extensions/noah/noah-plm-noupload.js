/*
 * Noah PLM: 禁用图片/文件上传与粘贴 —— 用户只能打字。
 *  1) 隐藏上传按钮(#btnAttach)与上传相关 UI;
 *  2) 拦截粘贴:含文件/图片时阻止(只保留纯文本);
 *  3) 拦截拖拽上传(dragover/drop);
 *  4) 禁用隐藏的 file input(双保险)。
 * 只操作 DOM/事件,不改核心。
 */
(function () {
    "use strict";

    // 关掉上游"长文本粘贴自动转成 pasted-text.md 附件"(用户只想纯文本粘贴)。
    // boot.js 的 _shouldAttachLargePastedText 首行即判断此开关, 设 false 后大文本也按纯文本粘贴。
    try { window._largeTextPasteAsAttachment = false; } catch (e) {}

    var css =
        "#btnAttach,#uploadBar,#uploadBarWrap,#attachTray{display:none!important;}";
    var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

    var FILE_INPUTS = ["fileInput", "importFileInput", "workspaceFileInput"];

    // 粘贴:有文件/图片则拦掉, 只把纯文本插回输入框
    function onPaste(e) {
        var dt = e.clipboardData; if (!dt) return;
        var hasFile = !!(dt.files && dt.files.length);
        if (!hasFile && dt.items) {
            for (var i = 0; i < dt.items.length; i++) {
                if (dt.items[i].kind === "file") { hasFile = true; break; }
            }
        }
        if (!hasFile) return;                       // 纯文本粘贴: 放行
        var text = dt.getData ? dt.getData("text/plain") : "";
        e.preventDefault(); e.stopPropagation();
        var m = document.activeElement;
        if (m && (m.id === "msg" || m.tagName === "TEXTAREA" || m.isContentEditable) && text) {
            if (typeof m.value === "string") {
                var s = m.selectionStart != null ? m.selectionStart : m.value.length;
                var en = m.selectionEnd != null ? m.selectionEnd : m.value.length;
                m.value = m.value.slice(0, s) + text + m.value.slice(en);
                m.selectionStart = m.selectionEnd = s + text.length;
                m.dispatchEvent(new Event("input", { bubbles: true }));
            } else {
                document.execCommand && document.execCommand("insertText", false, text);
            }
        }
    }
    function block(e) { e.preventDefault(); e.stopPropagation(); }

    function harden() {
        var b = document.getElementById("btnAttach"); if (b) b.style.display = "none";
        FILE_INPUTS.forEach(function (id) { var el = document.getElementById(id); if (el && !el.disabled) el.disabled = true; });
    }
    function wire() {
        document.addEventListener("paste", onPaste, true);
        document.addEventListener("dragover", block, true);
        document.addEventListener("drop", block, true);
        harden();
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
    else wire();
    setInterval(harden, 2000);   // 核心重渲染后仍保持隐藏/禁用
    console.log("[Noah] PLM upload/paste-image disabled (type-only)");
})();
