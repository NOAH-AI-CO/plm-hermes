// ===== Noah 引用卡片诊断脚本 =====
console.log("=".repeat(60));
console.log("[Noah 诊断]");

// 1. 有几个 noah-cite 元素？
const cites = document.querySelectorAll(".noah-cite");
console.log("1. 页面上 .noah-cite 元素数:", cites.length);
if (cites.length === 0) {
    console.log("   ⚠️ 一个都没有 → JS 没扫到引用");
    console.log("   → 检查：window.__noahScanCitations 是否存在:", typeof window.__noahScanCitations);
    console.log("   → 手动调一次:", "window.__noahScanCitations(document.getElementById('previewMd'))");
} else {
    console.log("   ✅ 已包元素，第一个:", cites[0]);
    console.log("   → data-cite-key:", cites[0].getAttribute("data-cite-key"));
}

// 2. 参考文献解析
const previewMd = document.getElementById("previewMd");
const msgBody = document.querySelector(".msg-body");
const container = previewMd || msgBody;
console.log("2. 容器:", container ? container.id || container.className : "❌ 找不到 #previewMd 或 .msg-body");

if (container) {
    const h2s = container.querySelectorAll("h2");
    console.log("   h2 数量:", h2s.length);
    let refH2 = null;
    for (const h of h2s) {
        const t = h.textContent.trim();
        if (t.includes("参考文献") || t.includes("References")) {
            refH2 = h;
            break;
        }
    }
    console.log("   参考文献 h2:", refH2 ? "✅ 找到 - " + refH2.textContent : "❌ 找不到");
    
    if (refH2) {
        // 数一下参考文献段的 h3 数量
        let node = refH2.nextElementSibling;
        let h3Count = 0;
        let firstH3 = null;
        let firstH3Sibling = null;
        while (node && node.tagName !== "H2") {
            if (node.tagName === "H3") {
                h3Count++;
                if (!firstH3) {
                    firstH3 = node;
                    firstH3Sibling = node.nextElementSibling;
                }
            }
            node = node.nextElementSibling;
        }
        console.log("   参考文献段 h3 数量:", h3Count);
        if (firstH3) {
            console.log("   第一个 h3 文本:", firstH3.textContent);
            console.log("   紧跟 h3 的下一个元素:", firstH3Sibling ? firstH3Sibling.tagName + " - " + firstH3Sibling.textContent.slice(0, 60) : "无");
        }
    }
}

// 3. 手动 hover 触发
if (cites.length > 0) {
    console.log("3. 手动触发 hover (150ms 后应该弹卡片)");
    cites[0].dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    setTimeout(() => {
        const cards = document.querySelectorAll(".noah-cite-card");
        console.log("   500ms 后卡片数:", cards.length);
        if (cards.length > 0) {
            console.log("   ✅ 卡片弹出！内容:");
            console.log("   - key:", cards[0].querySelector(".noah-cite-card-key")?.textContent);
            console.log("   - apa:", cards[0].querySelector(".noah-cite-card-apa")?.textContent?.slice(0, 100));
        } else {
            console.log("   ❌ 卡片没弹出");
        }
    }, 500);
}

// 4. Scripts 都加载了吗？
console.log("4. Noah 脚本状态:");
console.log("   __noahScanCitations:", typeof window.__noahScanCitations);
console.log("   __noahResetCitations:", typeof window.__noahResetCitations);
console.log("   __noahPreviewHooked:", window.__noahPreviewHooked);

console.log("=".repeat(60));
console.log("请把以上完整输出截图发我");
