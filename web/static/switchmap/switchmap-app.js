/* global SwitchDraw */
(function () {
  'use strict';

  var root = document.getElementById('switchmap-root');
  if (!root) {
    return;
  }

  var deviceSelect = document.getElementById('switchmap-device');
  var snapshotSelect = document.getElementById('switchmap-snapshot');
  var loadBtn = document.getElementById('switchmap-load');
  var downloadBtn = document.getElementById('switchmap-download');
  var summaryEl = document.getElementById('switchmap-summary');
  var previewEl = document.getElementById('switchmap-preview');
  var statusEl = document.getElementById('switchmap-status');
  var errorEl = document.getElementById('switchmap-error');
  var metaEl = document.getElementById('switchmap-meta');

  var currentDevices = [];
  var currentSite = root.dataset.site || '';

  function showError(message) {
    if (!errorEl) {
      return;
    }
    errorEl.textContent = message || '';
    errorEl.hidden = !message;
  }

  function showStatus(message) {
    if (!statusEl) {
      return;
    }
    statusEl.textContent = message || '';
    statusEl.hidden = !message;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function selectedDeviceId() {
    return deviceSelect ? deviceSelect.value : '';
  }

  function selectedSnapshot() {
    return snapshotSelect ? snapshotSelect.value : '';
  }

  function logUrl(deviceId, snapshotTs) {
    var base = '/switchmap/devices/' + encodeURIComponent(deviceId) + '/log';
    if (snapshotTs) {
      return base + '?snapshot_ts=' + encodeURIComponent(snapshotTs);
    }
    return base;
  }

  function vlanColorsUrl(site, vlanIds) {
    var q = 'site=' + encodeURIComponent(site) + '&vlan_ids=' + encodeURIComponent(vlanIds.join(','));
    return '/switchmap/api/vlan-colors?' + q;
  }

  function onboardedVlanIds(device) {
    var ids = {};
    Object.keys(device.vlans || {}).forEach(function (id) {
      ids[id] = true;
    });
    (device.physicalPorts || []).forEach(function (port) {
      if (port.accessVlan) {
        ids[port.accessVlan] = true;
      }
    });
    return Object.keys(ids).sort(function (a, b) {
      return parseInt(a, 10) - parseInt(b, 10);
    });
  }

  function renderPortBox(port, registry) {
    var style = SwitchDraw.portStyle(port, registry);
    var label = SwitchDraw.portLabel(port);
    var status = SwitchDraw.portStatusDisplay(port);
    return [
      '<div class="port-box">',
      '<div class="port-vlan-cell" style="background:' + style.fill + ';color:' + style.vlanText + '">',
      '<div class="port-name">' + escapeHtml(label.title) + '</div>',
      '<div class="port-vlan">' + escapeHtml(label.vlan) + '</div>',
      '</div>',
      '<div class="port-status-cell" style="background:' + status.fill + ';color:' + status.textColor + '">',
      escapeHtml(status.text),
      '</div>',
      '</div>'
    ].join('');
  }

  function renderPreview(devices) {
    if (!previewEl) {
      return;
    }
    if (!devices.length) {
      previewEl.innerHTML = '';
      return;
    }
    previewEl.innerHTML = devices.map(function (device) {
      var registry = device.colorRegistry || SwitchDraw.createColorRegistry(device);
      var groups = SwitchDraw.buildFaceplateGroups(device.physicalPorts);
      var groupHtml = groups.map(function (group) {
        return [
          '<section class="module-block">',
          '<h3>' + escapeHtml(group.moduleLabel) + '</h3>',
          '<div class="row-label">奇數埠（上排）</div>',
          '<div class="port-row">' + group.oddRow.map(function (p) { return renderPortBox(p, registry); }).join('') + '</div>',
          '<div class="row-label">偶數埠（下排）</div>',
          '<div class="port-row">' + group.evenRow.map(function (p) { return renderPortBox(p, registry); }).join('') + '</div>',
          '</section>'
        ].join('');
      }).join('');
      return [
        '<section class="device-preview">',
        '<h2>' + escapeHtml(device.hostname) + ' 前面板預覽</h2>',
        groupHtml,
        '</section>'
      ].join('');
    }).join('');
  }

  function renderSummary(devices) {
    if (!summaryEl) {
      return;
    }
    if (!devices.length) {
      summaryEl.innerHTML = '<p class="muted">尚無解析結果。</p>';
      return;
    }
    summaryEl.innerHTML = devices.map(function (device) {
      var legend = SwitchDraw.buildVlanSummary(device);
      var legendHtml = legend.length
        ? [
            '<ul class="vlan-legend">',
            legend.map(function (item) {
              var label = item.id === 'trunk' ? 'Trunk' : ('VLAN ' + item.id);
              var textColor = item.textColor || SwitchDraw.bestTextColorForFill(item.color);
              return [
                '<li class="vlan-swatch" style="background:',
                item.color,
                ';color:',
                textColor,
                '">',
                escapeHtml(label),
                ' (',
                item.portCount,
                ')</li>'
              ].join('');
            }).join(''),
            '</ul>'
          ].join('')
        : '';
      return [
        '<article class="summary-card">',
        '<h2>' + escapeHtml(device.hostname) + '</h2>',
        '<ul>',
        '<li>實體埠：' + device.counts.total + '</li>',
        '<li>Up：' + device.counts.up + '</li>',
        '<li>Down：' + device.counts.down + '</li>',
        '<li>Shutdown：' + device.counts.shutdown + '</li>',
        '<li>VLAN 數：' + Object.keys(device.vlans).length + '</li>',
        '</ul>',
        legendHtml,
        '</article>'
      ].join('');
    }).join('');
  }

  function handleParsedDevices(devices, serverMap) {
    currentDevices = devices.map(function (device) {
      return SwitchDraw.enrichDevice(device, serverMap);
    });
    renderSummary(currentDevices);
    renderPreview(currentDevices);
    if (downloadBtn) {
      downloadBtn.disabled = !currentDevices.length;
    }
    if (currentDevices.length) {
      showStatus('就緒。可下載 Excel 埠位圖（.xlsx）。');
    }
  }

  function loadSnapshotList(deviceId) {
    if (!snapshotSelect || !deviceId) {
      return;
    }
    fetch('/switchmap/partial/snapshots?device_id=' + encodeURIComponent(deviceId), {
      credentials: 'same-origin'
    })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        snapshotSelect.innerHTML = html;
      })
      .catch(function () {
        snapshotSelect.innerHTML = '';
      });
  }

  function loadDevice() {
    var deviceId = selectedDeviceId();
    showError('');
    showStatus('');
    currentDevices = [];
    renderSummary([]);
    renderPreview([]);
    if (downloadBtn) {
      downloadBtn.disabled = true;
    }
    if (!deviceId) {
      showError('請選擇設備。');
      return;
    }
    var vendor = deviceSelect.selectedOptions[0] && deviceSelect.selectedOptions[0].dataset.vendor;
    if (vendor && vendor.toLowerCase() !== 'cisco') {
      showError('SwitchMap 目前僅支援 Cisco 設備。');
      return;
    }

    showStatus('載入快照 log…');
    fetch(logUrl(deviceId, selectedSnapshot()), { credentials: 'same-origin' })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.text().then(function (t) {
            throw new Error(t || ('HTTP ' + resp.status));
          });
        }
        var missing = resp.headers.get('X-Switchmap-Missing') || '';
        var warn = resp.headers.get('X-Switchmap-Warnings') || '';
        if (metaEl) {
          var parts = [];
          if (missing) {
            parts.push('缺少 artifact：' + missing);
          }
          if (warn) {
            parts.push(warn);
          }
          metaEl.textContent = parts.join(' · ');
        }
        return resp.text();
      })
      .then(function (logText) {
        var devices = SwitchDraw.parseLog(logText);
        if (!devices.length) {
          throw new Error('無法解析 log，請確認已備份且為 Cisco IOS/XE。');
        }
        var site = (deviceSelect.selectedOptions[0] && deviceSelect.selectedOptions[0].dataset.site) || currentSite;
        var vlanIds = onboardedVlanIds(devices[0]);
        if (!vlanIds.length) {
          handleParsedDevices(devices, null);
          return;
        }
        return fetch(vlanColorsUrl(site, vlanIds), { credentials: 'same-origin' })
          .then(function (r) {
            if (!r.ok) {
              throw new Error('VLAN 配色 API 失敗');
            }
            return r.json();
          })
          .then(function (serverMap) {
            handleParsedDevices(devices, serverMap.colors || serverMap);
          });
      })
      .catch(function (err) {
        showError(err.message || String(err));
        showStatus('');
      });
  }

  if (deviceSelect) {
    deviceSelect.addEventListener('change', function () {
      loadSnapshotList(selectedDeviceId());
    });
  }
  if (loadBtn) {
    loadBtn.addEventListener('click', loadDevice);
  }
  if (downloadBtn) {
    downloadBtn.addEventListener('click', function () {
      if (!currentDevices.length || typeof SwitchDraw.buildWorkbookBlob !== 'function') {
        return;
      }
      var device = currentDevices[0];
      SwitchDraw.buildWorkbookBlob(device).then(function (blob) {
        var name = (device.hostname || 'switch') + '-switchport.xlsx';
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      }).catch(function (err) {
        showError('Excel 產生失敗：' + (err.message || err));
      });
    });
  }

  var initialDevice = root.dataset.initialDevice || '';
  if (initialDevice && deviceSelect) {
    deviceSelect.value = initialDevice;
    loadSnapshotList(initialDevice);
  }
})();
