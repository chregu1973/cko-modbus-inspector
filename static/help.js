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
    {img: '11-rtu', title: 'Zähler über RS485 (USB) prüfen', tab: 'connection', text: `
      <p>Modbus-RTU-Zähler lassen sich direkt mit einem <b>USB-RS485-Adapter</b> am Laptop prüfen – vor oder statt dem Gateway. In Schritt 03 die Übertragungsart <b>«Modbus RTU über USB»</b> wählen.</p>
      <p>Für Verdrahtung, automatische Suche und Fehlersuche gibt es eine eigene Anleitung: <button type="button" class="link-button" data-help-guide="rtu">RTU-Inbetriebnahme öffnen →</button></p>`},
  ];

  // Eigene Anleitung für die Inbetriebnahme von RS485-Zählern über USB
  const RTU_STEPS = [
    {src: 'rtu-1-material.svg', title: 'Das brauchst du', tab: 'connection', caption: 'Ausrüstung für die Prüfung', text: `
      <ul><li><b>USB-RS485-Adapter</b> (z. B. mit FTDI-, CH340- oder CP210x-Chip). Windows bringt die Treiber meist mit.</li>
      <li><b>Zweiadrige, verdrillte Leitung</b> (z. B. J-Y(St)Y 2×2×0,8) – ein Paar für A/B, eine Ader für GND.</li>
      <li><b>Abschlusswiderstand 120 Ω</b> – oft im Adapter oder Zähler zuschaltbar.</li>
      <li><b>Datenblatt des Zählers</b> mit Werkseinstellungen (Baudrate, Parität, Adresse) – falls nicht zur Hand: die automatische Suche findet sie.</li></ul>`},
    {src: 'rtu-wiring.svg', title: 'Richtig anschliessen', tab: 'connection', caption: 'A an A, B an B, GND an GND', text: `
      <p><b>A</b> des Adapters an <b>A</b> des Zählers, <b>B</b> an <b>B</b>. Manche Hersteller schreiben <b>D+ / D−</b>, <b>Data+ / Data−</b> oder vertauschen die Bezeichnungen – bei «keine Antwort» A und B einfach tauschen. Das beschädigt nichts.</p>
      <p><b>GND</b> verbinden, wenn der Zähler einen Bezugsanschluss hat. Am Leitungsende <b>120 Ω</b> zwischen A und B.</p>`},
    {src: 'rtu-3-bus.svg', title: 'Mehrere Zähler am Bus', tab: 'connection', caption: 'Linie mit Abschluss an beiden Enden', text: `
      <ul><li>Zähler <b>in Linie</b> verbinden (von Zähler zu Zähler), keine Sterne oder langen Stichleitungen.</li>
      <li><b>Abschluss 120 Ω an beiden Enden</b> der Linie – nicht an jedem Zähler.</li>
      <li>Jeder Zähler braucht eine <b>eigene Adresse</b> (Unit-ID), alle dieselbe <b>Baudrate und Parität</b>.</li>
      <li>Nur <b>ein Master</b>: Gateway oder SPS während der Prüfung abklemmen.</li></ul>`},
    {img: '11-rtu', title: 'COM-Port wählen und öffnen', tab: 'connection', caption: 'Schritt 03 – Modbus RTU über USB', text: `
      <p>In Schritt 03 <b>«Modbus RTU über USB»</b> wählen. Die Liste zeigt USB-Adapter zuerst. Unsicher, welcher Port der richtige ist? Adapter abziehen, <b>«↻ Neu laden»</b> – der verschwundene Eintrag ist es.</p>
      <p>Sind Baudrate und Format bekannt, eintragen und <b>«Verbindung prüfen»</b>. Sonst direkt weiter zur automatischen Suche.</p>`},
    {img: '12-rtu-search', title: 'Einstellungen automatisch suchen', tab: 'connection', caption: 'Baudrate, Format und Unit-ID gefunden', text: `
      <p><b>«Suche starten»</b> probiert die üblichen Baudraten und Formate (8N1, 8E1, 8O1, 8N2) für die Unit-IDs im gewählten Bereich durch. Der erste Treffer wird <b>automatisch übernommen</b> – auch in Decoder und Register-Finder.</p>
      <ul><li><b>Schnell</b> genügt fast immer; <b>Vollständig</b> prüft auch seltene Baudraten.</li><li>Die gefundenen Werte später <b>genau so im Gateway</b> eintragen.</li></ul>`},
    {img: '13-rtu-monitor', title: 'Werte prüfen', tab: 'products', caption: 'Zähler aus dem Nachschlagewerk – live geprüft', text: `
      <p>Im <b>Nachschlagewerk</b> (Schritt 01) den Zähler suchen und die Datenpunkte übernehmen – oder die Register mit dem Decoder bestimmen. Dann den <b>Live-Monitor</b> starten.</p>
      <p>Der Monitor markiert <b>unplausible Werte</b> mit ⚠, z. B. Spannung ohne Faktor, negativer Zählerstand oder negative Leistung bei einem Verbraucher (Wandler verkehrt, Phasen vertauscht).</p>`},
    {img: '14-meterlist', title: 'Zählerliste für Gateway und Visu', tab: 'monitor', caption: 'Übergabe mit KNX-DPT-Vorschlag', text: `
      <p><b>«Zählerliste»</b> im Live-Monitor fasst alles zusammen: Verbindung, Unit-ID, Register, Datentyp, Faktor, letzter Wert und ein <b>Vorschlag für den KNX-DPT</b> (z. B. 14.056 Leistung, 13.013 Energie).</p>
      <ul><li><b>CSV</b> zum Ergänzen von Gruppenadresse und Raum, <b>Drucken / PDF</b> als Inbetriebnahme-Protokoll.</li><li>Damit wird das KNX-Modbus-Gateway, Node-RED oder die Visu konfiguriert.</li></ul>`},
    {src: 'rtu-8-troubleshoot.svg', title: 'Fehlersuche', tab: 'connection', caption: 'Die häufigsten Ursachen', text: `
      <ul><li><b>Keine Antwort:</b> A/B tauschen · Gateway/SPS abklemmen · ID-Bereich vergrössern · richtigen COM-Port wählen.</li>
      <li><b>Antwort nur ab und zu:</b> Abschlusswiderstand, Leitungslänge, Pause zwischen Anfragen (z. B. 50 ms) erhöhen.</li>
      <li><b>COM-Port lässt sich nicht öffnen:</b> anderes Programm (Hersteller-Software, Terminal) schliessen.</li>
      <li><b>Werte unplausibel:</b> Faktor, Datentyp und Byte-Reihenfolge im Decoder prüfen.</li></ul>`},
  ];
  const GUIDES = {main: {steps: STEPS, eyebrow: 'KURZANLEITUNG'}, rtu: {steps: RTU_STEPS, eyebrow: 'RTU-INBETRIEBNAHME'}};
  let guide = GUIDES.main;
  let index = 0;
  const dialog = $('#helpDialog');

  function show(step) {
    const steps = guide.steps;
    index = Math.max(0, Math.min(steps.length - 1, step));
    const item = steps[index];
    $('#helpImage').src = `/static/help/${item.src || `help-${item.img}.webp`}?v=${window.HB_APP_VERSION || ''}`;
    $('#helpImage').alt = item.title;
    $('#helpTitle').textContent = item.title;
    $('#helpStep').textContent = `Schritt ${index + 1} von ${steps.length}`;
    $('#helpCaption').textContent = item.caption || 'Beispiel mit Demo-Gerät';
    $('#helpContent').innerHTML = item.text;
    $('#helpPrevBtn').disabled = index === 0;
    $('#helpNextBtn').textContent = index === steps.length - 1 ? 'Fertig' : 'Weiter →';
    $('#helpDots').innerHTML = steps.map((_, i) => `<button type="button" class="${i === index ? 'active' : ''}" data-help-dot="${i}" title="${steps[i].title}"></button>`).join('');
    dialog.querySelector('.dialog-head .eyebrow').textContent = guide.eyebrow;
  }

  function open(step = 0, name = 'main') { guide = GUIDES[name] || GUIDES.main; show(step); if (!dialog.open) dialog.showModal(); }
  function close() { dialog.close(); try { localStorage.setItem('cko-modbus-help-seen', '1'); } catch (_) {} }

  $('#helpBtn')?.addEventListener('click', () => open(0));
  $('#helpCloseBtn')?.addEventListener('click', close);
  $('#helpPrevBtn')?.addEventListener('click', () => show(index - 1));
  $('#helpNextBtn')?.addEventListener('click', () => (index === guide.steps.length - 1 ? close() : show(index + 1)));
  $('#helpTryBtn')?.addEventListener('click', () => {
    const tab = guide.steps[index].tab;
    if (guide === GUIDES.rtu && $('#transport').value !== 'rtu_serial') { $('#transport').value = 'rtu_serial'; $('#transport').dispatchEvent(new Event('change')); }
    close(); selectTab(tab);
  });
  $('#helpContent')?.addEventListener('click', event => { const link = event.target.closest('[data-help-guide]'); if (link) open(0, link.dataset.helpGuide); });
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
