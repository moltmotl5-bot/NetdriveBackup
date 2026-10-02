(function () {
  function params(extra) {
    const f = document.getElementById("topo-filters");
    if (!f) return extra || "";
    const q = new URLSearchParams(new FormData(f));
    if (extra) {
      const e = new URLSearchParams(extra);
      e.forEach((v, k) => q.set(k, v));
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
})();
