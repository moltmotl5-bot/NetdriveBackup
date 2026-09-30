/* global SwitchDraw */
var SwitchDraw = (typeof globalThis !== 'undefined' ? globalThis : this).SwitchDraw || {};

(function (SD) {
  'use strict';

  var VLAN_PAIRS = [
    { fill: '#4E79A7', text: '#FFFFFF' }, { fill: '#F28E2B', text: '#1A1A1A' },
    { fill: '#E15759', text: '#FFFFFF' }, { fill: '#76B7B2', text: '#1A1A1A' },
    { fill: '#59A14F', text: '#FFFFFF' }, { fill: '#EDC948', text: '#1A1A1A' },
    { fill: '#B07AA1', text: '#FFFFFF' }, { fill: '#FF9DA7', text: '#1A1A1A' },
    { fill: '#9C755F', text: '#FFFFFF' }, { fill: '#BAB0AC', text: '#1A1A1A' },
    { fill: '#86BCB6', text: '#1A1A1A' }, { fill: '#D37295', text: '#FFFFFF' },
    { fill: '#FABFD2', text: '#1A1A1A' }, { fill: '#8CD17D', text: '#1A1A1A' },
    { fill: '#B6992D', text: '#FFFFFF' }, { fill: '#499894', text: '#FFFFFF' },
    { fill: '#79706E', text: '#FFFFFF' }, { fill: '#D4A6C8', text: '#1A1A1A' },
    { fill: '#FFBE7D', text: '#1A1A1A' }, { fill: '#AEC7E8', text: '#1A1A1A' }
  ];

  var TRUNK_COLOR = '#2C3E50';
  var SHUTDOWN_COLOR = '#BDC3C7';
  var ERR_COLOR = '#C0392B';
  var ROUTED_COLOR = '#8E44AD';
  var STATUS_CONNECTED_FILL = '#D5F5E3';
  var STATUS_CONNECTED_TEXT = '#1E8449';
  var STATUS_DOWN_FILL = '#FCF3CF';
  var STATUS_DOWN_TEXT = '#7D6608';
  var STATUS_UNKNOWN_FILL = '#F2F3F4';
  var STATUS_UNKNOWN_TEXT = '#566573';

  function createColorRegistry(device) {
    var vlanIds = {};
    Object.keys(device.vlans || {}).forEach(function (id) {
      vlanIds[id] = true;
    });
    (device.physicalPorts || []).forEach(function (port) {
      if (port.accessVlan) {
        vlanIds[port.accessVlan] = true;
      }
    });

    var sorted = Object.keys(vlanIds).sort(function (a, b) {
      return parseInt(a, 10) - parseInt(b, 10);
    });

    var vlan = {};
    var vlanText = {};
    var usedPairs = {};
    sorted.forEach(function (id, index) {
      var pair = VLAN_PAIRS[index];
      if (!pair) {
        throw new Error('VLAN 配色表已用盡（onboarded VLAN 數超過預設配對表）。');
      }
      var key = pair.fill + '|' + pair.text;
      if (usedPairs[key]) {
        throw new Error('VLAN 配色重複：' + id);
      }
      usedPairs[key] = true;
      vlan[id] = pair.fill;
      vlanText[id] = pair.text;
    });

    return {
      vlan: vlan,
      vlanText: vlanText,
      special: {
        trunk: TRUNK_COLOR,
        shutdown: SHUTDOWN_COLOR,
        errDisabled: ERR_COLOR,
        routed: ROUTED_COLOR,
        unknown: '#D5D8DC'
      }
    };
  }

  function applyServerVlanColors(device, serverMap) {
    var base = createColorRegistry(device);
    if (serverMap && typeof serverMap === 'object') {
      Object.keys(serverMap).forEach(function (id) {
        var entry = serverMap[id];
        if (entry && entry.fill) {
          base.vlan[id] = entry.fill;
          base.vlanText[id] = entry.text || '#1A1A1A';
        }
      });
    }
    device.colorRegistry = base;
    return device;
  }

  function enrichDevice(device, serverMap) {
    if (serverMap) {
      return applyServerVlanColors(device, serverMap);
    }
    device.colorRegistry = createColorRegistry(device);
    return device;
  }

  function getVlanColor(registry, vlanId) {
    if (!registry || !vlanId) {
      return '#D5D8DC';
    }
    return registry.vlan[vlanId] || registry.special.unknown;
  }

  function portVlanColor(port, registry) {
    if (port.adminStatus === 'disabled') {
      return registry.special.shutdown;
    }
    if (port.mode === 'trunk') {
      return registry.special.trunk;
    }
    if (port.mode === 'routed') {
      return registry.special.routed;
    }
    return getVlanColor(registry, port.accessVlan);
  }

  function portStatusDisplay(port) {
    if (port.adminStatus === 'disabled') {
      return { text: 'shutdown', fill: SHUTDOWN_COLOR, textColor: '#2C3E50' };
    }
    if (port.linkStatus === 'err-disabled') {
      return { text: 'err-disable', fill: ERR_COLOR, textColor: '#FFFFFF' };
    }
    if (port.mode === 'trunk') {
      return { text: 'trunk', fill: TRUNK_COLOR, textColor: '#FFFFFF' };
    }
    if (port.mode === 'routed') {
      return { text: 'routed', fill: ROUTED_COLOR, textColor: '#FFFFFF' };
    }
    if (SD.isLinkUp(port.linkStatus)) {
      return { text: 'connected', fill: STATUS_CONNECTED_FILL, textColor: STATUS_CONNECTED_TEXT };
    }
    if (port.linkStatus === 'notconnect') {
      return { text: 'notconnect', fill: STATUS_DOWN_FILL, textColor: STATUS_DOWN_TEXT };
    }
    return {
      text: port.linkStatus || 'unknown',
      fill: STATUS_UNKNOWN_FILL,
      textColor: STATUS_UNKNOWN_TEXT
    };
  }

  function portStyle(port, registry) {
    var reg = registry || { vlan: {}, special: { unknown: '#D5D8DC', trunk: TRUNK_COLOR, shutdown: SHUTDOWN_COLOR } };
    var fill = portVlanColor(port, reg);
    var status = portStatusDisplay(port);
    var vlanText = '#1A1A1A';
    if (port.accessVlan && reg.vlanText && reg.vlanText[port.accessVlan]) {
      vlanText = reg.vlanText[port.accessVlan];
    }
    return {
      fill: fill,
      text: status.textColor,
      vlanText: vlanText,
      label: port.mode === 'trunk' ? 'TRUNK' : (port.accessVlan || '-'),
      statusFill: status.fill,
      statusText: status.textColor
    };
  }

  function portLabel(port) {
    var parts = port.parts;
    var shortName = parts.normalized.replace(/^([A-Za-z]+)/, function (m) { return m; });
    var line2 = port.mode === 'trunk' ? 'TRUNK' : (port.accessVlan || '-');
    var line3 = port.neighbor || port.description || '';
    if (line3.length > 18) {
      line3 = line3.slice(0, 16) + '..';
    }
    return {
      title: shortName,
      vlan: line2,
      detail: line3,
      status: portStatusDisplay(port).text
    };
  }

  function groupKey(port) {
    var p = port.parts;
    return p.short + p.stack + '/' + p.module;
  }

  function sheetName(key) {
    return key.replace(/\//g, '-').slice(0, 31);
  }

  function buildFaceplateGroups(physicalPorts) {
    var groups = {};
    physicalPorts.forEach(function (port) {
      var key = groupKey(port);
      if (!groups[key]) {
        groups[key] = {
          key: key,
          sheetName: sheetName(key),
          moduleLabel: key,
          ports: []
        };
      }
      groups[key].ports.push(port);
    });

    return Object.keys(groups).sort().map(function (key) {
      var group = groups[key];
      var ports = group.ports.slice().sort(function (a, b) {
        return a.parts.port - b.parts.port;
      });
      var odd = ports.filter(function (p) { return p.parts.port % 2 === 1; });
      var even = ports.filter(function (p) { return p.parts.port % 2 === 0; });
      return {
        key: group.key,
        sheetName: group.sheetName,
        moduleLabel: group.moduleLabel,
        oddRow: odd,
        evenRow: even,
        allPorts: ports
      };
    });
  }

  function buildVlanSummary(device) {
    var registry = device.colorRegistry || createColorRegistry(device);
    var counts = {};
    device.physicalPorts.forEach(function (port) {
      if (port.mode === 'trunk') {
        counts.trunk = (counts.trunk || 0) + 1;
        return;
      }
      if (port.accessVlan) {
        counts[port.accessVlan] = (counts[port.accessVlan] || 0) + 1;
      }
    });

    var rows = Object.keys(registry.vlan).sort(function (a, b) {
      return parseInt(a, 10) - parseInt(b, 10);
    }).map(function (id) {
      return {
        id: id,
        name: device.vlans[id] ? device.vlans[id].name : ('VLAN' + id),
        color: registry.vlan[id],
        textColor: (registry.vlanText && registry.vlanText[id]) || '#1A1A1A',
        portCount: counts[id] || 0
      };
    });

    if (counts.trunk) {
      rows.push({
        id: 'trunk',
        name: 'Trunk',
        color: registry.special.trunk,
        portCount: counts.trunk
      });
    }

    return rows;
  }

  SD.createColorRegistry = createColorRegistry;
  SD.applyServerVlanColors = applyServerVlanColors;
  SD.enrichDevice = enrichDevice;
  SD.getVlanColor = getVlanColor;
  SD.portVlanColor = portVlanColor;
  SD.portStatusDisplay = portStatusDisplay;
  SD.portStyle = portStyle;
  SD.portLabel = portLabel;
  SD.buildFaceplateGroups = buildFaceplateGroups;
  SD.buildVlanSummary = buildVlanSummary;
  SD.TRUNK_COLOR = TRUNK_COLOR;
  SD.SHUTDOWN_COLOR = SHUTDOWN_COLOR;
})(SwitchDraw);

(function (root, sd) {
  root.SwitchDraw = sd;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = sd;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, SwitchDraw);
