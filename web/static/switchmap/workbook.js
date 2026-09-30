/* global SwitchDraw, ExcelJS */
var SwitchDraw = (typeof globalThis !== 'undefined' ? globalThis : this).SwitchDraw || {};

(function (SD) {
  'use strict';

  function getExcelJS() {
    if (typeof ExcelJS !== 'undefined') {
      return ExcelJS;
    }
    if (typeof require !== 'undefined') {
      return require('exceljs');
    }
    throw new Error('ExcelJS 未載入');
  }

  function sanitizeCellValue(value) {
    if (value == null) {
      return '';
    }
    if (typeof value !== 'string') {
      return value;
    }
    return value.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
  }

  function hexToArgb(hex) {
    return 'FF' + String(hex || '#FFFFFF').replace('#', '').toUpperCase();
  }

  function setCellValue(cell, value) {
    cell.value = sanitizeCellValue(value);
  }

  function applyBorder(cell) {
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF999999' } },
      left: { style: 'thin', color: { argb: 'FF999999' } },
      bottom: { style: 'thin', color: { argb: 'FF999999' } },
      right: { style: 'thin', color: { argb: 'FF999999' } }
    };
  }

  function fillCell(cell, hexColor, options) {
    var opts = options || {};
    cell.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: hexToArgb(hexColor) }
    };
    cell.alignment = {
      vertical: 'middle',
      horizontal: 'center',
      wrapText: true
    };
    cell.font = {
      name: 'Calibri',
      size: opts.fontSize || 9,
      bold: !!opts.bold,
      color: { argb: hexToArgb(opts.textColor || '#1A1A1A') }
    };
    applyBorder(cell);
  }

  function styleHeaderCell(cell, value) {
    setCellValue(cell, value);
    fillCell(cell, '#ECF0F1', { bold: true, fontSize: 10 });
  }

  function writeLegend(sheet, device, startRow) {
    var row = startRow;
    var title = sheet.getCell('A' + row);
    setCellValue(title, device.hostname + ' 前面板');
    title.font = { name: 'Calibri', size: 14, bold: true };
    row += 1;

    setCellValue(sheet.getCell('A' + row), '總埠數: ' + device.counts.total);
    setCellValue(sheet.getCell('B' + row), 'Up: ' + device.counts.up);
    setCellValue(sheet.getCell('C' + row), 'Down: ' + device.counts.down);
    setCellValue(sheet.getCell('D' + row), 'Shutdown: ' + device.counts.shutdown);
    row += 1;

    styleHeaderCell(sheet.getCell('A' + row), 'VLAN 圖例');
    row += 1;

    var legend = SD.buildVlanSummary(device);
    legend.forEach(function (item, index) {
      var cell = sheet.getCell(row, index + 1);
      var label = item.id === 'trunk' ? 'TRUNK' : ('VLAN ' + item.id + ' ' + item.name);
      setCellValue(cell, label + ' (' + item.portCount + ')');
      fillCell(cell, item.color, { textColor: item.textColor || '#1A1A1A' });
    });

    return row + 2;
  }

  function writePortRow(sheet, rowIndex, ports, registry) {
    ports.forEach(function (port, index) {
      var colVlan = index * 2 + 1;
      var colStatus = index * 2 + 2;
      var vlanCell = sheet.getCell(rowIndex, colVlan);
      var statusCell = sheet.getCell(rowIndex, colStatus);
      var label = SD.portLabel(port);
      var vlanFill = SD.portVlanColor(port, registry);
      var status = SD.portStatusDisplay(port);

      var style = SD.portStyle(port, registry);
      setCellValue(vlanCell, label.title + '\n' + label.vlan);
      fillCell(vlanCell, vlanFill, { textColor: style.vlanText || '#1A1A1A' });

      setCellValue(statusCell, status.text);
      fillCell(statusCell, status.fill, { textColor: status.textColor });
    });
    sheet.getRow(rowIndex).height = 42;
  }

  function writeModuleBlock(sheet, group, startRow, registry) {
    var portCount = Math.max(group.oddRow.length, group.evenRow.length, 1);
    var colCount = portCount * 2;
    for (var c = 1; c <= colCount; c++) {
      sheet.getColumn(c).width = c % 2 === 1 ? 11 : 9;
    }

    var row = startRow;
    styleHeaderCell(sheet.getCell('A' + row), group.moduleLabel + '（奇數埠 · 上排）');
    row += 1;
    writePortRow(sheet, row, group.oddRow, registry);
    row += 1;
    styleHeaderCell(sheet.getCell('A' + row), group.moduleLabel + '（偶數埠 · 下排）');
    row += 1;
    writePortRow(sheet, row, group.evenRow, registry);
    return row + 1;
  }

  function buildFaceplateSheet(workbook, device) {
    var registry = device.colorRegistry || SD.createColorRegistry(device);
    var groups = SD.buildFaceplateGroups(device.physicalPorts);
    var sheet = workbook.addWorksheet('Faceplate', {
      views: [{ showGridLines: false }]
    });
    var row = writeLegend(sheet, device, 1);
    groups.forEach(function (group, index) {
      if (index > 0) {
        row += 1;
      }
      row = writeModuleBlock(sheet, group, row, registry);
    });
  }

  function buildPortsSheet(workbook, device) {
    var headers = [
      '主機', '模組', '介面', '描述', '管理狀態', '連線狀態', '模式',
      'Access VLAN', 'VLAN 名稱', 'Voice VLAN', 'Native VLAN', 'Allowed VLAN',
      '速率', '雙工', '類型', 'Port-channel', '鄰居', '鄰居埠'
    ];
    var sheet = workbook.addWorksheet('Ports');
    headers.forEach(function (header, index) {
      styleHeaderCell(sheet.getCell(1, index + 1), header);
      sheet.getColumn(index + 1).width = index === 3 ? 28 : 14;
    });

    device.ports.forEach(function (port, rowIndex) {
      var row = rowIndex + 2;
      var values = [
        device.hostname,
        port.parts.stack + '/' + port.parts.module,
        port.name,
        port.description,
        port.adminStatus === 'disabled' ? 'shutdown' : 'enabled',
        port.linkStatus,
        port.mode,
        port.accessVlan,
        port.vlanName,
        port.voiceVlan,
        port.nativeVlan,
        port.allowedVlans,
        port.speed,
        port.duplex,
        port.type,
        port.portChannel,
        port.neighbor,
        port.neighborPort
      ];
      values.forEach(function (value, colIndex) {
        setCellValue(sheet.getCell(row, colIndex + 1), value);
      });
    });

    sheet.autoFilter = {
      from: { row: 1, column: 1 },
      to: { row: device.ports.length + 1, column: headers.length }
    };
  }

  function buildVlansSheet(workbook, device) {
    var headers = ['VLAN', '名稱', '色碼', '埠數'];
    var sheet = workbook.addWorksheet('VLANs');
    headers.forEach(function (header, index) {
      styleHeaderCell(sheet.getCell(1, index + 1), header);
      sheet.getColumn(index + 1).width = 16;
    });

    SD.buildVlanSummary(device).forEach(function (item, rowIndex) {
      var row = rowIndex + 2;
      setCellValue(sheet.getCell(row, 1), item.id === 'trunk' ? '' : item.id);
      setCellValue(sheet.getCell(row, 2), item.name);
      setCellValue(sheet.getCell(row, 3), item.color);
      sheet.getCell(row, 4).value = item.portCount;
      fillCell(sheet.getCell(row, 3), item.color, { textColor: item.textColor || '#1A1A1A' });
    });
  }

  function buildWorkbook(device) {
    var Excel = getExcelJS();
    SD.enrichDevice(device);
    var workbook = new Excel.Workbook();
    workbook.creator = 'SwitchMap / SwitchDraw';
    workbook.created = new Date();
    workbook.title = sanitizeCellValue(device.hostname + ' Switchport');

    buildFaceplateSheet(workbook, device);
    buildPortsSheet(workbook, device);
    buildVlansSheet(workbook, device);

    return workbook;
  }

  function toUint8Array(buffer) {
    if (buffer instanceof Uint8Array) {
      return buffer;
    }
    if (buffer instanceof ArrayBuffer) {
      return new Uint8Array(buffer);
    }
    if (buffer && buffer.buffer instanceof ArrayBuffer) {
      return new Uint8Array(buffer.buffer, buffer.byteOffset || 0, buffer.byteLength || buffer.length);
    }
    return new Uint8Array(buffer);
  }

  function buildWorkbookBuffer(device) {
    var workbook = buildWorkbook(device);
    return workbook.xlsx.writeBuffer();
  }

  function buildWorkbookBlob(device) {
    return buildWorkbookBuffer(device).then(function (buffer) {
      var bytes = toUint8Array(buffer);
      if (typeof Blob !== 'undefined') {
        return new Blob([bytes], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        });
      }
      return bytes;
    });
  }

  SD.buildWorkbook = buildWorkbook;
  SD.buildWorkbookBuffer = buildWorkbookBuffer;
  SD.buildWorkbookBlob = buildWorkbookBlob;
  SD.sanitizeCellValue = sanitizeCellValue;
})(SwitchDraw);

(function (root, sd) {
  root.SwitchDraw = sd;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = sd;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, SwitchDraw);
