(function () {
  const jobId =
    window.NCCM_BACKUP_JOB_ID ||
    new URLSearchParams(location.search).get("run_id");
  if (!jobId) return;

  const panel = document.getElementById("live-panel");
  const logEl = document.getElementById("live-log");
  const badge = document.getElementById("job-badge");
  const table = document.getElementById("results-table");
  const tbody = document.getElementById("results-body");
  const empty = document.getElementById("results-empty");
  const submit = document.getElementById("backup-submit");

  if (panel) panel.hidden = false;
  if (badge) badge.textContent = "job: " + jobId;
  if (submit) submit.disabled = true;

  function appendLog(line) {
    if (!logEl) return;
    logEl.textContent += line + "\n";
    logEl.scrollTop = logEl.scrollHeight;
  }

  function renderResults(msg) {
    if (msg.error && empty) {
      empty.textContent = "備份失敗: " + msg.error;
      empty.hidden = false;
    }
    if (!msg.results || !tbody) {
      if (submit) submit.disabled = false;
      if (badge) badge.textContent = "status: " + (msg.status || "failed");
      return;
    }
    tbody.innerHTML = "";
    msg.results.forEach(function (r) {
      const tr = document.createElement("tr");
      const detail = r.error || r.snapshot_dir || "";
      tr.innerHTML =
        "<td>" +
        escapeHtml(r.site) +
        "</td><td>" +
        escapeHtml(r.ip) +
        "</td><td>" +
        escapeHtml(r.hostname) +
        "</td><td>" +
        escapeHtml(r.status) +
        "</td><td>" +
        escapeHtml(detail) +
        "</td>";
      tbody.appendChild(tr);
    });
    if (table) table.hidden = false;
    if (empty) empty.hidden = true;
    if (submit) submit.disabled = false;
    if (badge)
      badge.textContent =
        "run_id=" + (msg.result_run_id || "") + " · " + msg.status;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  const es = new EventSource("/backup/events/" + encodeURIComponent(jobId));
  es.onmessage = function (ev) {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (e) {
      appendLog(ev.data);
      return;
    }
    if (msg.type === "log") appendLog(msg.line);
    if (msg.type === "error") {
      appendLog("ERROR: " + msg.message);
      es.close();
      if (submit) submit.disabled = false;
    }
    if (msg.type === "complete") {
      if (msg.error) appendLog("FAILED: " + msg.error);
      renderResults(msg);
      es.close();
    }
  };
  es.onerror = function () {
    appendLog("(SSE 連線中斷，可重新整理頁面)");
    es.close();
    if (submit) submit.disabled = false;
  };
})();