// Modbus RTU direkt über USB-RS485: COM-Ports, automatische Suche (Baudrate, Format, Unit-ID) und Zählerliste.
// Nutzt Hilfsfunktionen aus app.js: $, api, toast, connection, connectionLabel, escapeHtml, state, saveLocal, selectTab.
(() => {
  const QUICK_BAUDS = [9600, 19200, 38400];
  const FULL_BAUDS = [9600, 19200, 38400, 2400, 4800, 57600, 115200, 1200, 14400];
  const FORMATS = ['8N1', '8E1', '8O1', '8N2'];
  const IDS_PER_REQUEST = 8;
  let wantedPort = '';
  let searching = false;
  let stopRequested = false;

  // --- COM-Ports ---------------------------------------------------------------
  function portLabel(port) {
    const details = [port.description, port.chip && !String(port.description).includes(port.chip.split(' ')[0]) ? port.chip : ''].filter(Boolean).join(' · ');
    return details ? `${port.device} – ${details}` : port.device;
  }

  window.setSerialSelection = (device) => {
    wantedPort = device || wantedPort;
    const select = $('#serialPort');
    if (!select || !wantedPort) return;
    if (![...select.options].some(option => option.value === wantedPort)) {
      select.insertAdjacentHTML('beforeend', `<option value="${escapeHtml(wantedPort)}">${escapeHtml(wantedPort)} (nicht eingesteckt?)</option>`);
    }
    select.value = wantedPort;
  };

  let loading = null;
  window.loadSerialPorts = () => {
    if (loading) return loading;
    loading = (async () => {
      const select = $('#serialPort');
      const note = $('#serialPortNote');
      const previous = select.value || wantedPort;
      try {
        const data = await (await fetch('/api/serial-ports')).json();
        const ports = data.ports || [];
        select.innerHTML = ports.length
          ? ports.map(port => `<option value="${escapeHtml(port.device)}">${escapeHtml(portLabel(port))}</option>`).join('')
          : '<option value="">Kein COM-Port gefunden</option>';
        if (previous) window.setSerialSelection(previous);
        const usb = ports.filter(port => port.usb).length;
        note.textContent = data.hint || (usb
          ? `${usb} USB-Adapter gefunden. Unsicher, welcher es ist? Adapter abziehen, «Neu laden» – der verschwundene Eintrag ist der richtige.`
          : 'Kein USB-Adapter erkannt – angezeigt werden nur eingebaute Schnittstellen. Adapter einstecken und «Neu laden».');
        note.classList.toggle('important-note', !usb);
      } catch (error) {
        note.textContent = `Schnittstellen konnten nicht gelesen werden: ${error.message}`;
      } finally {
        loading = null;
      }
    })();
    return loading;
  };

  $('#serialRefreshBtn')?.addEventListener('click', () => window.loadSerialPorts().then(() => toast('Schnittstellenliste aktualisiert.')));
  $('#serialPort')?.addEventListener('change', () => { wantedPort = $('#serialPort').value; });

  // --- Automatische Suche ------------------------------------------------------
  function probeTimeoutMs(baud) {
    const frameMs = 20 * 11 * 1000 / baud;
    return Math.min(1500, Math.max(120, 100 + 2 * frameMs));
  }

  function plan() {
    const scope = $('#rtuScope').value;
    const bauds = scope === 'full' ? FULL_BAUDS : scope === 'current' ? [Number($('#baudrate').value)] : QUICK_BAUDS;
    const start = Number($('#rtuIdStart').value);
    const end = Number($('#rtuIdEnd').value);
    const combos = bauds.flatMap(baud => FORMATS.map(format => ({baud, format})));
    const ids = Math.max(0, end - start + 1);
    const seconds = combos.reduce((sum, combo) => sum + ids * (probeTimeoutMs(combo.baud) + 25) / 1000 + 0.15, 0);
    return {combos, start, end, ids, seconds};
  }

  function updateEstimate() {
    const {combos, ids, seconds} = plan();
    const box = $('#rtuEstimate');
    if (!box) return;
    if (ids < 1) { box.textContent = 'Bitte einen gültigen ID-Bereich (1–247) eingeben.'; return; }
    const duration = seconds < 90 ? `${Math.ceil(seconds)} s` : `${Math.ceil(seconds / 60)} min`;
    box.textContent = `${combos.length} Einstellungen × ${ids} Unit-IDs – höchstens ca. ${duration}, mit «Nach erstem Treffer stoppen» meist deutlich kürzer.`
      + (ids > 30 ? ' Tipp: Zähler haben ab Werk meist die Adresse 1 – ein kleiner Bereich ist viel schneller.' : '');
  }
  ['#rtuScope', '#rtuIdStart', '#rtuIdEnd', '#baudrate'].forEach(id => $(id)?.addEventListener('input', updateEstimate));
  ['#rtuScope', '#baudrate'].forEach(id => $(id)?.addEventListener('change', updateEstimate));

  function setProgress(done, total, text, hits, started) {
    const percent = total ? Math.round(done / total * 100) : 0;
    $('#rtuProgressBar').style.width = `${percent}%`;
    $('#rtuProgressPercent').textContent = `${percent} %`;
    $('#rtuProgressText').textContent = text;
    $('#rtuProgressHits').textContent = `${hits} ${hits === 1 ? 'Treffer' : 'Treffer'}`;
    $('#rtuProgressTime').textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`;
  }

  function renderResults(found) {
    const body = $('#rtuResults');
    body.innerHTML = found.length ? found.map((item, index) => `<tr>
        <td>${item.baud}</td><td>${item.format}</td><td><strong>${item.unit_id}</strong></td>
        <td class="${item.status === 'answer' ? 'good' : ''}">${escapeHtml(item.detail)}</td><td>${item.latency_ms} ms</td>
        <td><button class="table-action" type="button" data-rtu-apply="${index}">Übernehmen</button></td></tr>`).join('')
      : '<tr class="empty"><td colspan="6">Keine Antwort gefunden.</td></tr>';
    body.querySelectorAll('[data-rtu-apply]').forEach(button => button.addEventListener('click', () => apply(found[Number(button.dataset.rtuApply)])));
  }

  function apply(hit, quiet = false) {
    $('#baudrate').value = String(hit.baud);
    $('#dataFormat').value = hit.format;
    ['#unitStart', '#unitEnd'].forEach(id => { if ($(id)) $(id).value = hit.unit_id; });
    ['#finderUnit', '#decoderUnit'].forEach(id => { if ($(id)) $(id).value = hit.unit_id; });
    saveLocal();
    if (!quiet) toast(`Übernommen: ${hit.baud} Baud ${hit.format}, Unit-ID ${hit.unit_id}.`);
  }

  function summary(type, html) {
    const box = $('#rtuSummary');
    box.className = `alert ${type}`;
    box.innerHTML = html;
  }

  async function search() {
    if (searching) return;
    const port = $('#serialPort').value;
    if (!port) { toast('Zuerst den COM-Port des USB-RS485-Adapters wählen.', true); return; }
    const {combos, start, end, ids} = plan();
    if (ids < 1 || start < 1 || end > 247) { toast('Bitte einen gültigen ID-Bereich (1–247) eingeben.', true); return; }
    const stopFirst = $('#rtuStopFirst').checked;
    const total = combos.length * ids;
    const found = [];
    const started = performance.now();
    let done = 0;
    let error = null;
    searching = true; stopRequested = false;
    $('#rtuSearchBtn').disabled = true; $('#rtuCancelBtn').disabled = false;
    $('#rtuProgress').classList.remove('hidden', 'complete', 'cancelled');
    $('#rtuSummary').className = 'hidden';
    renderResults([]); $('#rtuResults').innerHTML = '<tr class="empty"><td colspan="6">Suche läuft …</td></tr>';
    setActivity(`RTU-Suche auf ${port} läuft …`, 'busy');
    const timer = setInterval(() => { $('#rtuProgressTime').textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`; }, 250);
    try {
      for (let index = 0; index < combos.length && !stopRequested; index += 1) {
        const {baud, format} = combos[index];
        $('#rtuProgressCombos').textContent = `Einstellung ${index + 1} von ${combos.length}`;
        for (let first = start; first <= end && !stopRequested; first += IDS_PER_REQUEST) {
          const last = Math.min(end, first + IDS_PER_REQUEST - 1);
          setProgress(done, total, `${baud} Baud ${format} · Unit-ID ${first}–${last}`, found.length, started);
          const response = await fetch('/api/rtu-probe', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({connection: {serial_port: port, baudrate: baud, data_format: format},
              start_id: first, end_id: last, function: Number($('#rtuFunction').value), address: 0}),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
          data.found.forEach(item => found.push({...item, baud, format}));
          done += last - first + 1;
          if (data.found.length) renderResults(found);
        }
        if (stopFirst && found.length) break;
      }
    } catch (failure) {
      error = failure;
    } finally {
      clearInterval(timer);
      searching = false;
      $('#rtuSearchBtn').disabled = false; $('#rtuCancelBtn').disabled = true;
      const finalText = stopRequested ? 'Durch den Benutzer abgebrochen' : error ? 'Mit Fehler beendet'
        : found.length ? `Zähler gefunden bei ${found[0].baud} Baud ${found[0].format}` : `${done} Abfragen ohne Antwort`;
      setProgress(found.length && stopFirst ? total : done, total, finalText, found.length, started);
      $('#rtuProgress').classList.add(stopRequested ? 'cancelled' : 'complete');
      $('#rtuProgressTitle').textContent = stopRequested ? 'Suche abgebrochen' : 'Suche beendet';
    }
    renderResults(found);
    if (error) {
      summary('error', escapeHtml(error.message));
      setActivity(error.message, 'error');
      toast(error.message, true);
      return;
    }
    if (found.length) {
      apply(found[0], true);
      const ids = [...new Set(found.filter(item => item.baud === found[0].baud && item.format === found[0].format).map(item => item.unit_id))];
      summary('success', `<b>Gefunden: ${found[0].baud} Baud, ${found[0].format}, Unit-ID ${ids.join(', ')}</b> – automatisch übernommen.
        Weiter mit <button type="button" class="link-button" data-rtu-next="products">Gerät im Nachschlagewerk wählen</button> oder
        <button type="button" class="link-button" data-rtu-next="decoder">Register lesen (Schritt 06)</button>.
        Diese Einstellungen später auch im Gateway eintragen.`);
      setActivity(`RTU-Suche: ${found.length} Treffer.`);
    } else if (!stopRequested) {
      summary('warning', `<b>Keine Antwort.</b> Häufigste Ursachen: <b>A und B vertauscht</b> (einfach tauschen und erneut suchen),
        ein zweiter Master am Bus (Gateway abklemmen), Adresse ausserhalb des Bereichs ${start}–${end}, falscher COM-Port
        oder fehlender Abschluss. <button type="button" class="link-button" data-rtu-guide="7">Fehlersuche in der Anleitung →</button>`);
      setActivity('RTU-Suche: keine Antwort.', 'error');
    }
  }

  $('#rtuSearchBtn')?.addEventListener('click', search);
  $('#rtuCancelBtn')?.addEventListener('click', () => { stopRequested = true; $('#rtuProgressText').textContent = 'Wird nach der laufenden Abfrage beendet …'; });
  $('#rtuSummary')?.addEventListener('click', event => {
    const next = event.target.closest('[data-rtu-next]');
    if (next) selectTab(next.dataset.rtuNext);
    const guide = event.target.closest('[data-rtu-guide]');
    if (guide) window.openHelp?.(Number(guide.dataset.rtuGuide), 'rtu');
  });
  $('#rtuGuideBtn')?.addEventListener('click', () => window.openHelp?.(0, 'rtu'));
  updateEstimate();

  // --- Zählerliste -------------------------------------------------------------
  let meterList = null;

  function lastValues() {
    return Object.fromEntries(state.points.map(point => {
      const history = state.histories[point.id] || [];
      return [point.id, history.length ? history[history.length - 1] : null];
    }));
  }

  function fileBase() {
    return ($('#profileName').value.trim() || `${connection().host}-zaehler`).replace(/[^a-z0-9äöü_-]+/gi, '-').replace(/^-|-$/g, '') || 'cko-zaehlerliste';
  }

  function valueText(row) {
    if (row.value === null || row.value === undefined) return '–';
    return `${formatNumber(row.value)} ${escapeHtml(row.unit || '')}`;
  }

  $('#meterListBtn')?.addEventListener('click', async () => {
    if (!state.points.length) { toast('Noch keine Datenpunkte für die Zählerliste vorhanden.', true); return; }
    try {
      meterList = await api('/api/export/meter-list', {
        points: state.points.map(({preview, ...point}) => point), connection: connection(), values: lastValues(),
      }, $('#meterListBtn'));
    } catch (_) { return; }
    const noValues = meterList.rows.every(row => row.value === null || row.value === undefined);
    const box = $('#meterListSummary');
    box.className = `alert ${meterList.warnings ? 'warning' : noValues ? 'info' : 'success'}`;
    box.innerHTML = meterList.warnings
      ? `<b>${meterList.warnings} ${meterList.warnings === 1 ? 'Datenpunkt' : 'Datenpunkte'} mit Hinweis</b> – Faktor, Datentyp oder Anschluss prüfen, bevor die Werte ins Gateway übernommen werden.`
      : noValues ? 'Noch keine Live-Werte: Live-Monitor kurz starten, dann prüft die Liste auch die Plausibilität der Werte.'
        : '<b>Alle Werte plausibel.</b> Die Liste kann als Vorlage für Gateway und Visualisierung dienen.';
    $('#meterListRows').innerHTML = meterList.rows.map(row => `<tr>
        <td><strong>${escapeHtml(row.name)}</strong></td><td>${escapeHtml(row.unit_id)}</td>
        <td>${escapeHtml(row.function)} · ${escapeHtml(row.address)}</td><td>${escapeHtml(row.data_type)} ${escapeHtml(row.order)}</td>
        <td>${escapeHtml(String(row.scale).replace('.', ','))}</td><td>${valueText(row)}</td>
        <td title="${escapeHtml([row.dpt_label, row.dpt_note].filter(Boolean).join(' – '))}"><strong>${escapeHtml(row.dpt)}</strong><br><small class="muted">${escapeHtml(row.dpt_label)}</small></td>
        <td>${row.hints.length ? `<small class="plausibility-hint">⚠ ${escapeHtml(row.hints.join(' '))}</small>` : '<span class="good">✓</span>'}</td></tr>`).join('');
    $('#meterListDialog').showModal();
  });

  const closeMeterList = () => $('#meterListDialog').close();
  $('#meterListCloseBtn')?.addEventListener('click', closeMeterList);
  $('#meterListCloseBtn2')?.addEventListener('click', closeMeterList);

  $('#meterListCsvBtn')?.addEventListener('click', () => {
    if (!meterList) return;
    const blob = new Blob([meterList.csv], {type: 'text/csv;charset=utf-8'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob); link.download = `${fileBase()}-zaehlerliste.csv`; link.click(); URL.revokeObjectURL(link.href);
    toast('Zählerliste als CSV gespeichert.');
  });

  $('#meterListPrintBtn')?.addEventListener('click', () => {
    if (!meterList) return;
    const win = window.open('', '_blank');
    if (!win) { toast('Das Druckfenster wurde vom Browser blockiert.', true); return; }
    const meta = [
      ['Gerät / Profil', $('#profileName').value.trim()], ['Hersteller / Modell', [$('#profileManufacturer').value.trim(), $('#profileModel').value.trim()].filter(Boolean).join(' ')],
      ['Projekt / Anlage', $('#profileProject').value.trim()], ['Verbindung', meterList.rows[0]?.connection || connectionLabel()],
      ['Erstellt', new Intl.DateTimeFormat('de-CH', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date())],
    ].filter(([, value]) => value);
    win.document.write(`<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Zählerliste ${escapeHtml(fileBase())}</title>
      <style>
        body{font:12px/1.4 "Segoe UI",Arial,sans-serif;color:#111;margin:24px}
        h1{font-size:20px;margin:0 0 4px} .sub{color:#555;margin:0 0 14px}
        dl{display:grid;grid-template-columns:150px 1fr;gap:3px 12px;margin:0 0 16px} dt{color:#555} dd{margin:0;font-weight:600}
        table{width:100%;border-collapse:collapse} th,td{border:1px solid #bbb;padding:5px 6px;text-align:left;vertical-align:top}
        th{background:#eef2f7;font-size:11px} td small{color:#555} .warn{color:#9a5b00} .ok{color:#147a3d}
        .ga{width:90px} footer{margin-top:14px;color:#666;font-size:10px}
        @page{size:A4 landscape;margin:12mm} @media print{body{margin:0}}
      </style></head><body>
      <h1>Zählerliste</h1><p class="sub">Modbus-Datenpunkte mit KNX-DPT-Vorschlag – erstellt mit dem CKO Modbus Inspector ${escapeHtml(window.HB_APP_VERSION || '')}</p>
      <dl>${meta.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join('')}</dl>
      <table><thead><tr><th>Bezeichnung</th><th>Unit-ID</th><th>FC</th><th>Register</th><th>Datentyp</th><th>Faktor</th><th>Einheit</th><th>Letzter Wert</th><th>KNX-DPT (Vorschlag)</th><th>Prüfung</th><th class="ga">Gruppenadresse</th><th>Raum / Verbraucher</th></tr></thead><tbody>
      ${meterList.rows.map(row => `<tr><td><b>${escapeHtml(row.name)}</b></td><td>${escapeHtml(row.unit_id)}</td><td>${escapeHtml(row.function)}</td><td>${escapeHtml(row.address)}</td>
        <td>${escapeHtml(row.data_type)} ${escapeHtml(row.order)}</td><td>${escapeHtml(String(row.scale).replace('.', ','))}</td><td>${escapeHtml(row.unit || '')}</td>
        <td>${row.value === null || row.value === undefined ? '–' : escapeHtml(formatNumber(row.value))}</td>
        <td><b>${escapeHtml(row.dpt)}</b><br><small>${escapeHtml(row.dpt_label)}${row.dpt_note ? ` – ${escapeHtml(row.dpt_note)}` : ''}</small></td>
        <td>${row.hints.length ? `<span class="warn">⚠ ${escapeHtml(row.hints.join(' '))}</span>` : row.value === null || row.value === undefined ? '' : '<span class="ok">✓ plausibel</span>'}</td><td></td><td></td></tr>`).join('')}
      </tbody></table>
      <footer>DPT-Angaben sind Vorschläge nach Einheit und Messgrösse; massgebend sind Gateway und Visualisierung. Register vor Übernahme mit dem Live-Wert am Zähler vergleichen.</footer>
      </body></html>`);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 300);
  });
})();
