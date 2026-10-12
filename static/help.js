// Bebilderte Kurzanleitung «So geht's»: Schritt für Schritt mit echten Screenshots.
(() => {
  const STEPS = [
    {img: '1-start', title: 'Überblick', tab: 'products', text: `
      <p>Der Inspector führt in sieben Schritten von der IP-Adresse bis zum fertigen Datenpunkt. Der Überblick «So gehst du vor» zeigt alle Schritte; erledigte bekommen in der Seitenleiste ein Häkchen.</p>
      <ul><li><b>Optional</b> (rot markiert) sind Geräteauswahl, Netzwerk-Scan und Register-Finder.</li><li>Am Ende jeder Seite führt <b>«Weiter zu Schritt …»</b> zum nächsten Schritt.</li></ul>`},
    {img: '2-network', title: 'Gerät im Netz finden', tab: 'network', text: `
      <p>IP-Bereich eintragen (z. B. <code>192.168.1.0/24</code>) und <b>«Netz scannen»</b>. Mit «Modbus-Antwort verifizieren» werden nur echte Modbus-Geräte als bestätigt markiert – auch Gateways mit Modbus RTU über TCP.</p>
      <p>Beim Treffer <b>«Verwenden»</b> klicken: Adresse und Übertragungsart werden übernommen.</p>`},
    {img: '3-connection', title: 'Verbinden', tab: 'connection', text: `
      <p>IP-Adresse, Port (meist 502) und Übertragungsart prüfen, dann <b>«Verbindung prüfen»</b>.</p>
      <ul><li><b>Pause zwischen Anfragen</b> hilft bei langsamen Geräten und Gateways.</li><li>Der <b>Verbindungsstatus</b> zeigt: Alle Funktionen teilen sich eine Verbindung pro Gerät – wichtig für Geräte mit wenigen Modbus-Sitzungen. Lehnt ein Gerät ab, läuft evtl. Home Assistant, Node-RED oder die Visu parallel.</li></ul>`},
    {img: '4-units', title: 'Unit-ID finden', tab: 'units', text: `
      <p>Bereich der Unit-IDs (früher Slave-ID) wählen und <b>«Unit-IDs scannen»</b>. Grün = Antwort mit Wert, «Exception» = Gerät antwortet, kennt aber die Testadresse nicht.</p>
      <p>Antworten sehr viele IDs gleich, wertet das Gerät die Unit-ID nicht aus – dann ist jede ID gültig. Bei der passenden ID <b>«Register suchen»</b>.</p>`},
    {img: '5-sunspec', title: 'Register finden – oder SunSpec', tab: 'finder', text: `
      <p>Bei Wechselrichtern, Zählern und Speichern mit SunSpec (Fronius, SMA, SolarEdge, KACO …) einfach <b>«SunSpec suchen»</b>: Hersteller, Modell, Seriennummer und alle Messwerte samt Skalierung werden direkt gelesen.</p>
      <p>Mit <b>«Alle Messwerte übernehmen»</b> landen sie im Live-Monitor. Ohne SunSpec durchsucht der Register-Finder einen Adressbereich.</p>`},
    {img: '6-decoder', title: 'Werte entschlüsseln', tab: 'decoder', text: `
      <p>Unit-ID, Funktion, Startadresse und Anzahl eingeben und <b>«Register lesen»</b>. Der Decoder zeigt jeden Rohwert in allen Datentypen und Byte-Reihenfolgen – inklusive Float16 und Text.</p>
      <ul><li>Kennst du den Wert am Gerät, findet <b>«Plausiblen Wert suchen»</b> die passende Interpretation.</li><li>Lehnt das Gerät einen Block ab, liest der Inspector automatisch den lesbaren Teil.</li></ul>`},
    {img: '7-point', title: 'Datenpunkt übernehmen', tab: 'decoder', text: `
      <p>Bei der plausiblen Zeile <b>«+ Monitor»</b> klicken, Bezeichnung, Einheit und Faktor eintragen – die Vorschau zeigt sofort den umgerechneten Wert.</p>`},
    {img: '8-monitor', title: 'Live-Monitor, Profil & Export', tab: 'monitor', text: `
      <p>Im Live-Monitor laufen alle Datenpunkte mit Verlauf. Profilangaben ergänzen und <b>«In Profilbibliothek speichern»</b>.</p>
      <ul><li><b>Home Assistant (YAML)</b>: fertiger <code>modbus:</code>-Block für Home Assistant.</li><li><b>Visu-CSV</b> und <b>.hbmodbus</b> für Visualisierung und Weitergabe.</li></ul>`},
    {img: '9-write', title: 'Werte schreiben', tab: 'monitor', text: `
      <p>Schreiben ist gesperrt. Oben rechts <b>«Nur Lesen»</b> anklicken, um es für 30 Minuten freizugeben. Dann im Live-Monitor bei einem Datenpunkt <b>✎</b> oder im Decoder «✎ Schreiben».</p>
      <ul><li>Die Vorschau zeigt Funktionscode und Registerwerte, vor dem Senden bestätigen.</li><li>Danach wird zurückgelesen: ✓ heisst, das Gerät hat den Wert übernommen.</li><li>Zuerst an einem unkritischen Register testen.</li></ul>`},
    {img: '10-catalog', title: 'Geräte-Nachschlagewerk', tab: 'products', text: `
      <p>Das Nachschlagewerk enthält Registerkarten bekannter Geräte – u. a. Zähler, Wechselrichter und Speicher aus den offenen evcc-Vorlagen. Suchen, Eintrag öffnen und Datenpunkte übernehmen.</p>
      <ul><li><b>«Katalog-Datei / Loxone-Vorlage importieren»</b>: eigene Katalogdateien oder selbst heruntergeladene Loxone-Modbus-Vorlagen (.xml) einlesen.</li><li>Einträge sind Herstellerangaben – vor Verwendung mit dem Decoder prüfen.</li></ul>`},
  ];
  let index = 0;
  const dialog = $('#helpDialog');

  function show(step) {
    index = Math.max(0, Math.min(STEPS.length - 1, step));
    const item = STEPS[index];
    $('#helpImage').src = `/static/help/help-${item.img}.webp?v=${window.HB_APP_VERSION || ''}`;
    $('#helpImage').alt = item.title;
    $('#helpTitle').textContent = item.title;
    $('#helpStep').textContent = `Schritt ${index + 1} von ${STEPS.length}`;
    $('#helpCaption').textContent = 'Beispiel mit Demo-Gerät';
    $('#helpContent').innerHTML = item.text;
    $('#helpPrevBtn').disabled = index === 0;
    $('#helpNextBtn').textContent = index === STEPS.length - 1 ? 'Fertig' : 'Weiter →';
    $('#helpDots').innerHTML = STEPS.map((_, i) => `<button type="button" class="${i === index ? 'active' : ''}" data-help-dot="${i}" title="${STEPS[i].title}"></button>`).join('');
  }

  function open(step = 0) { show(step); if (!dialog.open) dialog.showModal(); }
  function close() { dialog.close(); try { localStorage.setItem('cko-modbus-help-seen', '1'); } catch (_) {} }

  $('#helpBtn')?.addEventListener('click', () => open(0));
  $('#helpCloseBtn')?.addEventListener('click', close);
  $('#helpPrevBtn')?.addEventListener('click', () => show(index - 1));
  $('#helpNextBtn')?.addEventListener('click', () => (index === STEPS.length - 1 ? close() : show(index + 1)));
  $('#helpTryBtn')?.addEventListener('click', () => { const tab = STEPS[index].tab; close(); selectTab(tab); });
  $('#helpDots')?.addEventListener('click', event => { const dot = event.target.closest('[data-help-dot]'); if (dot) show(Number(dot.dataset.helpDot)); });
  dialog?.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog?.addEventListener('keydown', event => {
    if (event.key === 'ArrowRight') show(index + 1);
    if (event.key === 'ArrowLeft') show(index - 1);
  });
  window.openHelp = open;

  // Beim ersten Start einmal öffnen
  let seen = true;
  try { seen = localStorage.getItem('cko-modbus-help-seen') === '1'; } catch (_) {}
  if (!seen) setTimeout(() => open(0), 600);
})();
