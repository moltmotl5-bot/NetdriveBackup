(function () {
  "use strict";

  document.addEventListener("click", function (event) {
    var row = event.target.closest("tr[data-pick-field]");
    if (!row) return;
    var fieldId = row.getAttribute("data-pick-field");
    var value = row.getAttribute("data-pick-value");
    if (!fieldId || value == null) return;
    var field = document.getElementById(fieldId);
    if (field) field.value = value;
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  document.addEventListener("change", function (event) {
    var target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    if (target.getAttribute("data-auto-submit") && target.form) {
      target.form.submit();
    }
  });
})();
