/* PLM 引擎地址注入(必须在其它 noah-plm-*.js 之前加载)。
 * 本地(127.0.0.1/localhost)无 nginx 反代 → 前端直连引擎 :8002;
 * 独立域名走同源根路径;挂载在 /plm-hermes 下时保留该代理前缀。*/
(function () {
  var h = location.hostname;
  var mount = location.pathname === "/plm-hermes" || location.pathname.indexOf("/plm-hermes/") === 0
    ? "/plm-hermes" : "";
  window.__PLM_API_BASE__ = (h === "127.0.0.1" || h === "localhost")
    ? "http://127.0.0.1:8002" : mount;
})();
