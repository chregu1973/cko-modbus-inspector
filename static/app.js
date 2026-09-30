const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  connected: false,
  lastRead: null,
  pendingPoint: null,
  points: [],
  histories: {},
  pollTimer: null,
  pollAbortController: null,
  polling: false,
  registerScan: null,
  registerBaseline: null,
  registerScanning: false,
  registerStopRequested: false,
  registerProgressTimer: null,
  databaseProfileId: null,
  profileLibrary: [],
};

const els = {
  host: $('#host'), port: $('#port'), timeout: $('#timeout'), transport: $('#transport'),
  status: $('#connectionStatus'), activityDot: $('#activityDot'), activityText: $('#activityText'),
  toast: $('#toast'), pointCount: $('#pointCount'),
};

function connection() {
  return { host: els.host.value.trim(), port: Number(els.port.value), timeout_ms: Number(els.timeout.value), transport: els.transport.value };
}

function setActivity(text, type = 'ok') {
  els.activityText.textContent = text;
  els.activityDot.className = `activity-dot ${type === 'ok' ? '' : type}`;
}

function toast(message, error = false) {
  els.toast.textContent = message;
  els.toast.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => els.toast.className = 'toast', 3200);
}

async function api(path, body, button) {
  if (button) button.disabled = true;
  setActivity(`${button?.textContent.trim() || 'Abfrage'} läuft …`, 'busy');
  try {
    const response = await fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    setActivity('Abfrage erfolgreich abgeschlossen.');
    return data;
  } catch (error) {
    setActivity(error.message, 'error');
    toast(error.message, true);
    throw error;
  } finally {
    if (button) button.disabled = false;
  }
}

function selectTab(tab) {
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.tab === tab));
  $$('.tab-page').forEach(page => page.classList.toggle('active', page.id === `tab-${tab}`));
}

$('#navTabs').addEventListener('click', event => {
  const button = event.target.closest('.nav-item');
  if (button) selectTab(button.dataset.tab);
});

function updateActiveProduct(metadata = null) {
  const name = metadata?.name || $('#profileName').value.trim();
  const stateLabel = $('#databaseProfileState');
  if (state.databaseProfileId) {
    stateLabel.textContent = `Bibliotheksprofil geladen · ${metadata?.updated_at ? `zuletzt ${formatDateTime(metadata.updated_at)}` : 'Änderungen können gespeichert werden'}`;
    $('#saveProfileBtn').textContent = 'Änderungen speichern';
    $('#saveAsProfileBtn').classList.remove('hidden');
  } else {
    stateLabel.textContent = name ? 'Noch nicht in der Profilbibliothek gespeichert.' : 'Zuerst Produkt-/Profilname eintragen.';
    $('#saveProfileBtn').textContent = 'In Profilbibliothek speichern';
    $('#saveAsProfileBtn').classList.add('hidden');
  }
}

async function profileLibraryRequest(path, options = {}, button = null) {
  if (button) button.disabled = true;
  try {
    const response = await fetch(path, {
      method: options.method || 'GET',
      headers: options.body ? {'Content-Type': 'application/json'} : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  } finally {
    if (button) button.disabled = false;
  }
}

async function refreshProfileLibrary(query = $('#productSearch').value.trim()) {
  const status = $('#productSearchStatus');
  status.textContent = 'Profilbibliothek wird durchsucht …';
  try {
    const data = await profileLibraryRequest(`/api/profile-library?q=${encodeURIComponent(query)}`);
    state.profileLibrary = data.profiles;
    renderProductResults(data.profiles, query);
  } catch (error) {
    status.textContent = `Profilbibliothek nicht verfügbar: ${error.message}`;
    $('#productResults').innerHTML = '';
  }
}

function renderProductResults(profiles, query = '') {
  $('#profileLibraryCount').textContent = `${profiles.length} ${profiles.length === 1 ? 'Profil' : 'Profile'}`;
  const status = $('#productSearchStatus');
  const container = $('#productResults');
  container.innerHTML = '';
  if (!profiles.length) {
    status.textContent = query
      ? `Kein Profil zu „${query}“ gefunden. Du kannst das Gerät neu anlegen.`
      : 'Noch keine Geräteprofile gespeichert. Beginne mit dem ersten Gerät.';
    const empty = document.createElement('div');
    empty.className = 'product-empty';
    empty.innerHTML = '<strong>Kein passendes Profil vorhanden</strong><span>Beim Abschluss kannst du die geprüften Register für spätere Projekte speichern.</span>';
    container.appendChild(empty);
    return;
  }
  status.textContent = query ? `${profiles.length} passende Profile gefunden.` : 'Zuletzt verwendete Geräteprofile.';
  profiles.forEach(profile => {
    const card = document.createElement('article');
    card.className = 'product-result';
    const identity = [profile.manufacturer, profile.model].filter(Boolean).join(' · ') || 'Hersteller/Modell noch offen';
    const project = profile.project || 'Kein Projekt hinterlegt';
    card.innerHTML = `
      <div class="product-result-main">
        <span class="eyebrow">${escapeHtml(identity)}</span>
        <strong>${escapeHtml(profile.name)}</strong>
        <span>${escapeHtml(project)} · ${profile.point_count} ${profile.point_count === 1 ? 'Datenpunkt' : 'Datenpunkte'} · ${formatDateTime(profile.updated_at)}</span>
      </div>
      <div class="product-result-actions">
        <button class="secondary product-open">Profil öffnen</button>
        <button class="primary product-use">Für neues Projekt verwenden</button>
        <button class="delete-button product-delete" title="Profil löschen">×</button>
      </div>`;
    card.querySelector('.product-open').addEventListener('click', () => loadDatabaseProfile(profile.id, false));
    card.querySelector('.product-use').addEventListener('click', () => loadDatabaseProfile(profile.id, true));
    card.querySelector('.product-delete').addEventListener('click', () => deleteDatabaseProfile(profile));
    container.appendChild(card);
  });
}

async function loadDatabaseProfile(profileId, asTemplate) {
  try {
    const data = await profileLibraryRequest(`/api/profile-library/${encodeURIComponent(profileId)}`);
    applyProfile(data.payload, false);
    if (asTemplate) {
      state.databaseProfileId = null;
      $('#profileProject').value = '';
      updateActiveProduct();
      saveLocal();
      selectTab('network');
      toast('Gerätewissen geladen. Projekt, IP-Adresse und Unit-/Slave-ID jetzt prüfen.');
    } else {
      state.databaseProfileId = profileId;
      updateActiveProduct(data.metadata);
      saveLocal();
      selectTab('monitor');
      toast(`${data.metadata.point_count} Datenpunkte aus der Profilbibliothek geladen.`);
    }
  } catch (error) {
    toast(error.message, true);
  }
}

async function deleteDatabaseProfile(profile) {
  if (!window.confirm(`Geräteprofil „${profile.name}“ aus der lokalen Bibliothek löschen?`)) return;
  try {
    await profileLibraryRequest(`/api/profile-library/${encodeURIComponent(profile.id)}`, {method:'DELETE'});
    if (state.databaseProfileId === profile.id) {
      state.databaseProfileId = null;
      updateActiveProduct();
    }
    await refreshProfileLibrary();
    toast('Geräteprofil wurde aus der Bibliothek gelöscht.');
  } catch (error) {
    toast(error.message, true);
  }
}

let profileSearchTimer = null;
$('#productSearch').addEventListener('input', () => {
  clearTimeout(profileSearchTimer);
  profileSearchTimer = setTimeout(() => refreshProfileLibrary(), 180);
});

$('#newProductBtn').addEventListener('click', () => {
  $('#newProductCard').classList.remove('hidden');
  const query = $('#productSearch').value.trim();
  if (query && !$('#newProductName').value) $('#newProductName').value = query;
  $('#newProductName').focus();
});

$('#cancelNewProductBtn').addEventListener('click', () => $('#newProductCard').classList.add('hidden'));

$('#beginNewProductBtn').addEventListener('click', () => {
  const name = $('#newProductName').value.trim();
  if (!name) { toast('Bitte zuerst Produkt- oder Profilname eingeben.', true); $('#newProductName').focus(); return; }
  if (state.points.length && !window.confirm('Aktuell geladene Datenpunkte verwerfen und ein neues Geräteprofil beginnen?')) return;
  state.databaseProfileId = null;
  state.points = [];
  state.histories = {};
  $('#profileName').value = name;
  $('#profileManufacturer').value = $('#newProductManufacturer').value.trim();
  $('#profileModel').value = $('#newProductModel').value.trim();
  $('#profileProject').value = $('#newProductProject').value.trim();
  $('#profileFirmware').value = $('#newProductFirmware').value.trim();
  $('#profileNotes').value = '';
  $('#newProductCard').classList.add('hidden');
  updateActiveProduct();
  renderMonitor();
  saveLocal();
  selectTab('network');
  toast('Neues Geräteprofil begonnen. Als Nächstes das Netzwerk prüfen.');
});

$('#clearLog').addEventListener('click', () => setActivity('Lokaler Connector bereit.'));

$('#shutdownBtn').addEventListener('click', async () => {
  if (!window.confirm('CKO Modbus Inspector vollständig beenden?\n\nDer Live-Monitor und der lokale Server werden gestoppt.')) return;
  const button = $('#shutdownBtn');
  stopPolling();
  button.disabled = true;
  button.textContent = 'Wird beendet …';
  setActivity('Lokaler Server wird beendet …', 'busy');
  try {
    const response = await fetch('/api/shutdown', {method: 'POST'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    els.status.className = 'status offline';
    els.status.innerHTML = '<i></i>Server beendet';
    setActivity('Server beendet. Dieses Browserfenster kann geschlossen werden.');
    toast('Server beendet. Das Browserfenster kann geschlossen werden.');
    setTimeout(() => window.close(), 650);
  } catch (error) {
    button.disabled = false;
    button.innerHTML = '<span>⏻</span><strong>Tool beenden</strong>';
    setActivity(error.message, 'error');
    toast(`Beenden fehlgeschlagen: ${error.message}`, true);
  }
});

function transportLabel(value = els.transport.value) {
  return value === 'rtu_tcp' ? 'Modbus RTU über TCP' : 'Modbus TCP';
}

function updateTransportHint() {
  const isTransparent = els.transport.value === 'rtu_tcp';
  $('#transportTitle').textContent = transportLabel();
  $('#transportWarning').classList.toggle('hidden', !isTransparent);
  if (isTransparent && Number(els.timeout.value) < 1200) els.timeout.value = 1500;
}

els.transport.addEventListener('change', () => { updateTransportHint(); saveLocal(); });

function markConnected(host, port, latency, transport) {
  state.connected = true;
  els.status.className = 'status online';
  els.status.innerHTML = '<i></i>Verbunden';
  $('#connectResult').className = 'result-box success';
  $('#connectResult').textContent = `${host}:${port} per TCP erreichbar · ${latency} ms · ${transportLabel(transport)}. Eine Modbus-Antwort wird im nächsten Schritt geprüft.`;
  $('#toUnitsBtn').classList.remove('hidden');
}

$('#toUnitsBtn').addEventListener('click', () => selectTab('units'));

$('#connectBtn').addEventListener('click', async () => {
  const button = $('#connectBtn');
  try {
    const data = await api('/api/connect', { connection: connection() }, button);
    markConnected(data.host, data.port, data.latency_ms, data.transport);
  } catch (_) {
    state.connected = false;
    els.status.className = 'status offline';
    els.status.innerHTML = '<i></i>Nicht verbunden';
    $('#connectResult').className = 'result-box error';
    $('#connectResult').textContent = 'Ziel nicht erreichbar. IP, Port, Netzwerk und Firewall prüfen.';
    $('#toUnitsBtn').classList.add('hidden');
  }
});

async function loadInterfaces() {
  try {
    const data = await api('/api/interfaces');
    const container = $('#interfaces');
    container.innerHTML = '';
    if (!data.interfaces.length) {
      container.innerHTML = '<div class="result-box muted">Keine IPv4-Netzwerkadapter erkannt.</div>';
      return;
    }
    data.interfaces.forEach(item => {
      const row = document.createElement('div');
      row.className = 'interface-item';
      row.innerHTML = `<div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.address)} · ${escapeHtml(item.cidr)}</small></div><button>Übernehmen →</button>`;
      row.querySelector('button').addEventListener('click', () => {
        $('#cidr').value = item.cidr;
        selectTab('network');
      });
      container.appendChild(row);
    });
  } catch (_) {
    $('#interfaces').innerHTML = '<div class="result-box error">Adapter konnten nicht gelesen werden.</div>';
  }
}

$('#networkScanBtn').addEventListener('click', async () => {
  const button = $('#networkScanBtn');
  try {
    const data = await api('/api/network-scan', {
      cidr: $('#cidr').value.trim(), port: Number($('#scanPort').value), timeout_ms: Number($('#scanTimeout').value),
      verify_modbus: $('#scanVerifyModbus').checked, resolve_names: $('#scanResolveNames').checked,
    }, button);
    const summary = $('#networkSummary');
    summary.classList.remove('hidden');
    const confirmedPart = data.verify_modbus ? `<span><strong>${data.modbus_confirmed}</strong> Modbus bestätigt</span>` : '';
    summary.innerHTML = `<span><strong>${data.scanned}</strong> Adressen geprüft</span><span><strong>${data.devices.length}</strong> Treffer</span>${confirmedPart}<span><strong>${data.duration_ms} ms</strong> Laufzeit</span>`;
    const tbody = $('#networkResults');
    tbody.innerHTML = data.devices.length ? '' : '<tr class="empty"><td colspan="7">Kein offener Modbus-Port gefunden.</td></tr>';
    data.devices.forEach(device => {
      const row = document.createElement('tr');
      let statusClass = 'good';
      let statusText = 'TCP erreichbar';
      let statusTitle = '';
      if (device.modbus_verified === true && device.modbus_transport === 'rtu_tcp') { statusText = 'Modbus RTU über TCP bestätigt'; statusTitle = 'Transparentes RS485-Gateway: «Verwenden» stellt die Übertragungsart auf RTU über TCP.'; }
      else if (device.modbus_verified === true) { statusText = 'Modbus TCP bestätigt'; }
      else if (device.modbus_verified === false) { statusClass = 'bad'; statusText = 'Port offen, keine Modbus-Antwort'; statusTitle = 'Weder Modbus TCP noch RTU über TCP hat auf Unit-ID 1 geantwortet. Unter «Verbindung» manuell prüfen und im Schritt Unit-/Slave-IDs andere IDs testen.'; }
      const hostname = device.hostname ? escapeHtml(device.hostname) : '<span class="muted">–</span>';
      const macVendor = device.mac
        ? `${escapeHtml(device.mac)}${device.vendor ? ` <span class="muted">(${escapeHtml(device.vendor)})</span>` : ''}`
        : '<span class="muted">–</span>';
      row.innerHTML = `<td>${escapeHtml(device.host)}</td><td>${device.port}</td><td>${device.latency_ms} ms</td><td class="${statusClass}" title="${escapeHtml(statusTitle)}">${statusText}</td><td>${hostname}</td><td>${macVendor}</td><td><button class="table-action">Verwenden</button></td>`;
      row.querySelector('button').addEventListener('click', () => {
        els.host.value = device.host; els.port.value = device.port; $('#scanPort').value = device.port;
        if (device.modbus_transport) { els.transport.value = device.modbus_transport; updateTransportHint(); }
        selectTab('connection'); $('#connectBtn').click();
      });
      tbody.appendChild(row);
    });
  } catch (_) {}
});

$('#unitScanBtn').addEventListener('click', async () => {
  const button = $('#unitScanBtn');
  try {
    const data = await api('/api/unit-scan', {
      connection: connection(), start_id: Number($('#unitStart').value), end_id: Number($('#unitEnd').value),
      function: Number($('#unitFunction').value), address: Number($('#unitAddress').value),
    }, button);
    const summary = $('#unitSummary');
    summary.classList.remove('hidden');
    summary.innerHTML = `<span><strong>${data.scanned}</strong> Unit-/Slave-IDs geprüft</span><span><strong>${data.found.length}</strong> Modbus-Antworten</span><span><strong>${data.duration_ms} ms</strong> Laufzeit</span>`;
    const warning = $('#unitWarning');
    warning.classList.toggle('hidden', !data.warning); warning.textContent = data.warning || '';
    const tbody = $('#unitResults');
    const attempts = data.attempts || data.found;
    tbody.innerHTML = attempts.length ? '' : '<tr class="empty"><td colspan="4">Keine Unit-/Slave-ID geprüft.</td></tr>';
    attempts.forEach(item => {
      const row = document.createElement('tr');
      const responded = ['answer', 'exception'].includes(item.status);
      const className = item.status === 'answer' ? 'good' : (responded ? '' : 'bad');
      const latency = item.latency_ms == null ? '–' : `${item.latency_ms} ms`;
      row.innerHTML = `<td><strong>${item.unit_id}</strong></td><td class="${className}">${escapeHtml(item.detail)}</td><td>${latency}</td><td>${responded ? '<button class="table-action">Register suchen</button>' : ''}</td>`;
      const finderButton = row.querySelector('button');
      if (finderButton) finderButton.addEventListener('click', () => {
          $('#finderUnit').value = item.unit_id;
          const functionValue = $('#unitFunction').value;
          $('#finderFunction').value = ['3', '4'].includes(functionValue) ? functionValue : '0';
          selectTab('finder');
        });
      tbody.appendChild(row);
    });
    setActivity(`${data.scanned} Unit-/Slave-IDs geprüft, ${data.found.length} Modbus-Antworten in ${data.duration_ms} ms.`);
  } catch (_) {}
});

$('#registerScanBtn').addEventListener('click', runRegisterScan);

$('#cancelRegisterScanBtn').addEventListener('click', () => {
  if (!state.registerScanning) return;
  state.registerStopRequested = true;
  $('#cancelRegisterScanBtn').disabled = true;
  $('#finderProgressTitle').textContent = 'Abbruch angefordert';
  $('#finderProgressText').textContent = 'Der aktuelle Teilbereich wird noch sauber abgeschlossen …';
});

function updateRegisterProgress({percent, rangeText, checked, totalQueries, hits, elapsed, status = 'running'}) {
  const progress = $('#finderProgress');
  progress.classList.remove('hidden', 'complete', 'cancelled');
  if (status === 'complete') progress.classList.add('complete');
  if (status === 'cancelled') progress.classList.add('cancelled');
  $('#finderProgressBar').style.width = `${Math.max(0, Math.min(100, percent))}%`;
  $('#finderProgressPercent').textContent = `${Math.round(percent)} %`;
  $('#finderProgressQueries').textContent = `${checked} / ${totalQueries} Abfragen`;
  $('#finderProgressHits').textContent = `${hits} Antworten`;
  $('#finderProgressTime').textContent = `${(elapsed / 1000).toFixed(1)} s`;
  $('#finderProgressText').textContent = rangeText;
}

async function fetchRegisterChunk(body) {
  const response = await fetch('/api/register-scan', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function runRegisterScan() {
  if (state.registerScanning) return;
  const unitId = Number($('#finderUnit').value);
  const selectedFunction = Number($('#finderFunction').value);
  const startAddress = Number($('#finderStart').value);
  const endAddress = Number($('#finderEnd').value);
  const delayMs = Number($('#finderDelay').value);
  const addressCount = endAddress - startAddress + 1;
  if (!Number.isInteger(startAddress) || !Number.isInteger(endAddress) || startAddress < 0 || endAddress > 65535 || endAddress < startAddress) {
    toast('Bitte einen gültigen Registerbereich eingeben.', true); return;
  }
  if (addressCount > 512) { toast('Pro Suche sind höchstens 512 Adressen erlaubt.', true); return; }

  const functionCount = selectedFunction === 0 ? 2 : 1;
  const totalQueries = addressCount * functionCount;
  const chunkSize = 16;
  const started = performance.now();
  const aggregate = {
    ok: true, unit_id: unitId, functions: selectedFunction === 0 ? [3, 4] : [selectedFunction],
    start_address: startAddress, end_address: endAddress, checked: 0, requests: 0, found: [], unsupported: 0,
    block_retry_count: 0, block_hits: 0, blocks: [],
    errors: [], aborted: false, warning: null, duration_ms: 0, timestamp: Date.now() / 1000,
  };
  state.registerScanning = true;
  state.registerStopRequested = false;
  $('#registerScanBtn').disabled = true;
  $('#cancelRegisterScanBtn').disabled = false;
  $('#finderWarning').classList.add('hidden');
  setActivity(`Registerscan Unit/Slave ${unitId} läuft …`, 'busy');
  updateRegisterProgress({percent: 0, rangeText: `Bereich ${startAddress}–${endAddress} wird vorbereitet …`, checked: 0, totalQueries, hits: 0, elapsed: 0});
  state.registerProgressTimer = setInterval(() => {
    $('#finderProgressTime').textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`;
  }, 250);

  let cancelled = false;
  try {
    for (let chunkStart = startAddress; chunkStart <= endAddress; chunkStart += chunkSize) {
      const chunkEnd = Math.min(endAddress, chunkStart + chunkSize - 1);
      $('#finderProgressTitle').textContent = 'Registerscan läuft';
      $('#finderProgressText').textContent = `Prüfe Adressen ${chunkStart}–${chunkEnd} · Unit/Slave ${unitId}`;
      const part = await fetchRegisterChunk({
        connection: connection(), unit_id: unitId, function: selectedFunction,
        start_address: chunkStart, end_address: chunkEnd, capture_end_address: endAddress, delay_ms: delayMs,
      });
      aggregate.checked += part.checked;
      aggregate.requests += part.requests ?? part.checked;
      const foundByAddress = new Map(aggregate.found.map(item => [finderKey(item), item]));
      part.found.forEach(item => foundByAddress.set(finderKey(item), item));
      aggregate.found = [...foundByAddress.values()].sort((a, b) => a.function - b.function || a.address - b.address);
      aggregate.unsupported += part.unsupported;
      aggregate.block_retry_count += part.block_retry_count || 0;
      aggregate.block_hits += part.block_hits || 0;
      const blockKeys = new Set(aggregate.blocks.map(item => `${item.function}:${item.start}:${item.count}`));
      (part.blocks || []).forEach(item => {
        const key = `${item.function}:${item.start}:${item.count}`;
        if (!blockKeys.has(key)) { aggregate.blocks.push(item); blockKeys.add(key); }
      });
      aggregate.errors.push(...part.errors);
      if (part.aborted) {
        aggregate.aborted = true;
        aggregate.warning = part.warning;
      }
      const elapsed = performance.now() - started;
      updateRegisterProgress({
        percent: (aggregate.checked / totalQueries) * 100,
        rangeText: `Zuletzt geprüft: ${chunkStart}–${chunkEnd} · Unit/Slave ${unitId}`,
        checked: aggregate.checked, totalQueries, hits: aggregate.found.length, elapsed,
      });
      if (part.aborted) break;
      if (state.registerStopRequested) {
        cancelled = true;
        aggregate.aborted = true;
        aggregate.warning = 'Der Registerscan wurde durch den Benutzer abgebrochen. Bereits gefundene Register bleiben sichtbar.';
        break;
      }
    }
  } catch (error) {
    aggregate.aborted = true;
    aggregate.warning = error.message;
    toast(error.message, true);
    setActivity(error.message, 'error');
  } finally {
    aggregate.duration_ms = Math.round(performance.now() - started);
    if (!aggregate.warning && !aggregate.found.length) aggregate.warning = 'Im gewählten Bereich antwortet kein Register. Einen anderen Bereich oder FC03/FC04 versuchen.';
    if (!aggregate.warning && aggregate.block_hits) {
      aggregate.warning = `${aggregate.block_hits} ${aggregate.block_hits === 1 ? 'Mehrregister-Block wurde' : 'Mehrregister-Blöcke wurden'} nur als gemeinsame Abfrage erkannt. Blockstart und Abfragegrösse sind gekennzeichnet.`;
    }
    state.registerScan = aggregate;
    state.registerScanning = false;
    state.registerStopRequested = false;
    clearInterval(state.registerProgressTimer);
    state.registerProgressTimer = null;
    $('#registerScanBtn').disabled = false;
    $('#cancelRegisterScanBtn').disabled = true;
    $('#saveSnapshotBtn').disabled = !aggregate.found.length;
    const percent = totalQueries ? (aggregate.checked / totalQueries) * 100 : 0;
    $('#finderProgressTitle').textContent = cancelled ? 'Registerscan abgebrochen' : (aggregate.aborted ? 'Registerscan vorzeitig beendet' : 'Registerscan abgeschlossen');
    updateRegisterProgress({
      percent: aggregate.aborted ? percent : 100,
      rangeText: cancelled ? 'Teilresultate wurden übernommen.' : `${aggregate.found.length} gültige Register gefunden.`,
      checked: aggregate.checked, totalQueries, hits: aggregate.found.length, elapsed: aggregate.duration_ms,
      status: aggregate.aborted ? 'cancelled' : 'complete',
    });
    const warning = $('#finderWarning');
    warning.classList.toggle('hidden', !aggregate.warning); warning.textContent = aggregate.warning || '';
    renderRegisterFinder();
    if (!aggregate.aborted) setActivity(`${aggregate.checked} Adressprüfungen mit ${aggregate.requests} Modbus-Abfragen abgeschlossen, ${aggregate.found.length} Register gefunden.`);
    else if (cancelled) setActivity(`Registerscan abgebrochen · ${aggregate.found.length} Teiltreffer.`);
    else if (!aggregate.warning?.includes('HTTP')) setActivity(aggregate.warning || 'Registerscan vorzeitig beendet.', 'error');
  }
}

function finderKey(item) {
  return `${item.function}:${item.address}`;
}

function baselineMap() {
  return new Map((state.registerBaseline?.found || []).map(item => [finderKey(item), item]));
}

function renderRegisterFinder() {
  const data = state.registerScan;
  if (!data) return;
  const baseline = baselineMap();
  const hasBaseline = Boolean(state.registerBaseline);
  const hideZero = $('#finderHideZero').checked;
  const hideFFFF = $('#finderHideFFFF').checked;
  const changedOnly = $('#finderChangedOnly').checked && hasBaseline;
  let changedCount = 0;
  const placeholderCount = data.found.filter(item => item.value === 0xFFFF).length;
  const candidateCount = data.found.length - placeholderCount;
  const rows = data.found.map(item => {
    const beforeItem = baseline.get(finderKey(item));
    const before = beforeItem?.value;
    const delta = before == null ? null : item.value - before;
    const changed = delta !== null && delta !== 0;
    if (changed) changedCount += 1;
    return {...item, before, delta, changed};
  }).filter(item => {
    const zeroMayBelongToPair = item.value === 0 && data.found.some(neighbour =>
      neighbour.function === item.function &&
      Math.abs(neighbour.address - item.address) === 1 &&
      neighbour.value !== 0 && neighbour.value !== 0xFFFF
    );
    return (!hideZero || item.value !== 0 || zeroMayBelongToPair) &&
      (!hideFFFF || item.value !== 0xFFFF) &&
      (!changedOnly || item.changed);
  });

  const summary = $('#finderSummary');
  summary.classList.remove('hidden');
  summary.innerHTML = `<span><strong>${data.checked}</strong> Adressen/FC geprüft</span><span><strong>${data.requests ?? data.checked}</strong> Modbus-Abfragen</span><span><strong>${data.found.length}</strong> Register gefunden</span><span><strong>${candidateCount}</strong> Kandidaten</span><span><strong>${placeholderCount}</strong> FFFF-Platzhalter</span><span><strong>${data.unsupported}</strong> ungültige Adressen</span>${data.block_hits ? `<span><strong>${data.block_hits}</strong> Mehrregister-Blöcke</span>` : ''}${hasBaseline ? `<span><strong>${changedCount}</strong> Änderungen</span>` : ''}<span><strong>${data.duration_ms} ms</strong> Laufzeit</span>`;
  const tbody = $('#finderResults');
  tbody.innerHTML = rows.length ? '' : `<tr class="empty"><td colspan="7">${data.found.length ? 'Keine Register entsprechen dem aktuellen Filter.' : 'Keine gültigen Register im gewählten Bereich gefunden.'}</td></tr>`;
  rows.forEach(item => {
    const row = document.createElement('tr');
    if (item.changed) row.className = 'changed-row';
    if (item.value === 0xFFFF) row.classList.add('placeholder-row');
    const blockNote = Number(item.read_count) > 1
      ? (item.address === item.block_start
        ? `<small class="block-read-note">Blockstart · ${item.read_count} Register</small>`
        : `<small class="block-read-note">aus Block ${item.block_start} · ${item.read_count} Reg.</small>`)
      : '';
    const beforeText = item.before == null ? '–' : `${item.before} · 0x${item.before.toString(16).toUpperCase().padStart(4, '0')}`;
    const deltaText = item.delta == null ? '–' : (item.delta === 0 ? 'unverändert' : `${item.delta > 0 ? '+' : ''}${item.delta}`);
    const valueText = item.value === 0xFFFF ? `${item.value}<small class="placeholder-note">wahrscheinlich unbenutzt</small>` : item.value;
    row.innerHTML = `<td>FC${String(item.function).padStart(2, '0')}</td><td><strong>${item.address}</strong>${blockNote}</td><td><code>${item.hex}</code></td><td>${valueText}</td><td>${beforeText}</td><td class="${item.changed ? 'good' : 'muted'}">${deltaText}</td><td><button class="table-action">Decoder</button></td>`;
    row.querySelector('button').addEventListener('click', () => {
      $('#decoderUnit').value = data.unit_id;
      $('#decoderFunction').value = item.function;
      $('#decoderAddress').value = Number(item.read_count) > 1 ? item.block_start : item.address;
      $('#decoderCount').value = Number(item.read_count) > 1 ? item.read_count : Math.min(4, 65536 - item.address);
      selectTab('decoder');
    });
    tbody.appendChild(row);
  });
}

$('#saveSnapshotBtn').addEventListener('click', () => {
  if (!state.registerScan?.found?.length) return;
  state.registerBaseline = JSON.parse(JSON.stringify(state.registerScan));
  $('#finderChangedOnly').disabled = false;
  $('#clearSnapshotBtn').disabled = false;
  renderRegisterFinder();
  toast(`${state.registerBaseline.found.length} Register als Referenz gespeichert.`);
});

$('#clearSnapshotBtn').addEventListener('click', () => {
  state.registerBaseline = null;
  $('#finderChangedOnly').checked = false;
  $('#finderChangedOnly').disabled = true;
  $('#clearSnapshotBtn').disabled = true;
  renderRegisterFinder();
  toast('Referenz wurde gelöscht.');
});

['finderHideZero', 'finderHideFFFF', 'finderChangedOnly'].forEach(id => document.getElementById(id).addEventListener('change', renderRegisterFinder));

$('#decoderFunction').addEventListener('change', () => {
  const bits = ['1', '2'].includes($('#decoderFunction').value);
  $('#decoderCount').max = bits ? 2000 : 125;
  if (bits && Number($('#decoderCount').value) < 8) $('#decoderCount').value = 8;
});

$('#readBtn').addEventListener('click', () => readDecoder());

async function readDecoder() {
  const button = $('#readBtn');
  try {
    const request = {
      connection: connection(), unit_id: Number($('#decoderUnit').value), function: Number($('#decoderFunction').value),
      address: Number($('#decoderAddress').value), count: Number($('#decoderCount').value),
    };
    const data = await api('/api/read', request, button);
    if (data.notice) {
      // Gerät hat nur einen Teil des Blocks angenommen: Anzahl übernehmen, damit Monitor und Suche denselben Block lesen
      request.count = data.count;
      $('#decoderCount').value = data.count;
      toast(`${data.notice} Die Anzahl wurde auf ${data.count} gesetzt.`);
    }
    state.lastRead = { request, data };
    renderDecoding(data);
    $('#findMatchesBtn').disabled = Boolean(data.decoding.bits);
    $('#matchSummary').classList.add('hidden');
    $('#matchWarning').classList.add('hidden');
    $('#matchRecommendation').classList.add('hidden');
    $('#matchTable').classList.add('hidden');
  } catch (_) {}
}

async function jumpDecoder(address) {
  const bounded = Math.max(0, Math.min(65535, Number(address)));
  $('#decoderAddress').value = bounded;
  const maxCount = ['1', '2'].includes($('#decoderFunction').value) ? 2000 : 125;
  $('#decoderCount').value = Math.min(Number($('#decoderCount').value), maxCount, 65536 - bounded);
  await readDecoder();
}

$('#decoderPrevBtn').addEventListener('click', () => jumpDecoder(Number($('#decoderAddress').value) - 1));
$('#decoderNextBtn').addEventListener('click', () => jumpDecoder(Number($('#decoderAddress').value) + 1));

function renderDecoding(data) {
  $('#decoderEmpty').classList.add('hidden');
  $('#decoderOutput').classList.remove('hidden');
  $('#readTimestamp').textContent = new Date(data.timestamp * 1000).toLocaleTimeString('de-CH');
  const raw = $('#rawValues'); raw.innerHTML = '';
  const groups = $('#decodeGroups'); groups.innerHTML = '';
  $('#decoderPrevBtn').disabled = data.address <= 0;
  $('#decoderNextBtn').disabled = data.address >= 65535;
  if (data.decoding.bits) {
    data.decoding.bits.forEach((value, index) => {
      const code = document.createElement('button');
      code.type = 'button'; code.className = `raw-register${index === 0 ? ' active' : ''}`;
      code.textContent = `${data.address + index}: ${value ? 'TRUE' : 'FALSE'}`;
      code.title = `Decoder bei ${data.address + index} starten`;
      code.addEventListener('click', () => jumpDecoder(data.address + index));
      raw.appendChild(code);
    });
    const card = document.createElement('article'); card.className = 'card glass decode-card';
    card.innerHTML = '<h3>Bit-Werte <span>Boolean</span></h3>';
    data.decoding.bits.forEach((value, index) => {
      const row = document.createElement('div'); row.className = 'decode-row';
      row.innerHTML = `<strong>BOOL</strong><span class="order">Bit</span><span class="value">${value ? 'TRUE' : 'FALSE'}</span><button>+ Monitor</button>`;
      row.querySelector('button').addEventListener('click', () => preparePoint({type:'Bool', data_type:'bool', order:null, value}, data.address + index));
      card.appendChild(row);
    });
    groups.appendChild(card);
    return;
  }
  data.decoding.raw_hex.forEach((value, index) => {
    const code = document.createElement('button');
    code.type = 'button'; code.className = `raw-register${index === 0 ? ' active' : ''}`;
    code.textContent = `${data.address + index}: ${value}`;
    code.title = `Decoder bei ${data.address + index} starten`;
    code.addEventListener('click', () => jumpDecoder(data.address + index));
    raw.appendChild(code);
  });
  data.decoding.groups.forEach(group => {
    const card = document.createElement('article'); card.className = 'card glass decode-card';
    card.innerHTML = `<h3>${escapeHtml(group.label)} <span>${group.count} Register</span></h3>`;
    group.rows.forEach(item => {
      const row = document.createElement('div'); row.className = 'decode-row';
      row.innerHTML = `<strong>${escapeHtml(item.type)}</strong><span class="order">${escapeHtml(item.order)}</span><span class="value" title="${escapeHtml(String(item.value))}">${formatNumber(item.value)}</span><button>+ Monitor</button>`;
      row.querySelector('button').addEventListener('click', () => preparePoint(item, data.address));
      card.appendChild(row);
    });
    groups.appendChild(card);
  });
}

const matchPresets = {
  free: {name: '', unit: ''},
  energy: {name: 'Energie / Zählerstand', unit: 'kWh'},
  power: {name: 'Leistung', unit: 'kW'},
  voltage: {name: 'Spannung', unit: 'V'},
  current: {name: 'Strom', unit: 'A'},
  frequency: {name: 'Frequenz', unit: 'Hz'},
  temperature: {name: 'Temperatur', unit: '°C'},
  percent: {name: 'Stellwert', unit: '%'},
};

$('#matchKind').addEventListener('change', () => {
  const preset = matchPresets[$('#matchKind').value] || matchPresets.free;
  if (preset.name) $('#matchName').value = preset.name;
  if (preset.unit) $('#matchUnit').value = preset.unit;
});

$('#findMatchesBtn').addEventListener('click', findBestMatches);

async function findBestMatches() {
  if (!state.lastRead || state.lastRead.data.decoding.bits) {
    toast('Zuerst einen Registerbereich mit FC03 oder FC04 lesen.', true); return;
  }
  const expected = Number($('#matchExpected').value);
  if (!Number.isFinite(expected) || $('#matchExpected').value.trim() === '') {
    toast('Bitte den ungefähr erwarteten Wert eingeben.', true); $('#matchExpected').focus(); return;
  }
  const customFactorText = $('#matchCustomFactor').value.trim();
  const customFactor = customFactorText === '' ? null : Number(customFactorText);
  if (customFactorText !== '' && (!Number.isFinite(customFactor) || customFactor === 0)) {
    toast('Der optionale Zusatzfaktor muss eine Zahl ungleich 0 sein.', true); $('#matchCustomFactor').focus(); return;
  }
  const button = $('#findMatchesBtn');
  try {
    const data = await api('/api/match-values', {
      registers: state.lastRead.data.values,
      start_address: state.lastRead.data.address,
      expected_value: expected,
      tolerance_percent: Number($('#matchTolerance').value),
      type_mode: $('#matchType').value,
      quantity_kind: $('#matchKind').value,
      custom_factor: customFactor,
      limit: 5,
    }, button);
    renderValueMatches(data);
  } catch (_) {}
}

function renderValueMatches(data) {
  const unit = $('#matchUnit').value.trim();
  const name = $('#matchName').value.trim() || $('#matchKind option:checked').textContent;
  const summary = $('#matchSummary');
  summary.classList.remove('hidden');
  summary.innerHTML = `<span><strong>${data.checked_registers}</strong> Rohregister geprüft</span><span><strong>${data.candidate_count}</strong> Interpretationen fachlich bewertet</span><span><strong>${data.unique_candidate_count}</strong> eindeutige Kandidaten</span><span><strong>${data.within_tolerance}</strong> innerhalb ${formatNumber(data.tolerance_percent)} %</span>${data.ambiguous_candidates ? `<span><strong>${data.ambiguous_candidates}</strong> mit 16/32-Bit-Mehrdeutigkeit</span>` : ''}`;
  const warning = $('#matchWarning');
  warning.classList.remove('hidden');
  warning.textContent = data.recommendation?.width_ambiguous
    ? 'Der gleiche Zahlenwert ist sowohl als 16-Bit-Teilregister als auch als vollständiger 32-Bit-Wert möglich. Das Tool bevorzugt den vollständigen 32-Bit-Datenpunkt, stuft ihn aber bewusst nur als „mittel“ ein. Registerbreite mit Dokumentation oder Live-Verlauf bestätigen.'
    : data.recommendation?.polarity_mismatch
    ? 'Der beste Treffer passt zum Betrag, hat aber das entgegengesetzte Vorzeichen. Das ist bei Bezug und Lieferung häufig nur die Energieflussrichtung. Den negativen Rohwert unverändert übernehmen und die Bedeutung am Gerät prüfen.'
    : data.recommendation
    ? 'Die Empfehlung berücksichtigt Messgrösse, Datentyp, Registerbreite, Reihenfolge, Skalierung und Zahlenabstand. Vor der endgültigen Übernahme mit Live-Verlauf oder einer gezielten Anlagenänderung verifizieren.'
    : 'Kein Treffer liegt innerhalb der Toleranz. Bereich, Erwartungswert, Datentyp oder Einheit prüfen.';

  renderMatchRecommendation(data.recommendation, {name, unit});
  const table = $('#matchTable'); table.classList.remove('hidden');
  const tbody = $('#matchResults'); tbody.innerHTML = '';
  data.matches.forEach((item, index) => {
    const row = document.createElement('tr');
    if (item.within_tolerance) row.className = 'match-good';
    const equivalents = item.equivalent_interpretations?.length
      ? `<small class="muted match-equivalents">gleichwertig: ${escapeHtml(item.equivalent_interpretations.join(', '))}</small>` : '';
    const reason = item.reasons?.[1] || item.reasons?.[0] || '';
    const polarity = item.polarity_mismatch ? '<small class="polarity-note">Betrag passend · Vorzeichen umgekehrt</small>' : '';
    const ambiguity = item.width_ambiguous ? '<small class="ambiguity-note">16/32 Bit mehrdeutig</small>' : '';
    row.innerHTML = `<td class="match-rank">${index + 1}</td><td><strong>${item.address}</strong><br><small class="muted">${item.register_count} Reg.</small></td><td><strong>${escapeHtml(item.visu_type)}</strong> · <code>${escapeHtml(item.order)}</code><small class="muted match-detail">Rohwert ${formatNumber(item.raw_value)}</small>${equivalents}${ambiguity}</td><td>${formatFactor(item.factor)}</td><td class="${item.within_tolerance ? 'good' : ''}">${formatNumber(item.value)}${unit ? ` ${escapeHtml(unit)}` : ''}${polarity}</td><td>${formatNumber(item.deviation_percent)} %</td><td><span class="confidence confidence-${item.confidence_label}">${escapeHtml(item.confidence_label)} · ${formatNumber(item.confidence)} %</span><small class="muted match-detail">${escapeHtml(reason)}</small></td><td><div class="match-actions"><button class="table-action show-match">Anzeigen</button><button class="table-action monitor-match">+ Monitor</button></div></td>`;
    row.querySelector('.show-match').addEventListener('click', () => showMatchInLoadedBlock(item));
    row.querySelector('.monitor-match').addEventListener('click', () => preparePoint({
      type: item.type, data_type: item.data_type, order: item.order, value: item.raw_value,
    }, item.address, {name, unit, scale: item.factor}));
    tbody.appendChild(row);
  });
}

function renderMatchRecommendation(item, defaults) {
  const container = $('#matchRecommendation');
  if (!item) {
    container.classList.add('hidden');
    container.innerHTML = '';
    return;
  }
  const request = state.lastRead.request;
  const unit = defaults.unit.trim();
  const name = defaults.name.trim() || 'Datenpunkt';
  const functionLabel = `FC${String(request.function).padStart(2, '0')}`;
  const valueText = `${formatNumber(item.value)}${unit ? ` ${escapeHtml(unit)}` : ''}`;
  const polarityBadge = item.polarity_mismatch ? '<span class="polarity-badge">Vorzeichen prüfen</span>' : '';
  const ambiguityBadge = item.width_ambiguous ? '<span class="ambiguity-badge">16/32 Bit prüfen</span>' : '';
  container.classList.remove('hidden');
  container.classList.toggle('ambiguous', Boolean(item.width_ambiguous));
  container.innerHTML = `
    <div class="recommendation-head">
      <div><span class="eyebrow">${item.width_ambiguous ? 'EMPFOHLENER KANDIDAT · BREITE PRÜFEN' : 'EMPFOHLENER VISU-DATENPUNKT'}</span><h4>${escapeHtml(name)}</h4><p>${escapeHtml(item.reasons.join(' · '))}</p></div>
      <div class="recommendation-badges">${ambiguityBadge}${polarityBadge}<span class="confidence confidence-${item.confidence_label}">${escapeHtml(item.confidence_label)} · ${formatNumber(item.confidence)} %</span></div>
    </div>
    <div class="recommendation-grid">
      <div><small>Unit-ID (Slave-ID)</small><strong>${request.unit_id}</strong></div>
      <div><small>Funktion</small><strong>${functionLabel}</strong></div>
      <div><small>Register</small><strong>${item.address}</strong><span>${item.register_count} Register</span></div>
      <div><small>Datentyp</small><strong>${escapeHtml(item.visu_type)}</strong><span>${escapeHtml(item.order)}</span></div>
      <div><small>Faktor</small><strong>${formatFactor(item.factor)}</strong></div>
      <div><small>Aktueller Wert</small><strong class="good">${valueText}</strong></div>
    </div>
    <div class="recommendation-actions">
      <button class="secondary recommendation-show">Im Decoder anzeigen</button>
      <button class="secondary recommendation-copy">Konfiguration kopieren</button>
      <button class="primary recommendation-monitor">In den Live-Monitor übernehmen</button>
    </div>`;
  container.querySelector('.recommendation-show').addEventListener('click', () => showMatchInLoadedBlock(item));
  container.querySelector('.recommendation-monitor').addEventListener('click', () => preparePoint({
    type: item.type, data_type: item.data_type, order: item.order, value: item.raw_value,
  }, item.address, {name, unit, scale: item.factor}));
  container.querySelector('.recommendation-copy').addEventListener('click', async () => {
    const blockInfo = Number(request.count) > Number(item.register_count)
      ? `; Abfrageblock ${request.address}/${request.count}; Wert-Offset ${item.address - request.address}` : '';
    const config = `${name}; Unit-ID (Slave-ID) ${request.unit_id}; ${functionLabel}; Register ${item.address}; ${item.visu_type}; ${item.order}; Faktor ${plainNumber(item.factor)}; ${unit || 'ohne Einheit'}${blockInfo}`;
    try {
      await copyText(config);
      toast('Visu-Konfiguration wurde kopiert.');
    } catch (_) {
      toast('Konfiguration konnte nicht kopiert werden.', true);
    }
  });
}

function showMatchInLoadedBlock(item) {
  const data = state.lastRead?.data;
  const index = data ? Number(item.address) - Number(data.address) : -1;
  const rawButtons = $$('#rawValues .raw-register');
  if (index >= 0 && index < rawButtons.length) {
    rawButtons.forEach(button => button.classList.remove('active'));
    rawButtons[index].classList.add('active');
    rawButtons[index].scrollIntoView({behavior: 'smooth', block: 'nearest', inline: 'center'});
    toast(`Register ${item.address} ist im bereits gelesenen Block markiert.`);
    return;
  }
  jumpDecoder(item.address);
}

function preparePoint(item, address, defaults = {}) {
  const req = state.lastRead.request;
  const logicalCount = registerCount({function: req.function, data_type: item.data_type});
  const requestStart = Number(req.address);
  const requestCount = Number(req.count);
  const valueOffset = Number(address) - requestStart;
  const usesReadBlock = [3, 4].includes(Number(req.function))
    && requestCount > logicalCount
    && valueOffset >= 0
    && valueOffset + logicalCount <= requestCount;
  state.pendingPoint = {
    id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    name: defaults.name || '', unit: defaults.unit || '', scale: defaults.scale ?? 1, offset: 0,
    unit_id: req.unit_id, function: req.function, address,
    data_type: item.data_type, order: item.order, preview: item.value,
    read_start: usesReadBlock ? requestStart : Number(address),
    read_count: usesReadBlock ? requestCount : logicalCount,
    value_offset: usesReadBlock ? valueOffset : 0,
  };
  $('#pointName').value = state.pendingPoint.name;
  $('#pointUnit').value = state.pendingPoint.unit;
  $('#pointScale').value = String(state.pendingPoint.scale);
  $('#pointOffset').value = '0';
  const strategy = $('#pointReadStrategy');
  strategy.classList.toggle('hidden', !usesReadBlock);
  strategy.textContent = usesReadBlock
    ? `Kompatible Geräteabfrage: Block ${requestStart}–${requestStart + requestCount - 1} (${requestCount} Register), Wert ab Offset ${valueOffset}. Diese Lesestrategie wird im Profil gespeichert.`
    : '';
  updatePointPreview();
  $('#pointDialog').showModal();
  setTimeout(() => $('#pointName').focus(), 50);
}

function updatePointPreview() {
  if (!state.pendingPoint) return;
  const raw = state.pendingPoint.preview;
  const scale = Number($('#pointScale').value);
  const offset = Number($('#pointOffset').value);
  const unit = $('#pointUnit').value.trim();
  if (typeof raw !== 'number' || !Number.isFinite(raw) || !Number.isFinite(scale) || !Number.isFinite(offset)) {
    $('#pointPreview').value = 'Ungültige Eingabe';
    return;
  }
  const value = raw * scale + offset;
  $('#pointPreview').value = `${formatNumber(value)}${unit ? ` ${unit}` : ''}`;
}

['pointScale', 'pointOffset', 'pointUnit'].forEach(id => document.getElementById(id).addEventListener('input', updatePointPreview));

function cancelPointDialog() {
  state.pendingPoint = null;
  if ($('#pointDialog').open) $('#pointDialog').close('cancel');
}

$('#closePointDialogBtn').addEventListener('click', event => { event.preventDefault(); cancelPointDialog(); });
$('#cancelPointBtn').addEventListener('click', event => { event.preventDefault(); cancelPointDialog(); });
$('#pointDialog').addEventListener('cancel', event => { event.preventDefault(); cancelPointDialog(); });
$('#pointDialog').addEventListener('click', event => {
  if (event.target === $('#pointDialog')) cancelPointDialog();
});

$('#savePointBtn').addEventListener('click', event => {
  event.preventDefault();
  const name = $('#pointName').value.trim();
  if (!name) { toast('Bitte eine Bezeichnung eingeben.', true); return; }
  Object.assign(state.pendingPoint, {
    name, unit: $('#pointUnit').value.trim(), scale: Number($('#pointScale').value), offset: Number($('#pointOffset').value),
  });
  state.points.push(state.pendingPoint);
  state.histories[state.pendingPoint.id] = [];
  state.pendingPoint = null;
  $('#pointDialog').close();
  saveLocal(); renderMonitor(); selectTab('monitor'); toast('Datenpunkt wurde übernommen.');
});

function renderMonitor(values = {}) {
  els.pointCount.textContent = state.points.length;
  const tbody = $('#monitorResults');
  if (!state.points.length) {
    tbody.innerHTML = '<tr class="empty"><td colspan="6">Noch keine Datenpunkte. Im Decoder eine Interpretation mit „+ Monitor“ übernehmen.</td></tr>';
    return;
  }
  tbody.innerHTML = '';
  state.points.forEach(point => {
    const result = values[point.id];
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><strong>${escapeHtml(point.name)}</strong><br><small class="muted">Unit/Slave ${point.unit_id} · FC0${point.function}</small></td>
      <td>${point.address}</td>
      <td>${escapeHtml(point.data_type.toUpperCase())} · ${escapeHtml(point.order || 'BIT')}<br><small class="muted">Faktor ${point.scale} · Offset ${point.offset}</small>${Number(point.read_count || registerCount(point)) > registerCount(point) ? `<small class="block-read-note">liest Block ${point.read_start}–${Number(point.read_start) + Number(point.read_count) - 1} · Wert-Offset ${point.value_offset}</small>` : ''}</td>
      <td class="live-value">${result ? (result.ok ? `${formatNumber(result.value)} ${escapeHtml(point.unit)}` : 'FEHLER') : '–'}</td>
      <td>${sparkline(state.histories[point.id] || [])}</td>
      <td><button class="delete-button" title="Datenpunkt entfernen">×</button></td>`;
    row.querySelector('.delete-button').addEventListener('click', () => {
      state.points = state.points.filter(item => item.id !== point.id); delete state.histories[point.id]; saveLocal(); renderMonitor();
    });
    tbody.appendChild(row);
  });
}

function sparkline(values) {
  const numeric = values.filter(value => typeof value === 'number' && Number.isFinite(value));
  if (numeric.length < 2) return '<span class="muted">–</span>';
  const min = Math.min(...numeric), max = Math.max(...numeric), range = max - min || 1;
  const points = numeric.map((value, index) => `${(index / (numeric.length - 1)) * 108 + 1},${28 - ((value - min) / range) * 25}`).join(' ');
  return `<svg class="sparkline" viewBox="0 0 110 30" preserveAspectRatio="none"><polyline points="${points}"/></svg>`;
}

$('#pollBtn').addEventListener('click', () => state.polling ? stopPolling() : startPolling());

function startPolling() {
  if (!state.points.length) { toast('Noch keine Monitorpunkte vorhanden.', true); return; }
  state.polling = true; $('#pollBtn').textContent = 'Sofort stoppen'; $('#monitorState').textContent = 'Monitor läuft';
  pollNow();
}

function stopPolling() {
  state.polling = false; clearTimeout(state.pollTimer); state.pollTimer = null;
  if (state.pollAbortController) {
    state.pollAbortController.abort();
    state.pollAbortController = null;
  }
  $('#pollBtn').textContent = 'Starten'; $('#monitorState').textContent = 'Monitor gestoppt';
  setActivity('Live-Monitor gestoppt.');
}

async function pollNow() {
  if (!state.polling) return;
  const controller = new AbortController();
  state.pollAbortController = controller;
  setActivity('Live-Abfrage läuft …', 'busy');
  try {
    const response = await fetch('/api/poll', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({connection: connection(), points: state.points}), signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    if (!state.polling) return;
    const values = Object.fromEntries(data.points.map(item => [item.id, item]));
    data.points.forEach(item => {
      if (item.ok && typeof item.value === 'number' && Number.isFinite(item.value)) {
        const history = state.histories[item.id] ||= []; history.push(item.value); if (history.length > 60) history.shift();
      }
    });
    renderMonitor(values);
    $('#lastPoll').textContent = `Letzte Abfrage ${new Date(data.timestamp * 1000).toLocaleTimeString('de-CH')}`;
    setActivity('Live-Abfrage erfolgreich abgeschlossen.');
  } catch (error) {
    if (error.name !== 'AbortError') {
      setActivity(error.message, 'error');
      toast(error.message, true);
    }
  } finally {
    if (state.pollAbortController === controller) state.pollAbortController = null;
  }
  if (state.polling) state.pollTimer = setTimeout(pollNow, Number($('#pollInterval').value));
}

function profileData() {
  return {
    schema: 'hbtec-modbus-profile', schema_version: 1, app_version: window.HB_APP_VERSION,
    exported_at: new Date().toISOString(),
    profile: {
      name: $('#profileName').value.trim(), project: $('#profileProject').value.trim(),
      manufacturer: $('#profileManufacturer').value.trim(), model: $('#profileModel').value.trim(),
      firmware: $('#profileFirmware').value.trim(), notes: $('#profileNotes').value.trim(),
    },
    connection: connection(), points: state.points.map(({preview, ...point}) => point),
  };
}

function saveLocal() {
  const data = profileData(); delete data.exported_at;
  data.local_database_profile_id = state.databaseProfileId;
  localStorage.setItem('hbtec-modbus-inspector-profile', JSON.stringify(data));
}

function restoreLocal() {
  try {
    const data = JSON.parse(localStorage.getItem('hbtec-modbus-inspector-profile'));
    if (data?.schema === 'hbtec-modbus-profile') {
      const profileId = data.local_database_profile_id || null;
      applyProfile(data, false);
      state.databaseProfileId = profileId;
      updateActiveProduct();
    }
  } catch (_) {}
}

function applyProfile(data, notify = true) {
  if (data?.schema !== 'hbtec-modbus-profile' || data.schema_version !== 1 || !Array.isArray(data.points)) throw new Error('Kein gültiges CKO-Modbusprofil.');
  const profile = data.profile || {};
  state.databaseProfileId = null;
  $('#profileName').value = profile.name || ''; $('#profileProject').value = profile.project || '';
  $('#profileManufacturer').value = profile.manufacturer || ''; $('#profileModel').value = profile.model || '';
  $('#profileFirmware').value = profile.firmware || ''; $('#profileNotes').value = profile.notes || '';
  if (data.connection) { els.host.value = data.connection.host || els.host.value; els.port.value = data.connection.port || 502; els.timeout.value = data.connection.timeout_ms || 800; els.transport.value = data.connection.transport || 'tcp'; updateTransportHint(); }
  state.points = data.points; state.histories = Object.fromEntries(state.points.map(point => [point.id, []]));
  saveLocal(); renderMonitor(); updateActiveProduct(); if (notify) toast(`${state.points.length} Datenpunkte importiert.`);
}

['profileName','profileProject','profileManufacturer','profileModel','profileFirmware','profileNotes','host','port','timeout'].forEach(id => document.getElementById(id).addEventListener('change', () => { saveLocal(); updateActiveProduct(); }));

async function saveCurrentProfile(asNew = false) {
  const name = $('#profileName').value.trim();
  if (!name) { toast('Bitte Produkt-/Profilname eintragen.', true); $('#profileName').focus(); return; }
  const button = asNew ? $('#saveAsProfileBtn') : $('#saveProfileBtn');
  try {
    const data = await profileLibraryRequest('/api/profile-library', {
      method: 'POST', body: {profile: profileData(), id: asNew ? null : state.databaseProfileId},
    }, button);
    state.databaseProfileId = data.profile.id;
    updateActiveProduct(data.profile);
    saveLocal();
    await refreshProfileLibrary();
    toast(`„${data.profile.name}“ mit ${data.profile.point_count} Datenpunkten gespeichert.`);
  } catch (error) {
    toast(error.message, true);
  }
}

$('#saveProfileBtn').addEventListener('click', () => saveCurrentProfile(false));
$('#saveAsProfileBtn').addEventListener('click', () => saveCurrentProfile(true));

const AI_PROVIDER_LABELS = {anthropic: 'Anthropic', gemini: 'Google Gemini'};

function applyAiSettingsData(data) {
  $('#aiProviderSelect').value = data.provider;
  $('#aiLookupProviderBadge').textContent = `Anbieter: ${AI_PROVIDER_LABELS[data.provider] || data.provider}`;
  const anthropic = data.providers.anthropic;
  const gemini = data.providers.gemini;
  $('#aiApiKeyStatus').textContent = anthropic.has_api_key
    ? `Anthropic: Schlüssel hinterlegt (${anthropic.api_key_masked}).`
    : 'Anthropic: noch kein Schlüssel hinterlegt.';
  $('#geminiApiKeyStatus').textContent = gemini.has_api_key
    ? `Gemini: Schlüssel hinterlegt (${gemini.api_key_masked}).`
    : 'Gemini: noch kein Schlüssel hinterlegt.';
}

async function loadAiSettings() {
  try {
    const data = await profileLibraryRequest('/api/ai-settings');
    applyAiSettingsData(data);
  } catch (_) {
    $('#aiApiKeyStatus').textContent = 'KI-Einstellungen konnten nicht geladen werden.';
    $('#geminiApiKeyStatus').textContent = '';
  }
}

$('#aiSettingsBtn').addEventListener('click', () => {
  $('#aiApiKeyInput').value = '';
  $('#geminiApiKeyInput').value = '';
  loadAiSettings();
  $('#aiSettingsDialog').showModal();
});
$('#closeAiSettingsDialogBtn').addEventListener('click', event => { event.preventDefault(); $('#aiSettingsDialog').close(); });
$('#aiSettingsDialog').addEventListener('click', event => {
  if (event.target === $('#aiSettingsDialog')) $('#aiSettingsDialog').close();
});

$('#saveAiApiKeyBtn').addEventListener('click', async event => {
  event.preventDefault();
  const body = {provider: $('#aiProviderSelect').value};
  const anthropicKey = $('#aiApiKeyInput').value.trim();
  const geminiKey = $('#geminiApiKeyInput').value.trim();
  if (anthropicKey) body.anthropic_api_key = anthropicKey;
  if (geminiKey) body.gemini_api_key = geminiKey;
  try {
    const data = await profileLibraryRequest('/api/ai-settings', {method: 'POST', body}, $('#saveAiApiKeyBtn'));
    $('#aiApiKeyInput').value = '';
    $('#geminiApiKeyInput').value = '';
    applyAiSettingsData(data);
    toast('KI-Einstellungen gespeichert.');
    $('#aiSettingsDialog').close();
  } catch (error) {
    toast(error.message, true);
  }
});

$('#removeAiApiKeyBtn').addEventListener('click', async event => {
  event.preventDefault();
  try {
    const data = await profileLibraryRequest('/api/ai-settings', {method: 'POST', body: {anthropic_api_key: ''}}, $('#removeAiApiKeyBtn'));
    $('#aiApiKeyInput').value = '';
    applyAiSettingsData(data);
    toast('Anthropic-API-Schlüssel entfernt.');
  } catch (error) {
    toast(error.message, true);
  }
});

$('#removeGeminiApiKeyBtn').addEventListener('click', async event => {
  event.preventDefault();
  try {
    const data = await profileLibraryRequest('/api/ai-settings', {method: 'POST', body: {gemini_api_key: ''}}, $('#removeGeminiApiKeyBtn'));
    $('#geminiApiKeyInput').value = '';
    applyAiSettingsData(data);
    toast('Gemini-API-Schlüssel entfernt.');
  } catch (error) {
    toast(error.message, true);
  }
});

function currentDeviceIdentity() {
  return {
    manufacturer: $('#profileManufacturer').value.trim() || $('#newProductManufacturer').value.trim(),
    model: $('#profileModel').value.trim() || $('#newProductModel').value.trim(),
    firmware: $('#profileFirmware').value.trim() || $('#newProductFirmware').value.trim(),
  };
}

function applyPointToFinder(item) {
  const address = Number.isInteger(item.address) ? item.address : 0;
  const width = registerCount({function: item.function || 3, data_type: item.data_type});
  $('#finderUnit').value = Number($('#finderUnit').value) || 1;
  $('#finderFunction').value = (item.function === 3 || item.function === 4) ? String(item.function) : '0';
  $('#finderStart').value = Math.max(0, address - 5);
  $('#finderEnd').value = Math.min(65535, address + width + 5);
  selectTab('finder');
  toast('Vermutung übernommen: Bereich prüfen und mit echter Modbus-Antwort abgleichen.');
}

function buildPointCard(item, badgeText) {
  const card = document.createElement('article');
  card.className = 'ai-suggestion-card';
  const addressText = Number.isInteger(item.address) ? item.address : 'unbekannt';
  const functionLabel = (item.function === 3 || item.function === 4) ? `FC${String(item.function).padStart(2, '0')}` : 'unklar';
  const sourceLink = item.source_url
    ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">${escapeHtml(item.source_url)}</a>`
    : '';
  const notes = [item.address_notes, item.function_guess_note, item.source_note, item.caveats]
    .filter(Boolean).map(escapeHtml).join(' · ');
  const factorText = Number.isInteger(item.scale_factor_address)
    ? `dynamisch – SF-Register ${item.scale_factor_address} auslesen (Faktor = 10^SF)`
    : String(item.scale ?? 1);
  card.innerHTML = `
    <div class="ai-suggestion-head">
      <div><span class="ai-suggestion-badge">${escapeHtml(badgeText)}</span><h4>${escapeHtml(item.name)}</h4></div>
      <span class="confidence confidence-${escapeHtml(item.confidence)}">${escapeHtml(item.confidence)}</span>
    </div>
    <div class="ai-suggestion-grid">
      <div><small>Grösse</small><strong>${escapeHtml(item.quantity_kind)}</strong></div>
      <div><small>Funktion</small><strong>${functionLabel}</strong></div>
      <div><small>Adresse</small><strong>${addressText}</strong></div>
      <div><small>Datentyp</small><strong>${escapeHtml(item.data_type)}</strong><span>${escapeHtml(item.order || '')}</span></div>
      <div><small>Faktor</small><strong>${escapeHtml(factorText)}</strong></div>
      <div><small>Einheit</small><strong>${escapeHtml(item.unit || '–')}</strong></div>
    </div>
    <div class="ai-suggestion-notes">${notes || 'Keine weiteren Hinweise.'}${sourceLink ? ` · Quelle: ${sourceLink}` : ''}</div>
    <div class="ai-suggestion-actions"><button class="secondary point-test-btn">Im Register-Finder testen</button></div>`;
  card.querySelector('.point-test-btn').addEventListener('click', () => applyPointToFinder(item));
  return card;
}

function renderAiSuggestions(data) {
  const warningsBox = $('#aiLookupWarnings');
  const messages = [];
  if (data.general_notes) messages.push(data.general_notes);
  if (!data.device_identified) messages.push('Das genaue Gerät konnte nicht eindeutig identifiziert werden – Vorschläge basieren auf typischen Konventionen dieser Geräteklasse.');
  if (Array.isArray(data.warnings)) messages.push(...data.warnings);
  if (messages.length) {
    warningsBox.classList.remove('hidden');
    warningsBox.innerHTML = messages.map(message => `<p>${escapeHtml(message)}</p>`).join('');
  } else {
    warningsBox.classList.add('hidden');
    warningsBox.innerHTML = '';
  }

  const container = $('#aiLookupResults');
  container.innerHTML = '';
  if (!data.points || !data.points.length) {
    container.innerHTML = '<div class="result-box muted">Keine Vorschläge gefunden.</div>';
    return;
  }
  data.points.forEach(item => container.appendChild(buildPointCard(item, 'KI-Vermutung · ungetestet')));
}

async function runAiLookup(quantity, button) {
  const identity = currentDeviceIdentity();
  if (!identity.manufacturer && !identity.model) {
    toast('Bitte zuerst Hersteller oder Modell angeben.', true);
    return;
  }
  $('#aiLookupStatus').textContent = 'Online-Suche läuft, das kann einen Moment dauern …';
  try {
    const data = await api('/api/ai/lookup', {...identity, quantity: quantity || undefined}, button);
    $('#aiLookupProviderBadge').textContent = `Anbieter: ${AI_PROVIDER_LABELS[data.provider] || data.provider}`;
    $('#aiLookupStatus').textContent = `${data.points.length} Vorschläge gefunden (${AI_PROVIDER_LABELS[data.provider] || data.provider}).`;
    renderAiSuggestions(data);
  } catch (_) {
    $('#aiLookupStatus').textContent = '';
  }
}

$('#aiLookupDeviceBtn').addEventListener('click', () => runAiLookup(null, $('#aiLookupDeviceBtn')));
$('#aiLookupQuantityBtn').addEventListener('click', () => {
  const quantity = $('#aiLookupQuantityInput').value.trim();
  if (!quantity) { toast('Bitte eine Grösse angeben, nach der gesucht werden soll.', true); $('#aiLookupQuantityInput').focus(); return; }
  runAiLookup(quantity, $('#aiLookupQuantityBtn'));
});

let catalogTypeLabels = {};

async function loadCatalogTypes() {
  try {
    const data = await profileLibraryRequest('/api/device-catalog-types');
    const select = $('#catalogTypeFilter');
    data.types.forEach(type => {
      catalogTypeLabels[type.value] = type.label;
      const option = document.createElement('option');
      option.value = type.value;
      option.textContent = type.label;
      select.appendChild(option);
    });
  } catch (_) {
    // Filter bleibt auf "Alle Gerätetypen", falls die Liste nicht geladen werden kann.
  }
}

function fillCatalogEntryBody(body, entry, identity) {
  const sourceLink = entry.source_url
    ? `<a href="${escapeHtml(entry.source_url)}" target="_blank" rel="noopener">${escapeHtml(entry.source_note || entry.source_url)}</a>`
    : '';
  const noPointsHint = !entry.points || !entry.points.length
    ? '<div class="alert warning">Noch keine Register hinterlegt. Datenblatt/Handbuch besorgen und die Punkte hier per Katalog-Import oder über Claude im Chat ergänzen.</div>'
    : '';
  body.innerHTML = `
    ${entry.aliases ? `<p class="hint">${escapeHtml(entry.aliases)}</p>` : ''}
    ${entry.notes ? `<div class="ai-suggestion-notes">${escapeHtml(entry.notes)}</div>` : ''}
    ${sourceLink ? `<div class="ai-suggestion-notes">Quelle: ${sourceLink}</div>` : ''}
    ${noPointsHint}
    <div class="button-row"><button class="delete-button catalog-delete-btn">Eintrag löschen</button></div>
    <div class="ai-lookup-results catalog-points"></div>`;
  const pointsContainer = body.querySelector('.catalog-points');
  (entry.points || []).forEach(point => pointsContainer.appendChild(buildPointCard(point, entry.verified ? 'Katalog · geprüft' : 'Katalog · unverifiziert')));
  body.querySelector('.catalog-delete-btn').addEventListener('click', async () => {
    if (!window.confirm(`Katalogeintrag „${identity}“ wirklich löschen?`)) return;
    try {
      await profileLibraryRequest(`/api/device-catalog/${encodeURIComponent(entry.id)}`, {method: 'DELETE'});
      toast('Katalogeintrag gelöscht.');
      loadCatalog();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

function renderCatalogResults(entries) {
  const container = $('#catalogResults');
  container.innerHTML = '';
  if (!entries.length) {
    container.innerHTML = '<div class="result-box muted">Keine passenden Katalogeinträge gefunden.</div>';
    return;
  }
  entries.forEach(entry => {
    const section = document.createElement('article');
    section.className = 'catalog-entry';
    const identity = [entry.manufacturer, entry.model].filter(Boolean).join(' · ') || 'Unbenannter Eintrag';
    const typeLabel = catalogTypeLabels[entry.device_type] || entry.device_type || 'Sonstiges';
    const verifiedBadge = entry.verified
      ? '<span class="confidence confidence-hoch">geprüft</span>'
      : '<span class="confidence confidence-mittel">unverifiziert</span>';
    const isIncomplete = entry.point_count === 0;
    if (isIncomplete) section.classList.add('catalog-entry-incomplete');
    const countBadge = isIncomplete
      ? '<span class="confidence confidence-niedrig">zu recherchieren</span>'
      : `${entry.point_count} Register`;
    section.innerHTML = `
      <button class="catalog-entry-toggle" type="button">
        <span class="catalog-entry-main"><strong>${escapeHtml(identity)}</strong><span class="chip">${escapeHtml(typeLabel)}</span></span>
        <span class="catalog-entry-meta">${countBadge} ${isIncomplete ? '' : verifiedBadge}<span class="catalog-entry-caret">▸</span></span>
      </button>
      <div class="catalog-entry-body hidden"></div>`;
    const body = section.querySelector('.catalog-entry-body');
    let filled = false;
    section.querySelector('.catalog-entry-toggle').addEventListener('click', () => {
      const expanded = section.classList.toggle('expanded');
      body.classList.toggle('hidden', !expanded);
      if (expanded && !filled) {
        fillCatalogEntryBody(body, entry, identity);
        filled = true;
      }
    });
    container.appendChild(section);
  });
}

async function loadCatalog(
  query = $('#catalogSearch').value.trim(),
  deviceType = $('#catalogTypeFilter').value,
  status = $('#catalogStatusFilter').value,
) {
  $('#catalogStatus').textContent = 'Nachschlagewerk wird durchsucht …';
  try {
    const params = new URLSearchParams({q: query, type: deviceType, status});
    const data = await profileLibraryRequest(`/api/device-catalog?${params.toString()}`);
    const counts = data.counts || {};
    const countText = `${data.entries.length} ${data.entries.length === 1 ? 'Eintrag' : 'Einträge'}`;
    $('#catalogCount').textContent = counts.incomplete
      ? `${countText} · ${counts.incomplete} zu recherchieren`
      : countText;
    $('#catalogStatus').textContent = '';
    renderCatalogResults(data.entries);
  } catch (error) {
    $('#catalogStatus').textContent = `Nachschlagewerk nicht verfügbar: ${error.message}`;
    $('#catalogResults').innerHTML = '';
  }
}

let catalogSearchTimer = null;
$('#catalogSearch').addEventListener('input', () => {
  clearTimeout(catalogSearchTimer);
  catalogSearchTimer = setTimeout(() => loadCatalog(), 180);
});
$('#catalogTypeFilter').addEventListener('change', () => loadCatalog());
$('#catalogStatusFilter').addEventListener('change', () => loadCatalog());

$('#catalogImportBtn').addEventListener('click', () => $('#catalogImportFile').click());
$('#catalogImportFile').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const result = await profileLibraryRequest('/api/device-catalog-import', {method: 'POST', body: {data}});
    toast(`${result.total} Katalogeintrag/-einträge importiert: ${result.created} neu, ${result.updated} aktualisiert.`);
    loadCatalog();
  } catch (error) {
    toast(error.message || 'Katalog-Import fehlgeschlagen.', true);
  }
});

$('#databaseExportBtn').addEventListener('click', async () => {
  const button = $('#databaseExportBtn');
  try {
    const data = await profileLibraryRequest('/api/profile-library-backup', {}, button);
    const blob = new Blob([JSON.stringify(data.backup, null, 2)], {type:'application/json'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `cko-modbus-profilbibliothek-${new Date().toISOString().slice(0,10)}.hbmodbusdb`;
    link.click(); URL.revokeObjectURL(link.href);
    toast(`${data.backup.profiles.length} Geräteprofile gesichert.`);
  } catch (error) {
    toast(error.message, true);
  }
});

$('#databaseImportBtn').addEventListener('click', () => $('#databaseImportFile').click());
$('#databaseImportFile').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const backup = JSON.parse(await file.text());
    const data = await profileLibraryRequest('/api/profile-library-backup', {method:'POST', body:{backup}});
    await refreshProfileLibrary();
    toast(`${data.total} Profile importiert: ${data.created} neu, ${data.updated} aktualisiert.`);
  } catch (error) {
    toast(error.message || 'Datenbankimport fehlgeschlagen.', true);
  }
});

$('#exportBtn').addEventListener('click', () => {
  const data = profileData();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  const base = (data.profile.name || `${data.connection.host}-modbus`).replace(/[^a-z0-9äöü_-]+/gi, '-').replace(/^-|-$/g, '') || 'cko-modbus-profil';
  link.href = URL.createObjectURL(blob); link.download = `${base}.hbmodbus`; link.click(); URL.revokeObjectURL(link.href);
  toast('Geräteprofil wurde exportiert.');
});

function registerCount(point) {
  if ([1, 2].includes(Number(point.function))) return 1;
  return {bool: 1, uint16: 1, int16: 1, uint32: 2, int32: 2, float32: 2, uint64: 4, int64: 4, float64: 4}[point.data_type] || 1;
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replaceAll('"', '""')}"`;
}

$('#csvExportBtn').addEventListener('click', () => {
  if (!state.points.length) { toast('Noch keine Datenpunkte für den Visu-Export vorhanden.', true); return; }
  const header = ['Bezeichnung', 'Host', 'Port', 'Transport', 'Unit-ID (Slave-ID)', 'Funktionscode', 'Register', 'Registeranzahl', 'Datentyp', 'Byte-/Word-Reihenfolge', 'Faktor', 'Offset', 'Einheit', 'Abfrage-Start', 'Abfrageanzahl', 'Wert-Offset'];
  const rows = state.points.map(point => [
    point.name, els.host.value.trim(), els.port.value, els.transport.value,
    point.unit_id, `FC${String(point.function).padStart(2, '0')}`, point.address, registerCount(point),
    point.data_type.toUpperCase(), point.order || 'BIT', point.scale, point.offset, point.unit,
    point.read_start ?? point.address, point.read_count ?? registerCount(point), point.value_offset ?? 0,
  ]);
  const csv = '\uFEFF' + [header, ...rows].map(row => row.map(csvCell).join(';')).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const link = document.createElement('a');
  const base = ($('#profileName').value.trim() || `${els.host.value.trim()}-modbus`).replace(/[^a-z0-9äöü_-]+/gi, '-').replace(/^-|-$/g, '') || 'cko-modbus-registerplan';
  link.href = URL.createObjectURL(blob); link.download = `${base}-visu.csv`; link.click(); URL.revokeObjectURL(link.href);
  toast(`${state.points.length} Datenpunkte als Visu-CSV exportiert.`);
});

$('#importBtn').addEventListener('click', () => $('#importFile').click());
$('#importFile').addEventListener('change', async event => {
  try { applyProfile(JSON.parse(await event.target.files[0].text())); }
  catch (error) { toast(error.message, true); }
  event.target.value = '';
});

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement('textarea');
  field.value = text;
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.appendChild(field);
  field.select();
  const copied = document.execCommand('copy');
  field.remove();
  if (!copied) throw new Error('Kopieren nicht unterstützt.');
}

function plainNumber(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value);
  const abs = Math.abs(value);
  if (abs > 0 && abs < 1 && abs >= 1e-12) {
    return value.toFixed(12).replace(/0+$/, '').replace(/\.$/, '');
  }
  return String(value);
}

function formatFactor(value) {
  const plain = plainNumber(Number(value));
  return escapeHtml(plain.replace('.', ','));
}

function formatDateTime(value) {
  if (!value) return 'unbekannt';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('de-CH', {dateStyle:'short', timeStyle:'short'}).format(date);
}

function formatNumber(value) {
  if (typeof value === 'string') return escapeHtml(value);
  if (typeof value !== 'number') return String(value);
  if (!Number.isFinite(value)) return String(value);
  const abs = Math.abs(value);
  if ((abs > 0 && abs < .0001) || abs >= 1e9) return value.toExponential(5);
  return new Intl.NumberFormat('de-CH', { maximumFractionDigits: 6, useGrouping: true }).format(value);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

updateTransportHint(); restoreLocal(); renderMonitor(); updateActiveProduct(); loadInterfaces(); refreshProfileLibrary(); loadAiSettings();
loadCatalogTypes().then(loadCatalog);
