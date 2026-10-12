// Gemeinsame Verbindung (Status), Schreiben mit Freigabe und Home-Assistant-Export.
// Nutzt Hilfsfunktionen aus app.js: $, api, toast, connection, escapeHtml, state, els.
(() => {
  const ORDERS = {1: ['AB', 'BA'], 2: ['ABCD', 'BADC', 'CDAB', 'DCBA'], 4: ['ABCDEFGH', 'BADCFEHG', 'GHEFCDAB', 'HGFEDCBA']};
  const WORDS = {uint16: 1, int16: 1, float16: 1, uint32: 2, int32: 2, float32: 2, uint64: 4, int64: 4, float64: 4};
  let writeEnabled = false;
  let writeTarget = null;   // {unit_id, function, address, name}

  // --- Schreib-Freigabe -----------------------------------------------------
  function applyWriteMode(status) {
    writeEnabled = Boolean(status?.enabled);
    document.body.classList.toggle('write-enabled', writeEnabled);
    const button = $('#writeModeBtn');
    if (!button) return;
    const minutes = Math.max(1, Math.ceil((status?.remaining_s || 0) / 60));
    button.textContent = writeEnabled ? `Schreiben aktiv · ${minutes} min` : 'Nur Lesen';
    button.className = `badge write-mode ${writeEnabled ? 'danger-badge' : 'safe'}`;
    button.title = writeEnabled
      ? 'Schreiben ist freigegeben und schaltet sich automatisch ab. Klicken, um sofort wieder auf «Nur Lesen» zu gehen.'
      : 'Schreiben ist gesperrt. Klicken, um Schreiben für 30 Minuten freizugeben.';
  }

  async function refreshWriteMode() {
    try { applyWriteMode(await (await fetch('/api/write-mode')).json()); } catch (_) { /* Anzeige bleibt */ }
  }

  $('#writeModeBtn')?.addEventListener('click', async () => {
    if (!writeEnabled && !window.confirm('Schreiben für 30 Minuten freigeben?\n\nGeschriebene Werte wirken sofort auf das Gerät und können eine Anlage beeinflussen. Jeder Schreibvorgang wird vorher angezeigt, muss bestätigt werden und wird zurückgelesen.')) return;
    try {
      const response = await fetch('/api/write-mode', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !writeEnabled})});
      applyWriteMode(await response.json());
      if (typeof renderMonitor === 'function') renderMonitor();
      toast(writeEnabled ? 'Schreiben für 30 Minuten freigegeben.' : 'Zurück auf «Nur Lesen».');
    } catch (error) { toast(error.message, true); }
  });

  // --- Schreib-Dialog -------------------------------------------------------
  function fillOrders(dataType, selected) {
    const select = $('#writeOrder');
    const orders = dataType === 'string' ? ['AB', 'BA'] : ORDERS[WORDS[dataType] || 1];
    select.innerHTML = orders.map(order => `<option${order === selected ? ' selected' : ''}>${order}</option>`).join('');
    $('#writeLengthLabel').classList.toggle('hidden', dataType !== 'string');
  }

  function writePayload() {
    const isCoil = Number(writeTarget.function) === 1;
    return {
      connection: connection(), unit_id: writeTarget.unit_id, function: writeTarget.function, address: writeTarget.address,
      data_type: isCoil ? 'bool' : $('#writeType').value, order: $('#writeOrder').value,
      scale: Number($('#writeScale').value) || 1, offset: Number($('#writeOffset').value) || 0,
      length: Number($('#writeLength').value) || 1, value: $('#writeValue').value.trim(), prefer_fc16: $('#writeFc16').checked,
    };
  }

  let previewTimer = null;
  async function updateWritePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const box = $('#writePreview');
      const payload = writePayload();
      if (payload.value === '') { box.className = 'result-box muted'; box.textContent = 'Vorschau erscheint nach der Eingabe.'; updateSendState(false); return; }
      try {
        const response = await fetch('/api/encode-preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
        box.className = 'result-box';
        box.innerHTML = `Sendet <strong>${data.function}</strong> an Register ${writeTarget.address}: <code>${escapeHtml(data.hex)}</code>`;
        updateSendState(true);
      } catch (error) {
        box.className = 'result-box error'; box.textContent = error.message; updateSendState(false);
      }
    }, 200);
  }

  function updateSendState(valid = !$('#writePreview').classList.contains('error') && $('#writeValue').value.trim() !== '') {
    $('#writeSendBtn').disabled = !(writeEnabled && valid && $('#writeConfirm').checked);
  }

  window.openWriteDialog = (point, currentValue) => {
    if (!writeEnabled) { toast('Schreiben ist gesperrt. Zuerst oben «Nur Lesen» anklicken und freigeben.', true); return; }
    writeTarget = {unit_id: Number(point.unit_id), function: Number(point.function), address: Number(point.address), name: point.name || ''};
    const isCoil = writeTarget.function === 1;
    $('#writeTarget').innerHTML = `<strong>${escapeHtml(writeTarget.name || `Register ${writeTarget.address}`)}</strong> · ${escapeHtml(connection().host)} · Unit-ID ${writeTarget.unit_id} · ${isCoil ? 'Coil' : 'Holding-Register'} ${writeTarget.address}${currentValue !== undefined ? ` · aktuell ${escapeHtml(String(currentValue))}` : ''}`;
    document.querySelectorAll('#writeForm .form-grid > label').forEach(label => label.classList.toggle('hidden', isCoil && !label.querySelector('#writeValue')));
    $('#writeType').value = point.data_type && point.data_type !== 'bool' ? point.data_type : 'uint16';
    fillOrders($('#writeType').value, point.order);
    $('#writeScale').value = point.scale ?? 1;
    $('#writeOffset').value = point.offset ?? 0;
    $('#writeLength').value = point.length || 8;
    $('#writeValue').value = '';
    $('#writeValue').placeholder = isCoil ? 'Ein / Aus (1 / 0)' : 'Wert in Anzeige-Einheit';
    $('#writeConfirm').checked = false;
    $('#writeResult').className = 'result-box hidden';
    $('#writePreview').className = 'result-box muted';
    $('#writePreview').textContent = 'Vorschau erscheint nach der Eingabe.';
    updateSendState(false);
    $('#writeDialog').showModal();
    setTimeout(() => $('#writeValue').focus(), 50);
  };

  $('#writeType')?.addEventListener('change', () => { fillOrders($('#writeType').value); updateWritePreview(); });
  ['#writeOrder', '#writeScale', '#writeOffset', '#writeLength', '#writeValue', '#writeFc16'].forEach(id => $(id)?.addEventListener('input', updateWritePreview));
  $('#writeConfirm')?.addEventListener('change', () => updateSendState());

  $('#writeSendBtn')?.addEventListener('click', async () => {
    const button = $('#writeSendBtn');
    const result = $('#writeResult');
    try {
      const data = await api('/api/write', {...writePayload(), confirmed: true}, button);
      result.className = `result-box ${data.verified === false ? 'error' : 'success'}`;
      result.innerHTML = data.verified === true
        ? `✓ ${data.function} geschrieben und zurückgelesen – Gerät hat den Wert übernommen.`
        : data.verified === false
          ? `⚠ ${data.function} gesendet, Rücklesen ergibt aber <code>${escapeHtml(JSON.stringify(data.readback))}</code> statt <code>${escapeHtml(JSON.stringify(data.registers))}</code>. Das Gerät hat den Wert evtl. begrenzt oder übernimmt ihn verzögert.`
          : `${data.function} gesendet und vom Gerät bestätigt; Rücklesen war nicht möglich.`;
      $('#writeConfirm').checked = false;
      updateSendState();
      if (state.polling && typeof pollNow === 'function') setTimeout(pollNow, 300);
    } catch (error) {
      result.className = 'result-box error'; result.textContent = error.message;
    }
  });

  $('#decoderWriteBtn')?.addEventListener('click', () => {
    const fn = Number($('#decoderFunction').value);
    if (![1, 3].includes(fn)) { toast('Schreiben ist nur für Coils (FC01) und Holding-Register (FC03) möglich.', true); return; }
    window.openWriteDialog({unit_id: $('#decoderUnit').value, function: fn, address: $('#decoderAddress').value, data_type: 'uint16', order: 'AB'});
  });

  // --- Verbindungsstatus ------------------------------------------------------
  function seconds(value) {
    if (value === null || value === undefined) return '–';
    return value < 120 ? `${value} s` : `${Math.round(value / 60)} min`;
  }

  async function refreshConnections() {
    const body = $('#connectionStatus2');
    if (!body) return;
    try {
      const data = await (await fetch('/api/connections')).json();
      const rows = data.connections || [];
      body.innerHTML = rows.length ? rows.map(row => `<tr>
          <td>${escapeHtml(row.connection)}</td>
          <td class="${row.open ? 'good' : row.retry_in_s ? 'bad' : ''}">${row.open ? `offen seit ${seconds(row.connected_for_s)}` : row.retry_in_s ? `getrennt · neuer Versuch in ${row.retry_in_s} s` : 'geschlossen (öffnet bei Bedarf)'}</td>
          <td>${row.requests}</td><td>${row.errors}</td><td>${row.reconnects}</td>
          <td>${escapeHtml(row.users.join(', ') || '–')}</td></tr>`).join('')
        : '<tr class="empty"><td colspan="6">Noch keine Verbindung aufgebaut.</td></tr>';
      const withError = rows.find(row => row.last_error && row.last_error_ago_s !== null && row.last_error_ago_s < 300);
      const alert = $('#connectionLastError');
      alert.classList.toggle('hidden', !withError);
      if (withError) alert.textContent = `${withError.connection}: ${withError.last_error} (vor ${seconds(withError.last_error_ago_s)})`;
    } catch (_) { /* Status ist nur Anzeige */ }
  }

  $('#connectionStatusBtn')?.addEventListener('click', refreshConnections);
  setInterval(() => {
    if (document.querySelector('#tab-connection.active')) refreshConnections();
    refreshWriteMode();
  }, 5000);

  // --- Home-Assistant-Export ----------------------------------------------------
  $('#haExportBtn')?.addEventListener('click', async () => {
    if (!state.points.length) { toast('Noch keine Datenpunkte für den Export vorhanden.', true); return; }
    try {
      const data = await api('/api/export/home-assistant', {
        points: state.points.map(({preview, ...point}) => point), connection: connection(), name: $('#profileName').value.trim(),
      }, $('#haExportBtn'));
      const blob = new Blob([data.yaml], {type: 'text/yaml;charset=utf-8'});
      const link = document.createElement('a');
      const base = ($('#profileName').value.trim() || `${els.host.value.trim()}-modbus`).replace(/[^a-z0-9äöü_-]+/gi, '-').replace(/^-|-$/g, '') || 'cko-modbus';
      link.href = URL.createObjectURL(blob); link.download = `${base}-home-assistant.yaml`; link.click(); URL.revokeObjectURL(link.href);
      toast(`${state.points.length} Datenpunkte als Home-Assistant-YAML exportiert.`);
    } catch (_) { /* api zeigt den Fehler */ }
  });

  refreshWriteMode();
  refreshConnections();
})();
