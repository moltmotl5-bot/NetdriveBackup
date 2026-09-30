/* global SwitchDraw */
var SwitchDraw = SwitchDraw || {};

(function (SD) {
  'use strict';

  var IFACE_EXPAND = {
    Fa: 'FastEthernet',
    Gi: 'GigabitEthernet',
    Te: 'TenGigabitEthernet',
    Tw: 'TwentyFiveGigE',
    Fi: 'FiveGigabitEthernet',
    Fo: 'FortyGigabitEthernet',
    Hu: 'HundredGigE',
    Twe: 'TwoGigabitEthernet',
    Eth: 'Ethernet'
  };

  var IFACE_SHORT = {};
  Object.keys(IFACE_EXPAND).forEach(function (short) {
    IFACE_SHORT[IFACE_EXPAND[short]] = short;
  });

  var PORT_PREFIX = '(?:Fa|Gi|GigabitEthernet|Te|TenGigabitEthernet|Tw|Fi|Fo|Hu|Twe|Eth|Ethernet)';

  function cleanLog(text) {
    return text
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
      .replace(/\x08+/g, '')
      .replace(/--More--[^\n]*/g, '')
      .replace(/\n\s*\n\s*\n/g, '\n\n');
  }

  function normalizeInterfaceName(raw) {
    if (!raw) {
      return '';
    }
    var name = raw.trim().replace(/\s+/g, '');
    var match = name.match(/^([A-Za-z]+)(\d[\d\/]*)$/);
    if (!match) {
      return name;
    }
    var prefix = match[1];
    var suffix = match[2];
    var shortPrefix = prefix;

    if (prefix.length > 2 && IFACE_SHORT[prefix]) {
      shortPrefix = IFACE_SHORT[prefix];
    } else if (prefix.length === 2 && IFACE_EXPAND[prefix]) {
      shortPrefix = prefix;
    } else {
      var keys = Object.keys(IFACE_SHORT);
      for (var i = 0; i < keys.length; i++) {
        if (prefix.indexOf(keys[i]) === 0 || IFACE_SHORT[keys[i]].indexOf(prefix) === 0) {
          shortPrefix = IFACE_SHORT[keys[i]];
          break;
        }
      }
    }

    return shortPrefix + suffix;
  }

  function parseInterfaceParts(name) {
    var normalized = normalizeInterfaceName(name);
    var match = normalized.match(/^([A-Za-z]+)(\d+)\/(\d+)\/(\d+)$/);
    if (match) {
      return {
        short: match[1],
        stack: parseInt(match[2], 10),
        module: parseInt(match[3], 10),
        port: parseInt(match[4], 10),
        normalized: normalized
      };
    }
    match = normalized.match(/^([A-Za-z]+)(\d+)\/(\d+)$/);
    if (match) {
      return {
        short: match[1],
        stack: 0,
        module: parseInt(match[2], 10),
        port: parseInt(match[3], 10),
        normalized: normalized
      };
    }
    return {
      short: normalized.replace(/\d.*/, ''),
      stack: 0,
      module: 0,
      port: 0,
      normalized: normalized
    };
  }

  function isPhysicalInterface(name) {
    var n = normalizeInterfaceName(name);
    return /^(Fa|Gi|Te|Tw|Fi|Fo|Hu|Twe|Eth)\d+\/\d+\/\d+$/.test(n) ||
      /^(Fa|Gi|Te|Tw|Fi|Fo|Hu|Twe|Eth)\d+\/\d+$/.test(n);
  }

  function normalizeLinkStatus(status, protocol) {
    var s = String(status || '').toLowerCase().trim();
    var p = String(protocol || '').toLowerCase().trim();

    if (s.indexOf('administratively down') !== -1 || s === 'disabled') {
      return 'disabled';
    }
    if (s.indexOf('err-disabled') !== -1) {
      return 'err-disabled';
    }
    if (s.indexOf('connected') === 0 || s === 'up') {
      return 'connected';
    }
    if (s === 'notconnect' || s === 'not connected' || s === 'down' || p === 'down') {
      return 'notconnect';
    }
    if (p === 'up' && s !== 'down') {
      return 'connected';
    }
    return s || 'unknown';
  }

  function isLinkUp(linkStatus) {
    return linkStatus === 'connected';
  }

  var COMMAND_PATTERNS = {
    interfaceStatus: /^(?:show|sh)\s+(?:interfaces?\s+status|int\s+status)$/i,
    ipBrief: /^(?:show|sh)\s+ip\s+(?:interface\s+|int\s+)(?:brief|br)$/i,
    vlanBrief: /^(?:show|sh)\s+vlan\s+(?:brief|br)$/i,
    intDescription: /^(?:show|sh)\s+(?:interfaces?\s+description|int\s+desc(?:ription)?)$/i,
    cdpNeighbors: /^(?:show|sh)\s+cdp\s+nei(?:ghbors)?(?:\s+(?:detail|det))?$/i,
    lldpNeighbors: /^(?:show|sh)\s+lldp\s+nei(?:ghbors)?(?:\s+(?:detail|det))?$/i
  };

  function stripPrompt(line) {
    return line.replace(/^[A-Za-z0-9_.-]+[#>]\s*/, '').trim();
  }

  function extractCommandSection(text, patterns) {
    var lines = text.split('\n');
    var startIdx = -1;
    var list = Array.isArray(patterns) ? patterns : [patterns];

    for (var i = 0; i < lines.length; i++) {
      var cmdLine = stripPrompt(lines[i]);
      if (!cmdLine) {
        continue;
      }
      for (var p = 0; p < list.length; p++) {
        if (list[p].test(cmdLine)) {
          startIdx = i + 1;
          break;
        }
      }
      if (startIdx !== -1) {
        break;
      }
    }

    if (startIdx === -1) {
      return '';
    }

    var sectionLines = [];
    for (var j = startIdx; j < lines.length; j++) {
      var row = lines[j];
      if (/^[A-Za-z0-9_.-]+[#>]/.test(row)) {
        break;
      }
      if (/^(?:show|sh)\s+/i.test(stripPrompt(row))) {
        break;
      }
      sectionLines.push(row);
    }

    return sectionLines.join('\n');
  }

  function splitByDevice(text) {
    var hostnameMatches = [];
    var hostnameRe = /^hostname\s+(\S+)/gm;
    var match;
    while ((match = hostnameRe.exec(text)) !== null) {
      hostnameMatches.push({ name: match[1], index: match.index });
    }

    var uniqueNames = {};
    hostnameMatches.forEach(function (entry) {
      uniqueNames[entry.name] = true;
    });

    if (Object.keys(uniqueNames).length <= 1) {
      var singleHost = hostnameMatches[0] ? hostnameMatches[0].name : '';
      if (!singleHost) {
        var promptMatch = text.match(/^([A-Za-z0-9_.-]+)[>#]/m);
        singleHost = promptMatch ? promptMatch[1] : '';
      }
      return [{ promptHost: singleHost, text: text }];
    }

    var chunks = [];
    hostnameMatches.forEach(function (entry, idx) {
      var end = idx + 1 < hostnameMatches.length ? hostnameMatches[idx + 1].index : text.length;
      chunks.push({
        promptHost: entry.name,
        text: text.slice(entry.index, end)
      });
    });

    return chunks;
  }

  function extractHostname(text, promptHost) {
    var m = text.match(/^hostname\s+(\S+)/m);
    if (m) {
      return m[1];
    }
    return promptHost || 'switch';
  }

  function parseRunningConfig(text) {
    var interfaces = {};
    var blocks = text.split(/^interface\s+/m);
    blocks.slice(1).forEach(function (block) {
      var lines = block.split('\n');
      var header = lines[0].trim();
      var ifaceName = header.split(/\s+/)[0];
      if (!ifaceName) {
        return;
      }
      var key = normalizeInterfaceName(ifaceName);
      var entry = interfaces[key] || { name: key };

      lines.slice(1).forEach(function (line) {
        var trimmed = line.trim();
        if (!trimmed || trimmed.charAt(0) === '!' || trimmed === 'exit') {
          return;
        }
        if (trimmed.indexOf('description ') === 0) {
          entry.description = trimmed.slice(12).trim();
        } else if (trimmed === 'shutdown') {
          entry.adminStatus = 'disabled';
        } else if (trimmed.indexOf('no shutdown') === 0) {
          entry.adminStatus = 'enabled';
        } else if (trimmed.indexOf('switchport mode access') === 0) {
          entry.mode = 'access';
        } else if (trimmed.indexOf('switchport mode trunk') === 0) {
          entry.mode = 'trunk';
        } else if (trimmed.indexOf('switchport access vlan ') === 0) {
          entry.accessVlan = trimmed.split(/\s+/).pop();
        } else if (trimmed.indexOf('switchport voice vlan ') === 0) {
          entry.voiceVlan = trimmed.split(/\s+/).pop();
        } else if (trimmed.indexOf('switchport trunk native vlan ') === 0) {
          entry.nativeVlan = trimmed.split(/\s+/).pop();
        } else if (trimmed.indexOf('switchport trunk allowed vlan ') === 0) {
          entry.allowedVlans = trimmed.slice(30).trim();
        } else if (trimmed.indexOf('channel-group ') === 0) {
          entry.portChannel = trimmed.split(/\s+/)[1];
        } else if (trimmed.indexOf('no switchport') === 0) {
          entry.mode = 'routed';
        }
      });

      if (!entry.adminStatus) {
        entry.adminStatus = 'enabled';
      }
      interfaces[key] = entry;
    });

    return interfaces;
  }

  function headerColumnPositions(headerLine) {
    var names = ['Port', 'Name', 'Status', 'Vlan', 'Duplex', 'Speed', 'Type'];
    var positions = [];
    names.forEach(function (name) {
      var idx = headerLine.indexOf(name);
      if (idx >= 0) {
        positions.push({ name: name, start: idx });
      }
    });
    positions.sort(function (a, b) { return a.start - b.start; });
    return positions;
  }

  function valueAtColumn(line, positions, columnName) {
    for (var i = 0; i < positions.length; i++) {
      if (positions[i].name !== columnName) {
        continue;
      }
      var start = positions[i].start;
      var end = i + 1 < positions.length ? positions[i + 1].start : line.length;
      return line.substring(start, end).trim();
    }
    return '';
  }

  function parseInterfaceTail(line) {
    var match = line.match(/\s+(trunk|\d{1,4})\s+(a-full|a-half|full|half|auto)\s+(a-[\d.]+(?:G|M|K)?|\d+[\d.]*(?:G|M|K)?|auto)\s+(\S.*)$/i);
    if (!match) {
      match = line.match(/\s+(trunk|\d{1,4})\s+(a-full|a-half|full|half|auto)\s+(auto)\s+(\S.*)$/i);
    }
    if (!match) {
      return null;
    }
    return {
      vlan: match[1],
      duplex: match[2],
      speed: match[3],
      type: match[4].trim()
    };
  }

  function parseStatusLineFromRight(rest) {
    var type = '';
    var speed = '';
    var duplex = '';
    var vlan = '';
    var status = '';
    var description = '';

    var typeMatch = rest.match(/\s+((?:10\/100\/1000)?Base[A-Za-z0-9+\/-]+|\S*(?:SFP|G-)[A-Za-z0-9+\/-]*)\s*$/i);
    if (typeMatch) {
      type = typeMatch[1].trim();
      rest = rest.slice(0, typeMatch.index).trim();
    }

    var speedMatch = rest.match(/\s+(a-?\d+(?:\.\d+)?(?:G|M|K)?|auto|\d+(?:\.\d+)?(?:G|M|K)?)\s*$/i);
    if (speedMatch) {
      speed = speedMatch[1].trim();
      rest = rest.slice(0, speedMatch.index).trim();
    }

    var duplexMatch = rest.match(/\s+(a-full|a-half|full|half|auto)\s*$/i);
    if (duplexMatch) {
      duplex = duplexMatch[1].trim();
      rest = rest.slice(0, duplexMatch.index).trim();
    }

    var vlanMatch = rest.match(/\s+(trunk|\d{1,4})\s*$/i);
    if (vlanMatch) {
      vlan = vlanMatch[1].trim();
      rest = rest.slice(0, vlanMatch.index).trim();
    }

    var tokens = rest.split(/\s+/);
    var statusWords = ['connected', 'notconnect', 'disabled', 'err-disabled', 'up', 'down'];
    var statusIndex = -1;
    var i;
    for (i = 0; i < tokens.length; i++) {
      var token = tokens[i].toLowerCase();
      if (statusWords.indexOf(token) !== -1 || token.indexOf('connected:') === 0) {
        statusIndex = i;
        break;
      }
    }
    if (statusIndex >= 0) {
      status = tokens[statusIndex];
      description = tokens.slice(0, statusIndex).join(' ');
      var tail = tokens.slice(statusIndex + 1);
      if (tail.length >= 4) {
        vlan = tail[0];
        duplex = tail[1];
        speed = tail[2];
        type = tail.slice(3).join(' ');
      }
    } else {
      description = rest.trim();
    }
    return {
      description: description,
      status: normalizeLinkStatus(status),
      vlan: vlan,
      duplex: duplex,
      speed: speed,
      type: type
    };
  }

  function parseInterfaceStatusSection(section) {
    var lines = section.split('\n');
    var result = {};
    var started = false;
    var positions = [];

    lines.forEach(function (line) {
      if (/^Port\s+/i.test(line) && /Status/i.test(line)) {
        started = true;
        positions = headerColumnPositions(line);
        return;
      }
      if (!started || !line.trim() || /^[-\s]+$/.test(line)) {
        return;
      }

      var portMatch = line.match(new RegExp('^(' + PORT_PREFIX + '\\S*)\\s*(.*)$', 'i'));
      if (!portMatch) {
        return;
      }

      var port = normalizeInterfaceName(portMatch[1]);
      if (!isPhysicalInterface(port)) {
        return;
      }

      var entry = { name: port };
      if (positions.length >= 4) {
        entry.description = valueAtColumn(line, positions, 'Name');
        entry.status = normalizeLinkStatus(valueAtColumn(line, positions, 'Status'));
        var tail = parseInterfaceTail(line);
        if (tail) {
          entry.vlan = tail.vlan;
          entry.duplex = tail.duplex;
          entry.speed = tail.speed;
          entry.type = tail.type;
        } else {
          entry.vlan = valueAtColumn(line, positions, 'Vlan');
          entry.duplex = valueAtColumn(line, positions, 'Duplex');
          entry.speed = valueAtColumn(line, positions, 'Speed');
          entry.type = valueAtColumn(line, positions, 'Type');
        }
      } else {
        var parsed = parseStatusLineFromRight(portMatch[2]);
        entry.description = parsed.description;
        entry.status = parsed.status;
        entry.vlan = parsed.vlan;
        entry.duplex = parsed.duplex;
        entry.speed = parsed.speed;
        entry.type = parsed.type;
      }

      result[port] = entry;
    });

    return result;
  }

  function parseInterfaceStatus(text) {
    var section = extractCommandSection(text, COMMAND_PATTERNS.interfaceStatus);
    return section ? parseInterfaceStatusSection(section) : {};
  }

  function parseIpInterfaceBriefSection(section) {
    var lines = section.split('\n');
    var result = {};
    var started = false;

    lines.forEach(function (line) {
      if (/^Interface\s+/i.test(line) && /Status/i.test(line)) {
        started = true;
        return;
      }
      if (!started || !line.trim() || /^[-\s]+$/.test(line)) {
        return;
      }

      var match = line.match(new RegExp('^(' + PORT_PREFIX + '\\S*)\\s+\\S+\\s+\\S+\\s+\\S+\\s+(\\S+(?:\\s+down)?)\\s+(\\S+)\\s*$', 'i'));
      if (!match) {
        return;
      }

      var port = normalizeInterfaceName(match[1]);
      if (!isPhysicalInterface(port)) {
        return;
      }

      result[port] = {
        name: port,
        status: normalizeLinkStatus(match[2], match[3]),
        adminDown: match[2].toLowerCase().indexOf('administratively down') !== -1
      };
    });

    return result;
  }

  function parseIpInterfaceBrief(text) {
    var section = extractCommandSection(text, COMMAND_PATTERNS.ipBrief);
    return section ? parseIpInterfaceBriefSection(section) : {};
  }

  function mergeInterfaceStatus(primary, secondary) {
    var merged = {};
    Object.keys(primary).forEach(function (port) {
      merged[port] = Object.assign({}, primary[port]);
    });
    Object.keys(secondary).forEach(function (port) {
      if (!merged[port]) {
        merged[port] = Object.assign({}, secondary[port]);
      }
    });
    return merged;
  }

  function descriptionHeaderPositions(headerLine) {
    var names = ['Interface', 'Status', 'Protocol', 'Description'];
    var positions = [];
    names.forEach(function (name) {
      var idx = headerLine.indexOf(name);
      if (idx >= 0) {
        positions.push({ name: name, start: idx });
      }
    });
    positions.sort(function (a, b) { return a.start - b.start; });
    return positions;
  }

  function parseInterfacesDescriptionSection(section) {
    var lines = section.split('\n');
    var result = {};
    var started = false;
    var positions = [];

    lines.forEach(function (line) {
      if (/^Interface\s+/i.test(line) && /Description/i.test(line)) {
        started = true;
        positions = descriptionHeaderPositions(line);
        return;
      }
      if (!started || !line.trim() || /^[-\s]+$/.test(line)) {
        return;
      }

      var portMatch = line.match(new RegExp('^(' + PORT_PREFIX + '\\S*)\\s*(.*)$', 'i'));
      if (!portMatch) {
        return;
      }

      var port = normalizeInterfaceName(portMatch[1]);
      if (!isPhysicalInterface(port)) {
        return;
      }

      var entry = { name: port };
      if (positions.length >= 3) {
        var statusText = line.substring(
          positions[1].start,
          positions[2] ? positions[2].start : line.length
        ).trim();
        var protocol = positions[2] && positions[3]
          ? line.substring(positions[2].start, positions[3].start).trim()
          : '';
        var description = positions[3]
          ? line.substring(positions[3].start).trim()
          : '';
        entry.status = normalizeLinkStatus(statusText, protocol);
        entry.adminDown = statusText.toLowerCase().indexOf('admin') !== -1;
        entry.description = description;
      } else {
        var restMatch = portMatch[2].match(/^((?:admin\s+down|\S+))\s+(\S+)\s*(.*)$/i);
        if (!restMatch) {
          return;
        }
        entry.status = normalizeLinkStatus(restMatch[1], restMatch[2]);
        entry.adminDown = restMatch[1].toLowerCase().indexOf('admin') !== -1;
        entry.description = restMatch[3].trim();
      }

      if (entry.description) {
        result[port] = entry;
      }
    });

    return result;
  }

  function parseInterfacesDescription(text) {
    var section = extractCommandSection(text, COMMAND_PATTERNS.intDescription);
    return section ? parseInterfacesDescriptionSection(section) : {};
  }

  function parseVlanBriefSection(section) {
    var lines = section.split('\n');
    var vlans = {};
    var started = false;

    lines.forEach(function (line) {
      if (/^VLAN\s+Name/i.test(line)) {
        started = true;
        return;
      }
      if (!started || !line.trim() || /^[-=\s]+$/.test(line)) {
        return;
      }

      var m = line.match(/^(\d{1,4})\s+(.+?)\s+(active|suspend|act\/\S+|unsupport|unsup)\s*(.*)?$/i);
      if (m) {
        vlans[m[1]] = {
          id: m[1],
          name: m[2].trim(),
          ports: m[4] ? m[4].split(',').map(function (p) {
            return normalizeInterfaceName(p.trim());
          }).filter(Boolean) : []
        };
      }
    });

    return vlans;
  }

  function parseVlansFromConfig(text) {
    var vlans = {};
    var blocks = text.split(/^vlan\s+/im);
    blocks.slice(1).forEach(function (block) {
      var idMatch = block.match(/^(\d{1,4})\b/);
      if (!idMatch) {
        return;
      }
      var id = idMatch[1];
      var nameMatch = block.match(/^name\s+(.+)$/im);
      vlans[id] = {
        id: id,
        name: nameMatch ? nameMatch[1].trim() : ('VLAN' + id),
        ports: []
      };
    });
    return vlans;
  }

  function parseVlanBrief(text) {
    var section = extractCommandSection(text, COMMAND_PATTERNS.vlanBrief);
    var vlans = section ? parseVlanBriefSection(section) : {};
    return Object.assign({}, parseVlansFromConfig(text), vlans);
  }

  function enrichVlansFromPorts(vlans, ports) {
    var enriched = Object.assign({}, vlans);
    ports.forEach(function (port) {
      ['accessVlan', 'voiceVlan', 'nativeVlan'].forEach(function (field) {
        var id = port[field];
        if (id && !enriched[id]) {
          enriched[id] = { id: id, name: 'VLAN' + id, ports: [] };
        }
      });
    });
    return enriched;
  }

  function parseCdpNeighbors(text) {
    var section = extractCommandSection(text, COMMAND_PATTERNS.cdpNeighbors);
    if (!section) {
      return {};
    }

    var neighbors = {};
    var lines = section.split('\n');
    var current = null;

    lines.forEach(function (line) {
      var detailDevice = line.match(/^Device ID:\s*(.+)$/i);
      if (detailDevice) {
        current = { device: detailDevice[1].trim() };
        return;
      }
      var local = line.match(/^Interface:\s*(.+?),\s*Port ID \(outgoing port\):\s*(.+)$/i);
      if (local && current) {
        var port = normalizeInterfaceName(local[1].trim());
        neighbors[port] = {
          neighbor: current.device,
          neighborPort: local[2].trim()
        };
        current = null;
        return;
      }

      if (/^Device ID\s+Local Intrfce/i.test(line)) {
        return;
      }
      var row = line.match(/^(\S+)\s+(\S+\s*\d+\/\d+(?:\/\d+)?)\s+\d+/);
      if (row) {
        var localPort = normalizeInterfaceName(row[2].replace(/\s+/g, ''));
        neighbors[localPort] = neighbors[localPort] || { neighbor: row[1] };
      }
      var portId = line.match(/^Platform:\s*.+,\s*Port ID \(outgoing port\):\s*(.+)$/i);
      if (portId && current) {
        current.neighborPort = portId[1].trim();
      }
    });

    return neighbors;
  }

  function parseLldpNeighbors(text) {
    var section = extractCommandSection(text, COMMAND_PATTERNS.lldpNeighbors);
    if (!section) {
      return {};
    }

    var neighbors = {};
    var lines = section.split('\n');
    var currentLocal = '';

    lines.forEach(function (line) {
      var local = line.match(/^Local Intf:\s*(.+)$/i);
      if (local) {
        currentLocal = normalizeInterfaceName(local[1].trim());
        neighbors[currentLocal] = neighbors[currentLocal] || {};
        return;
      }
      var sysName = line.match(/^System Name:\s*(.+)$/i);
      if (sysName && currentLocal) {
        neighbors[currentLocal].neighbor = sysName[1].trim();
        return;
      }
      var portId = line.match(/^Port id:\s*(.+)$/i);
      if (portId && currentLocal) {
        neighbors[currentLocal].neighborPort = portId[1].trim();
      }
    });

    return neighbors;
  }

  function mergeNeighbors(cdp, lldp) {
    var merged = {};
    Object.keys(cdp).forEach(function (port) {
      merged[port] = Object.assign({}, cdp[port]);
    });
    Object.keys(lldp).forEach(function (port) {
      merged[port] = Object.assign({}, merged[port] || {}, lldp[port]);
    });
    return merged;
  }

  function mergePortData(config, status, vlans, neighbors, descriptions) {
    var names = {};
    Object.keys(config).forEach(function (k) { names[k] = true; });
    Object.keys(status).forEach(function (k) { names[k] = true; });
    Object.keys(descriptions || {}).forEach(function (k) { names[k] = true; });

    var ports = [];
    Object.keys(names).sort(compareInterfaces).forEach(function (name) {
      var cfg = config[name] || {};
      var st = status[name] || {};
      var desc = (descriptions && descriptions[name]) || {};
      var n = neighbors[name] || {};
      var accessVlan = cfg.accessVlan || (cfg.mode !== 'trunk' && st.vlan && st.vlan !== 'trunk' ? st.vlan : '');
      var vlanName = accessVlan && vlans[accessVlan] ? vlans[accessVlan].name : '';
      var adminStatus = cfg.adminStatus || (st.adminDown || desc.adminDown ? 'disabled' : 'enabled');
      var linkStatus = st.status || desc.status || 'unknown';
      var bestDescription = cfg.description || desc.description || st.description || '';

      ports.push({
        name: name,
        parts: parseInterfaceParts(name),
        description: bestDescription,
        adminStatus: adminStatus,
        linkStatus: linkStatus,
        mode: cfg.mode || (st.vlan === 'trunk' ? 'trunk' : 'access'),
        accessVlan: accessVlan,
        vlanName: vlanName,
        voiceVlan: cfg.voiceVlan || '',
        nativeVlan: cfg.nativeVlan || '',
        allowedVlans: cfg.allowedVlans || '',
        duplex: st.duplex || '',
        speed: st.speed || '',
        type: st.type || '',
        portChannel: cfg.portChannel || '',
        neighbor: n.neighbor || '',
        neighborPort: n.neighborPort || '',
        physical: isPhysicalInterface(name)
      });
    });

    return ports;
  }

  function compareInterfaces(a, b) {
    var pa = parseInterfaceParts(a);
    var pb = parseInterfaceParts(b);
    if (pa.short !== pb.short) {
      return pa.short.localeCompare(pb.short);
    }
    if (pa.stack !== pb.stack) {
      return pa.stack - pb.stack;
    }
    if (pa.module !== pb.module) {
      return pa.module - pb.module;
    }
    return pa.port - pb.port;
  }

  function parseDeviceChunk(chunk) {
    var text = chunk.text;
    var hostname = extractHostname(text, chunk.promptHost);
    var config = parseRunningConfig(text);
    var status = mergeInterfaceStatus(
      parseInterfaceStatus(text),
      parseIpInterfaceBrief(text)
    );
    var descriptions = parseInterfacesDescription(text);
    var vlans = parseVlanBrief(text);
    var neighbors = mergeNeighbors(parseCdpNeighbors(text), parseLldpNeighbors(text));
    var ports = mergePortData(config, status, vlans, neighbors, descriptions);
    vlans = enrichVlansFromPorts(vlans, ports);

    var physical = ports.filter(function (p) { return p.physical; });
    var counts = {
      total: physical.length,
      up: physical.filter(function (p) {
        return p.adminStatus !== 'disabled' && isLinkUp(p.linkStatus);
      }).length,
      down: physical.filter(function (p) {
        return p.adminStatus !== 'disabled' && !isLinkUp(p.linkStatus);
      }).length,
      shutdown: physical.filter(function (p) {
        return p.adminStatus === 'disabled';
      }).length
    };

    return {
      hostname: hostname,
      vlans: vlans,
      ports: ports,
      physicalPorts: physical,
      counts: counts
    };
  }

  function parseLog(text) {
    var cleaned = cleanLog(text);
    var chunks = splitByDevice(cleaned);
    return chunks.map(parseDeviceChunk).filter(function (device) {
      return device.ports.length > 0;
    });
  }

  SD.parseLog = parseLog;
  SD.cleanLog = cleanLog;
  SD.normalizeInterfaceName = normalizeInterfaceName;
  SD.normalizeLinkStatus = normalizeLinkStatus;
  SD.isLinkUp = isLinkUp;
  SD.parseInterfaceParts = parseInterfaceParts;
  SD.isPhysicalInterface = isPhysicalInterface;
  SD.compareInterfaces = compareInterfaces;
  SD.extractCommandSection = extractCommandSection;
  SD.COMMAND_PATTERNS = COMMAND_PATTERNS;
})(SwitchDraw);

(function (root, sd) {
  root.SwitchDraw = sd;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = sd;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, SwitchDraw);
