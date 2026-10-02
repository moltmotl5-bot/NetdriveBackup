(function () {
  function params(extra) {
    const f = document.getElementById("topo-filters");
    if (!f) return extra || "";
    const q = new URLSearchParams(new FormData(f));
    if (extra) {
      const e = new URLSearchParams(extra);
      e.forEach(function (v, k) {
        q.set(k, v);
      });
    }
    return q.toString();
  }

  document.querySelectorAll("[data-topo-node]").forEach(function (el) {
    el.addEventListener("click", function () {
      const nodeId = el.getAttribute("data-topo-node");
      const hidden = document.getElementById("topo-node-id");
      if (hidden) hidden.value = nodeId;
      const qs = params({ node_id: nodeId });
      if (typeof htmx !== "undefined") {
        htmx.ajax("GET", "/neighbors/topology/partial/detail?" + qs, {
          target: "#topo-detail",
          swap: "innerHTML",
        });
      }
      document.querySelectorAll("[data-topo-node] rect").forEach(function (r) {
        r.setAttribute("stroke-width", "2");
      });
      const rect = el.querySelector("rect");
      if (rect) rect.setAttribute("stroke-width", "3");
    });
  });

  var wrap = document.getElementById("topo-svg-wrap");
  if (!wrap || wrap.getAttribute("data-zoom-enabled") !== "1") {
    return;
  }

  var inner = document.getElementById("topo-zoom-inner");
  var viewport = document.getElementById("topo-zoom-viewport");
  var label = document.getElementById("topo-zoom-label");
  var scale = 1;
  var minScale = 0.25;
  var maxScale = 3;
  var step = 0.1;

  function clamp(s) {
    return Math.min(maxScale, Math.max(minScale, s));
  }

  function applyScale() {
    if (!inner) return;
    inner.style.transform = "scale(" + scale + ")";
    if (label) label.textContent = Math.round(scale * 100) + "%";
  }

  function zoomBy(delta) {
    scale = clamp(Math.round((scale + delta) * 100) / 100);
    applyScale();
  }

  function resetZoom() {
    scale = 1;
    applyScale();
    if (viewport) {
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
    }
  }

  var btnIn = document.getElementById("topo-zoom-in");
  var btnOut = document.getElementById("topo-zoom-out");
  var btnReset = document.getElementById("topo-zoom-reset");
  if (btnIn) btnIn.addEventListener("click", function () { zoomBy(step); });
  if (btnOut) btnOut.addEventListener("click", function () { zoomBy(-step); });
  if (btnReset) btnReset.addEventListener("click", resetZoom);

  if (viewport) {
    viewport.addEventListener(
      "wheel",
      function (ev) {
        ev.preventDefault();
        var dir = ev.deltaY > 0 ? -step : step;
        zoomBy(dir);
      },
      { passive: false }
    );
  }

  applyScale();
})();
