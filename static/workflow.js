// Arbeitsablauf sichtbar machen: Überblick, erledigte Schritte in der Seitenleiste und «Weiter» am Seitenende.
(() => {
  const STEPS = [
    {tab: 'products', title: 'Gerät & Profil', optional: 'optional – es geht auch ohne Geräteauswahl',
      what: 'Bekanntes Gerät aus der Bibliothek oder dem Nachschlagewerk wählen, um dessen Register gleich zu nutzen.',
      next: 'Ohne Geräteauswahl einfach weiter: Netzwerk-Scan – oder direkt zu Schritt 03 «Verbindung», wenn die IP-Adresse bekannt ist.'},
    {tab: 'network', title: 'Netzwerk-Scan', optional: 'optional, wenn die IP-Adresse bekannt ist', what: 'Modbus-Geräte im Netz finden.',
      next: 'In der Trefferliste «Verwenden» klicken – das Gerät wird in Schritt 03 übernommen und verbunden.'},
    {tab: 'connection', title: 'Verbindung', what: 'IP-Adresse, Port und Übertragungsart (TCP oder RTU über TCP) prüfen.',
      next: 'Wenn «erreichbar» erscheint: in Schritt 04 die Unit-/Slave-ID ermitteln.'},
    {tab: 'units', title: 'Unit-/Slave-IDs', what: 'Herausfinden, unter welcher ID das Gerät antwortet.',
      next: 'Bei der gefundenen ID «Register suchen» klicken. Ist die Registerliste bekannt, direkt zu Schritt 06 «Decoder».'},
    {tab: 'finder', title: 'Register-Finder', optional: 'optional, wenn die Registerliste bekannt ist', what: 'Belegte Register in einem Bereich suchen.',
      next: 'Einen Treffer anklicken – er wird in Schritt 06 «Decoder» gelesen und entschlüsselt.'},
    {tab: 'decoder', title: 'Decoder', what: 'Register lesen und die passende Interpretation (Datentyp, Reihenfolge, Faktor) finden.',
      next: 'Bei der plausiblen Interpretation «+ Monitor» klicken – der Datenpunkt landet in Schritt 07.'},
    {tab: 'monitor', title: 'Live-Monitor & Profil', what: 'Datenpunkte live prüfen, als Profil speichern und für die Visu exportieren.',
      next: 'Fertig: Profil speichern und bei Bedarf als Visu-CSV exportieren.'},
  ];
  const done = new Set();

  function markDone(tab) {
    if (done.has(tab)) return;
    done.add(tab);
    const button = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (button) { button.classList.add('done'); button.title = 'Erledigt'; }
    document.querySelectorAll(`[data-step-status="${tab}"]`).forEach((element) => { element.textContent = '✓ erledigt'; element.classList.add('ok'); });
    document.querySelectorAll(`[data-overview-step="${tab}"]`).forEach((element) => element.classList.add('done'));
  }

  // Erfolgreiche Anfragen erkennen, ohne die bestehende Logik anzufassen
  const RULES = [
    [/^\/api\/profile-library\/[^/]+$/, 'products'],
    [/^\/api\/network-scan$/, 'network'],
    [/^\/api\/connect$/, 'connection'],
    [/^\/api\/unit-scan$/, 'units', (data) => (data.found || []).length > 0],
    [/^\/api\/register-scan$/, 'finder'],
    [/^\/api\/read$/, 'decoder'],
    [/^\/api\/poll$/, 'monitor'],
  ];
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const response = await originalFetch(input, init);
    try {
      const path = new URL(typeof input === 'string' ? input : input.url, window.location.href).pathname;
      const rule = RULES.find(([pattern]) => pattern.test(path));
      if (rule && response.ok) {
        response.clone().json().then((data) => {
          if (data && data.ok !== false && (!rule[2] || rule[2](data))) markDone(rule[1]);
        }).catch(() => {});
      }
    } catch (_) { /* Ablaufanzeige darf nie eine Abfrage stören */ }
    return response;
  };

  function goTo(tab) {
    if (typeof selectTab === 'function') selectTab(tab);
    window.scrollTo({top: 0, behavior: 'smooth'});
    document.querySelector('.workspace')?.scrollTo({top: 0, behavior: 'smooth'});
  }

  function renderOverview() {
    const page = document.getElementById('tab-products');
    const heading = page?.querySelector('.page-heading');
    if (!heading) return;
    const box = document.createElement('div');
    box.className = 'workflow-overview';
    box.innerHTML = `<strong>So gehst du vor</strong><ol>${STEPS.map((step, index) => `
      <li><button type="button" data-overview-step="${step.tab}"><span>${String(index + 1).padStart(2, '0')}</span>
      <b>${step.title}</b><small>${step.what}${step.optional ? ` <em>(${step.optional})</em>` : ''}</small></button></li>`).join('')}</ol>`;
    box.addEventListener('click', (event) => {
      const button = event.target.closest('[data-overview-step]');
      if (button) goTo(button.dataset.overviewStep);
    });
    heading.after(box);
  }

  function renderFooters() {
    STEPS.forEach((step, index) => {
      const page = document.getElementById(`tab-${step.tab}`);
      if (!page) return;
      const following = STEPS[index + 1];
      const footer = document.createElement('div');
      footer.className = 'step-footer';
      footer.innerHTML = `
        <div class="step-footer-text"><span class="step-status" data-step-status="${step.tab}">○ offen</span>
          <p><b>Nächster Schritt:</b> ${step.next}</p></div>
        <div class="step-footer-actions">
          ${index > 0 ? `<button type="button" class="secondary" data-go="${STEPS[index - 1].tab}">← Schritt ${String(index).padStart(2, '0')}</button>` : ''}
          ${following ? `<button type="button" class="primary" data-go="${following.tab}">Weiter zu Schritt ${String(index + 2).padStart(2, '0')}: ${following.title} →</button>` : ''}
        </div>`;
      footer.addEventListener('click', (event) => {
        const button = event.target.closest('[data-go]');
        if (button) goTo(button.dataset.go);
      });
      page.appendChild(footer);
    });
  }

  function markOptionalHeadings() {
    STEPS.filter((step) => step.optional).forEach((step) => {
      const eyebrow = document.querySelector(`#tab-${step.tab} .page-heading .eyebrow`);
      if (eyebrow && !eyebrow.dataset.optional) {
        eyebrow.dataset.optional = '1';
        eyebrow.insertAdjacentHTML('beforeend', ' <span class="step-optional">· OPTIONAL</span>');
      }
      const nav = document.querySelector(`.nav-item[data-tab="${step.tab}"]`);
      if (nav) nav.title = `Optional: ${step.optional.replace(/^optional[, –-]*\s*/, '')}`;
    });
  }

  renderOverview();
  renderFooters();
  markOptionalHeadings();
  document.getElementById('newProductBtn')?.addEventListener('click', () => {
    if (document.getElementById('newProductName')?.value.trim()) markDone('products');
  });
})();
