(function () {
  function params(extra) {
    var f = document.getElementById("topo-filters");
    if (!f) return extra || "";
    var q = new URLSearchParams(new FormData(f));
    if (extra) {
      var e = new URLSearchParams(extra);
      e.forEach(function (v, k) {
        q.set(k, v);
      });
    }
    return q.toString();
  }

  document.querySelectorAll("[data-topo-node]").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var nodeId = el.getAttribute("data-topo-node");
      var hidden = document.getElementById("topo-node-id");
      if (hidden) hidden.value = nodeId;
      var qs = params({ node_id: nodeId });
      if (typeof htmx !== "undefined") {
        htmx.ajax("GET", "/neighbors/topology/partial/detail?" + qs, {
          target: "#topo-detail",
          swap: "innerHTML",
        });
      }
      document.querySelectorAll("[data-topo-node] rect").forEach(function (r) {
        r.setAttribute("stroke-width", "2");
      });
      var rect = el.querySelector("rect");
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
  var tx = 0;
  var ty = 0;
  var minScale = 0.08;
  var maxScale = 6;
  var step = 0.12;
  var panning = false;
  var panStartX = 0;
  var panStartY = 0;
  var panBaseTx = 0;
  var panBaseTy = 0;

  function svgSize() {
    var svg = inner && inner.querySelector("svg");
    if (!svg) return { w: 400, h: 300 };
    var vb = svg.viewBox && svg.viewBox.baseVal;
    if (vb && vb.width > 0 && vb.height > 0) {
      return { w: vb.width, h: vb.height };
    }
    return {
      w: parseFloat(svg.getAttribute("width")) || 400,
      h: parseFloat(svg.getAttribute("height")) || 300,
    };
  }

  function clamp(s) {
    return Math.min(maxScale, Math.max(minScale, s));
  }

  function applyTransform() {
    if (!inner) return;
    inner.style.transform =
      "translate(" + tx + "px, " + ty + "px) scale(" + scale + ")";
    if (label) label.textContent = Math.round(scale * 100) + "%";
  }

  function zoomBy(delta, anchorX, anchorY) {
    var old = scale;
    scale = clamp(Math.round((scale + delta) * 100) / 100);
    if (viewport && anchorX != null && anchorY != null && old !== scale) {
      var ratio = scale / old;
      tx = anchorX - (anchorX - tx) * ratio;
      ty = anchorY - (anchorY - ty) * ratio;
    }
    applyTransform();
  }

  function resetZoom() {
    scale = 1;
    tx = 16;
    ty = 16;
    applyTransform();
    if (viewport) {
      viewport.scrollLeft = 0;
      viewport.scrollTop = 0;
    }
  }

  function fitToView() {
    if (!viewport || !inner) return;
    var size = svgSize();
    var pad = 24;
    var vw = Math.max(viewport.clientWidth - pad, 120);
    var vh = Math.max(viewport.clientHeight - pad, 120);
    var fit = Math.min(vw / size.w, vh / size.h);
    scale = clamp(fit);
    tx = (viewport.clientWidth - size.w * scale) / 2;
    ty = (viewport.clientHeight - size.h * scale) / 2;
    applyTransform();
  }

  var btnIn = document.getElementById("topo-zoom-in");
  var btnOut = document.getElementById("topo-zoom-out");
  var btnReset = document.getElementById("topo-zoom-reset");
  var btnFit = document.getElementById("topo-zoom-fit");
  if (btnIn) {
    btnIn.addEventListener("click", function () {
      zoomBy(step, viewport.clientWidth / 2, viewport.clientHeight / 2);
    });
  }
  if (btnOut) {
    btnOut.addEventListener("click", function () {
      zoomBy(-step, viewport.clientWidth / 2, viewport.clientHeight / 2);
    });
  }
  if (btnReset) btnReset.addEventListener("click", resetZoom);
  if (btnFit) btnFit.addEventListener("click", fitToView);

  if (viewport) {
    viewport.addEventListener(
      "wheel",
      function (ev) {
        ev.preventDefault();
        var rect = viewport.getBoundingClientRect();
        var ax = ev.clientX - rect.left;
        var ay = ev.clientY - rect.top;
        var dir = ev.deltaY > 0 ? -step : step;
        zoomBy(dir, ax, ay);
      },
      { passive: false }
    );

    viewport.addEventListener("mousedown", function (ev) {
      if (ev.button !== 0) return;
      if (ev.target.closest && ev.target.closest("[data-topo-node]")) return;
      panning = true;
      viewport.classList.add("is-panning");
      panStartX = ev.clientX;
      panStartY = ev.clientY;
      panBaseTx = tx;
      panBaseTy = ty;
      ev.preventDefault();
    });
  }

  document.addEventListener("mousemove", function (ev) {
    if (!panning) return;
    tx = panBaseTx + (ev.clientX - panStartX);
    ty = panBaseTy + (ev.clientY - panStartY);
    applyTransform();
  });

  document.addEventListener("mouseup", function () {
    if (!panning) return;
    panning = false;
    if (viewport) viewport.classList.remove("is-panning");
  });

  window.addEventListener("resize", function () {
    if (scale < 0.15) fitToView();
  });

  fitToView();
})();
