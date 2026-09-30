(function () {
  "use strict";

  document.querySelectorAll(".schedule-devices-btn").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      var id = btn.getAttribute("data-schedule-id");
      var name = btn.getAttribute("data-schedule-name");
      var dlg = document.getElementById("schedule-devices-dialog");
      var body = document.getElementById("schedule-devices-body");
      var title = document.getElementById("schedule-devices-title");
      if (!dlg || !body || !title) return;
      title.textContent = "設備清單 — " + name;
      body.innerHTML = '<p class="muted">載入中…</p>';
      dlg.showModal();
      try {
        var response = await fetch("/schedules/" + id + "/devices");
        body.innerHTML = await response.text();
      } catch (err) {
        body.innerHTML = '<p class="error">載入失敗</p>';
      }
    });
  });
})();
