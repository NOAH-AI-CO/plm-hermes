/* Publishes the current user's session metadata to the Project Hub iframe parent. */
(function () {
  "use strict";

  if (window.parent === window) return;

  var parentOrigin = null;
  var refreshTimer = null;

  function sessionApiUrl() {
    var mounted = location.pathname === "/plm-hermes" || location.pathname.indexOf("/plm-hermes/") === 0;
    return (mounted ? "/plm-hermes" : "") + "/api/sessions";
  }

  function normalizeSession(session) {
    if (!session || typeof session.session_id !== "string") return null;
    var updatedAt = session.updated_at || session.time_updated || session.modified_at || session.created_at;
    if (!updatedAt) return null;
    if (typeof updatedAt === "number" || /^\d+(\.\d+)?$/.test(String(updatedAt))) {
      updatedAt = new Date(Number(updatedAt) * 1000).toISOString();
    }
    return {
      id: session.session_id,
      name: String(session.title || session.name || "新建会话").slice(0, 500),
      time_updated: String(updatedAt),
    };
  }

  function publish() {
    if (!parentOrigin) return;
    fetch(sessionApiUrl(), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) {
        var sessions = ((payload && payload.sessions) || []).map(normalizeSession).filter(Boolean).slice(0, 100);
        window.parent.postMessage({ type: "plm.history.sessions", sessions: sessions }, parentOrigin);
      })
      .catch(function () {});
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent || !event.data || event.data.type !== "plm.history.request") return;
    parentOrigin = event.origin;
    publish();
  });

  window.parent.postMessage({ type: "plm.history.ready" }, "*");
  refreshTimer = window.setInterval(publish, 10000);
  window.addEventListener("beforeunload", function () { window.clearInterval(refreshTimer); });
})();