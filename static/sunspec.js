// SunSpec-Erkennung: Gerät, Modelle und Werte anzeigen, als Monitorpunkte oder ins Nachschlagewerk übernehmen.
(() => {
  const KIND = {W: 'power', kW: 'power', VA: 'power', var: 'power', Wh: 'energy', kWh: 'energy', V: 'voltage', A: 'current', Hz: 'frequency', C: 'temperature', Pct: 'percent', '%': 'percent'};
  const UNIT = {C: '°C', Pct: '%', WH: 'Wh'};
  let last = null;

  const unitOf = (point) => UNIT[point.units] || point.units || '';
  const usable = (point) => point.implemented && point.sunspec_type !== 'sunssf';

  function monitorPoint(model, point) {
    const words = point.data_type === 'string' ? point.size : ({int16: 1, uint16: 1, int32: 2, uint32: 2, float32: 2, int64: 4, uint64: 4, float64: 4}[point.data_type] || 1);
    return {
      id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
      name: `${point.label}${model.name ? ` · ${model.name}` : ''}`, unit: unitOf(point), scale: point.scale, offset: 0,
      unit_id: last.unit_id, function: 3, address: point.address, data_type: point.data_type, order: point.order,
      read_start: point.address, read_count: words, value_offset: 0,
      ...(point.data_type === 'string' ? {length: point.size} : {}),
    };
  }

  function addPoints(points) {
    points.forEach(point => { state.points.push(point); state.histories[point.id] = []; });
    saveLocal(); renderMonitor();
    toast(`${points.length} SunSpec-Datenpunkt(e) in den Live-Monitor übernommen.`);
  }

  function formatValue(point) {
    if (!point.implemented) return '<span class="muted">nicht implementiert</span>';
    const value = typeof point.value === 'number' ? formatNumber(point.value) : escapeHtml(String(point.value));
    return `${value} ${escapeHtml(unitOf(point))}`;
  }

  function render(data) {
    last = data;
    const box = $('#sunspecResult');
    if (!data.found) { box.innerHTML = `<div class="alert warning">${escapeHtml(data.hint)}</div>`; return; }
    const device = data.device || {};
    const head = `<div class="sunspec-device"><div><small>Hersteller</small><strong>${escapeHtml(device.Mn || '–')}</strong></div><div><small>Modell</small><strong>${escapeHtml(device.Md || '–')}</strong></div><div><small>Seriennummer</small><strong>${escapeHtml(device.SN || '–')}</strong></div><div><small>Firmware</small><strong>${escapeHtml(device.Vr || '–')}</strong></div><div><small>SunSpec ab</small><strong>${data.base}</strong></div></div>
      <div class="button-row"><button id="sunspecCatalogBtn" class="secondary" type="button">Ins Nachschlagewerk übernehmen</button></div>`;
    const models = data.models.map((model, index) => {
      const points = model.points.filter(point => point.sunspec_type !== 'sunssf');
      const implemented = points.filter(usable).length;
      const rows = points.map((point, row) => `<tr class="${point.implemented ? '' : 'muted-row'}"><td>${escapeHtml(point.label)}<br><small class="muted">${escapeHtml(point.name)}</small></td><td>${point.address}</td><td>${escapeHtml(point.data_type.toUpperCase())}${point.scale !== 1 ? `<br><small class="muted">× ${point.scale}</small>` : ''}</td><td class="live-value">${formatValue(point)}</td><td>${usable(point) ? `<button class="table-action" data-model="${index}" data-point="${row}">+ Monitor</button>` : ''}</td></tr>`).join('');
      return `<details class="sunspec-model"${model.id !== 1 && index < 3 ? ' open' : ''}><summary><strong>Modell ${model.id}</strong> ${escapeHtml(model.name || model.label || (model.known ? '' : 'unbekanntes Modell'))} <span class="muted">· Register ${model.address}, ${model.length} Register · ${implemented} Werte</span>${implemented ? ` <button class="secondary small" type="button" data-model-all="${index}">Alle Messwerte übernehmen</button>` : ''}</summary>
        ${model.error ? `<div class="alert warning">${escapeHtml(model.error)}</div>` : ''}${points.length ? `<div class="table-wrap"><table><thead><tr><th>Wert</th><th>Register</th><th>Typ</th><th>Aktuell</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}</details>`;
    }).join('');
    box.innerHTML = head + models;
    box.querySelectorAll('[data-point]').forEach(button => button.addEventListener('click', () => {
      const model = last.models[Number(button.dataset.model)];
      const point = model.points.filter(p => p.sunspec_type !== 'sunssf')[Number(button.dataset.point)];
      addPoints([monitorPoint(model, point)]);
    }));
    box.querySelectorAll('[data-model-all]').forEach(button => button.addEventListener('click', event => {
      event.preventDefault();
      const model = last.models[Number(button.dataset.modelAll)];
      addPoints(model.points.filter(point => usable(point) && point.units).map(point => monitorPoint(model, point)));
    }));
    $('#sunspecCatalogBtn').addEventListener('click', saveToCatalog);
  }

  async function saveToCatalog() {
    const device = last.device || {};
    const ids = last.models.map(model => model.id);
    const type = ids.some(id => [124, 802].includes(id)) ? 'batteriespeicher'
      : ids.some(id => id >= 101 && id <= 113) ? 'wechselrichter'
      : ids.some(id => id >= 201 && id <= 214) ? 'energiezaehler' : 'sonstiges';
    const points = last.models.flatMap(model => model.points.filter(point => usable(point) && point.units).map(point => ({
      name: `${point.label}${model.name ? ` · ${model.name}` : ''}`, quantity_kind: KIND[point.units] || 'other', function: 3,
      address: point.address, data_type: point.data_type, order: point.order, scale: point.scale,
      ...(point.scale_factor_address !== null ? {scale_factor_address: point.scale_factor_address, scale_factor_type: 'int16 (SunSpec SF, Faktor 10^SF)'} : {}),
      unit: unitOf(point), confidence: 'hoch', caveats: `SunSpec-Modell ${model.id}, Punkt ${point.name}`,
    })));
    const entry = {
      schema: 'hbtec-device-catalog-entry', schema_version: 1,
      manufacturer: device.Mn || 'SunSpec-Gerät', model: device.Md || `Unit-ID ${last.unit_id}`, device_type: type,
      notes: `Per SunSpec-Erkennung ausgelesen (Basis ${last.base}, Modelle ${ids.join(', ')}, Firmware ${device.Vr || '–'}). Faktoren aus den Skalierungsregistern zum Zeitpunkt der Erkennung; das jeweilige SF-Register ist angegeben.`,
      source_url: 'https://github.com/sunspec/models', source_note: 'SunSpec-Erkennung am Gerät', verified: true, points,
    };
    try {
      const result = await profileLibraryRequest('/api/device-catalog-import', {method: 'POST', body: {data: entry}});
      toast(`${entry.manufacturer} ${entry.model}: ${points.length} Datenpunkte im Nachschlagewerk ${result.created ? 'angelegt' : 'aktualisiert'}.`);
      if (typeof loadCatalog === 'function') loadCatalog();
    } catch (error) { toast(error.message || 'Übernahme fehlgeschlagen.', true); }
  }

  $('#sunspecScanBtn')?.addEventListener('click', async () => {
    try {
      const data = await api('/api/sunspec-scan', {connection: connection(), unit_id: Number($('#finderUnit').value) || 1}, $('#sunspecScanBtn'));
      render(data);
      if (data.found) toast(`SunSpec gefunden: ${data.models.length} Modelle in ${data.duration_ms} ms.`);
    } catch (_) { /* api zeigt den Fehler */ }
  });
})();
