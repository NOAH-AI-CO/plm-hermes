/*
 * Noah PLM 管理面板 v1 —— 上传解锁指南
 * "管理"按钮 → 弹层(两 Tab), 实连 8002 后端。只操作 DOM, 不改核心。
 */
(function () {
    "use strict";
    var API = (window.__PLM_API_BASE__ || "");   // 同源(线上经 nginx /plm→引擎);本地由 apibase.js 注入 127.0.0.1:8002

    function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
    function el(tag, cls, html){var e=document.createElement(tag); if(cls)e.className=cls; if(html!=null)e.innerHTML=html; return e;}
    // 用户 token: 管理端点已要求登录, 每次请求带上 noahAccessToken。
    function noahToken(){var m=document.cookie.match(/(?:^|;\s*)noahAccessToken=([^;]+)/);return m?decodeURIComponent(m[1]):"";}
    function authHeaders(extra){var t=noahToken(),h=Object.assign({},extra||{});if(t)h["Authorization"]="Token "+t;return h;}
    // 带 r.ok 检查: 后端不可达/4xx/5xx 时抛错, 让调用方能显示"失败/重试"而不是静默当空态
    async function jget(p){
        var r=await fetch(API+p,{headers:authHeaders()});
        if(!r.ok) throw new Error("HTTP "+r.status);
        return r.json();
    }
    async function jsend(p,m,b){
        var r=await fetch(API+p,{method:m,headers:authHeaders({"Content-Type":"application/json"}),body:b?JSON.stringify(b):undefined});
        var data=null; try{data=await r.json();}catch(e){}
        if(!r.ok){var msg=(data&&(data.error||(data.detail&&data.detail.message)))||("HTTP "+r.status); var e=new Error(msg); e.status=r.status; e.data=data; throw e;}
        return data;
    }

    // ---------- 指南解锁 (上传解锁: 上传指南文件, 按文件名匹配受管清单落库解锁) ----------
    async function renderGuidelines(pane){
        pane.innerHTML =
            '<p class="noah-admin-tip">上传指南文件即可解锁对应指南(按文件名匹配已收录指南)。解锁后成员即可检索该份指南;下方列表显示各指南的解锁状态。</p>' +
            '<div class="noah-upload" id="gl-drop">' +
              '<input type="file" id="gl-file" accept="application/pdf" multiple style="display:none"/>' +
              '<div class="noah-upload-inner">' +
                '<div class="noah-upload-ico">⬆</div>' +
                '<div class="noah-upload-txt">点击或拖拽指南文件到此处<span class="sub">支持多选;按文件名匹配已收录指南</span></div>' +
              '</div>' +
            '</div>' +
            '<div class="sub" id="gl-upstatus" style="margin:6px 2px 12px"></div>' +
            '<div class="noah-fld">' +
              '<input class="noah-inp" id="gl-filter" placeholder="筛选指南名/机构…" style="min-width:300px"/>' +
              '<span class="sub" id="gl-count"></span>' +
            '</div>' +
            '<div class="noah-list" id="gl-list"><div class="noah-muted">加载中…</div></div>';
        var all=[];
        function draw(){
            var kw=(pane.querySelector("#gl-filter").value||"").toLowerCase();
            var list=pane.querySelector("#gl-list");
            var items=all.filter(function(g){return !kw || ((g.name||"")+(g.organization||"")).toLowerCase().indexOf(kw)>=0;});
            var nUnlocked=all.filter(function(g){return !g.paid;}).length;
            var CAP=150, shown=Math.min(items.length,CAP);
            pane.querySelector("#gl-count").textContent="共 "+all.length+" 份,已解锁 "+nUnlocked+" 份"+(items.length>CAP?("(显示前 "+CAP+",可筛选)"):"");
            if(!items.length){list.innerHTML='<div class="noah-muted">无匹配</div>';return;}
            list.innerHTML="";
            items.slice(0,CAP).forEach(function(g){
                var row=el("div","noah-row",
                    '<span class="noah-badge">'+esc(g.organization||"")+'</span>'+
                    '<span class="grow">'+esc(g.name||"")+'</span>');
                var locked=!!g.paid;
                row.appendChild(el("span","noah-lock "+(locked?"locked":"unlocked"), locked?"未解锁":"已解锁"));
                list.appendChild(row);
            });
        }
        async function load(){
            var list=pane.querySelector("#gl-list");
            if(list) list.innerHTML='<div class="noah-muted">加载中…</div>';
            try{ var d=await jget("/plm/guidelines?scope=yiyong"); all=(d&&d.guidelines)||[]; draw(); }
            catch(e){ if(list) list.innerHTML='<div class="noah-muted">加载失败:'+esc(e.message||"网络错误")+'</div>'; }
        }

        async function doUnlockFiles(files){
            var st=pane.querySelector("#gl-upstatus");
            if(!files||!files.length) return;
            var ok=0, fail=[];
            for(var i=0;i<files.length;i++){
                st.textContent="解锁中… "+(i+1)+"/"+files.length;
                try{
                    var r=await jsend("/plm/unlock","POST",{name:files[i].name,locked:false});
                    if(r&&r.ok) ok++;
                    else fail.push(files[i].name+"(未匹配)");
                }catch(e){
                    // 422=未匹配到该指南; 其它=网络/服务器错误
                    fail.push(files[i].name+"("+(e.status===422?"库中无此指南":(e.message||"出错"))+")");
                }
            }
            st.innerHTML="✓ 已解锁 "+ok+" 份"+(fail.length?(";失败 "+fail.length+" 份: "+esc(fail.join("、"))):"");
            load();
        }

        var drop=pane.querySelector("#gl-drop"), fileInp=pane.querySelector("#gl-file");
        drop.onclick=function(){ fileInp.click(); };
        fileInp.onchange=function(){ doUnlockFiles(fileInp.files); fileInp.value=""; };
        drop.ondragover=function(e){ e.preventDefault(); drop.classList.add("drag"); };
        drop.ondragleave=function(){ drop.classList.remove("drag"); };
        drop.ondrop=function(e){ e.preventDefault(); drop.classList.remove("drag"); doUnlockFiles(e.dataTransfer.files); };
        pane.querySelector("#gl-filter").oninput=draw;
        load();
    }

    // ---------- 弹层 ----------
    function openAdmin(tab){
        var ov=document.getElementById("noah-admin-overlay");
        ov.classList.add("open");
        switchTab(tab||"guidelines");
    }
    function switchTab(key){
        var ov=document.getElementById("noah-admin-overlay");
        var paneG=ov.querySelector("#pane-guidelines");
        paneG.classList.add("active");
        renderGuidelines(paneG);
    }

    var _meChecked=false, _isAdmin=false;
    // 只有 B 端管理员(管理着组织)才显示"管理"入口; 查一次 /plm/me 缓存结果(后端亦已强制鉴权)。
    function ensureAdmin(cb){
        if(_meChecked){ cb(_isAdmin); return; }
        if(!noahToken()){ cb(false); return; }
        jget("/plm/me").then(function(d){ _isAdmin=!!(d&&d.is_admin); _meChecked=true; cb(_isAdmin); })
                       .catch(function(){ cb(false); });   // 拿不到就当非管理员, 不显示
    }

    function mount(){
        if(!noahToken())return;   // 未登录不渲染
        if(document.getElementById("noah-admin-btn"))return;
        ensureAdmin(function(isAdmin){ if(isAdmin) mountBtn(); });
    }
    function mountBtn(){
        if(document.getElementById("noah-admin-btn"))return;
        var btn=el("button",null,"⚙ 管理"); btn.id="noah-admin-btn";
        btn.onclick=function(){openAdmin("guidelines");};
        document.body.appendChild(btn);

        var ov=el("div"); ov.id="noah-admin-overlay";
        ov.innerHTML=
            '<div class="noah-admin-modal">'+
              '<div class="noah-admin-top"><h3>PLM 管理台</h3><button class="noah-admin-close" id="na-close">×</button></div>'+
              '<div class="noah-admin-tabs">'+
                '<button class="noah-admin-tab active" data-k="guidelines">指南解锁</button>'+
              '</div>'+
              '<div class="noah-admin-body">'+
                '<div class="noah-admin-pane active" id="pane-guidelines"></div>'+
              '</div>'+
            '</div>';
        document.body.appendChild(ov);
        ov.querySelector("#na-close").onclick=function(){ov.classList.remove("open");};
        ov.addEventListener("click",function(e){if(e.target===ov)ov.classList.remove("open");});
        ov.querySelectorAll(".noah-admin-tab").forEach(function(b){b.onclick=function(){switchTab(b.dataset.k);};});
        // #plm-admin / #plm-members 均打开管理台(指南解锁)
        if(location.hash==="#plm-admin"||location.hash==="#plm-members") openAdmin("guidelines");
    }
    if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);
    else mount();
    setInterval(mount,2000);
    console.log("[Noah] PLM admin panel v1 loaded");
})();
