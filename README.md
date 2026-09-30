# CKO Modbus Inspector

Lokales Inbetriebnahme- und Diagnosewerkzeug für Modbus TCP sowie Modbus RTU über TCP. Die MVP-Version scannt lokale Netze, sucht Unit-IDs (Slave-IDs), liest FC01–FC04, zeigt Registerwerte gleichzeitig in allen üblichen Byte-/Word-Reihenfolgen und sammelt geprüfte Datenpunkte in wiederverwendbaren Geräteprofilen.

## Sicherheitsprinzip der MVP-Version

- ausschliesslich lesende Funktionscodes FC01–FC04
- keine Schreibfunktion
- Webserver nur auf `127.0.0.1`
- Netzwerkscan auf private/lokale IPv4-Netze und maximal `/24` beschränkt
- Geräteprofile werden in einer lokalen SQLite-Bibliothek auf dem PC gespeichert
- Bibliothekssicherungen lassen sich als `.hbmodbusdb` importieren und exportieren
- einzelne Profile lassen sich zusätzlich als `.hbmodbus` weitergeben
- einzige Ausnahme vom rein lokalen Betrieb: die optionale, per Knopfdruck ausgelöste KI-gestützte Online-Datenpunkt-Suche (siehe unten) sendet Hersteller/Modell/Firmware an Anthropic oder Google Gemini (je nach Wahl) und benötigt einen selbst hinterlegten API-Schlüssel des jeweiligen Anbieters

## Installation unter Windows

1. ZIP von [toolbox.ckoeppen.ch/tools/modbus-inspector](https://toolbox.ckoeppen.ch/tools/modbus-inspector/) herunterladen und entpacken.
2. **`CKO-Modbus-Inspector-Setup.exe`** doppelklicken – das ist die einzige Datei im Paket.
3. Das Setup installiert ohne Administratorrechte nach `%LOCALAPPDATA%\Programs\CKO Modbus Inspector` und legt eine Verknüpfung im Startmenü und auf dem Desktop an.
4. Nach der Installation startet der Inspector und öffnet `http://127.0.0.1:48722` im Browser. Python muss dafür nicht installiert sein.
5. Beenden über **Tool beenden** in der Seitenleiste. Ein erneuter Start bei laufendem Inspector öffnet nur wieder den Browser.

Deinstallation über *Windows-Einstellungen → Apps*. Profile und Einstellungen bleiben in `%LOCALAPPDATA%\hbTec\ModbusInspector` erhalten. Fehler und Ideen lassen sich direkt aus der Anwendung über **Fehler oder Idee melden** an die CKO Toolbox senden.

## Start aus dem Quellcode

Für Entwicklung und Linux: Python 3.10+ installieren, dann `start-windows.bat` bzw. `start-linux.sh` ausführen. Beim ersten Start wird eine lokale Python-Umgebung mit den Paketen aus `requirements.txt` eingerichtet. Das Windows-Setup wird per GitHub Actions gebaut (PyInstaller + Inno Setup, siehe `.github/workflows/ci.yml`).

## Typischer Ablauf

1. Optional: Unter **Gerät & Profil** Hersteller, Produkt, Modell oder Projekt suchen. Ohne Geräteauswahl direkt mit Schritt 3 oder 4 weitermachen.
2. Ein vorhandenes Profil öffnen oder sein Gerätewissen für ein neues Projekt übernehmen. Falls das Gerät noch unbekannt ist, ein neues Profil mit Produktname, Hersteller und Modell beginnen.
3. Unter **Netzwerk-Scan** Geräte mit geöffnetem Port 502 finden. VPN-Zielnetze können als CIDR manuell eingetragen werden.
4. Den gewünschten Treffer übernehmen und unter **Verbindung** den TCP-Zugang prüfen.
5. Die Übertragungsart wählen: **Modbus TCP** für echte TCP-Geräte/Protokoll-Gateways oder **Modbus RTU über TCP** für transparente Seriell-Server.
6. Hinter einem Gateway unter **Unit-IDs (Slave-IDs)** die Teilnehmer suchen. Auch eine Modbus-Exception 2 bestätigt, dass die Unit antwortet; nur die Testadresse ist dann ungültig.
7. Wenn die Registeradressen unbekannt sind, unter **Register-Finder** einen Bereich mit FC03, FC04 oder beiden durchsuchen.
8. Optional eine Referenz speichern, am Gerät gezielt einen Zustand ändern und erneut scannen. Veränderte Register werden hervorgehoben.
9. Einen Treffer direkt im **Decoder** öffnen. Die Rohregister sind anklickbar; mit Vor/Zurück lässt sich die Startadresse schrittweise verschieben.
10. Wenn ein ungefährer Anlagenwert bekannt ist, unter **Plausiblen Wert suchen** Messgrösse, aktuellen Vergleichswert, Einheit und Toleranz angeben. Das Vorzeichen nach Möglichkeit genau wie am Gerät oder in der Visu eingeben.
11. Den empfohlenen Visu-Datenpunkt prüfen, seine Konfiguration kopieren oder direkt in den Live-Monitor übernehmen.
12. Bezeichnung, Einheit, Faktor und Offset ergänzen. Die Vorschau zeigt sofort den fertig skalierten Wert.
13. Das fertige Gerätewissen im **Live-Monitor** in der lokalen Profilbibliothek speichern. Einzelprofile können als `.hbmodbus`, die ganze Bibliothek als `.hbmodbusdb` gesichert werden.
14. Für die Übernahme in eine Visualisierung den dokumentierten Registerplan als **Visu-CSV** exportieren.
15. **Tool beenden** stoppt den Live-Monitor und anschließend den lokalen Python-Server.

## Lokale Profilbibliothek

Die Bibliothek speichert Produktname, Hersteller, Modell, Firmware, Notizen, die zuletzt verwendete Verbindung und alle bestätigten Datenpunkte. Bei einem neuen Projekt kann das Registerwissen als Vorlage geladen werden; IP-Adresse, Port und Unit-/Slave-ID müssen anschliessend für die neue Anlage geprüft werden.

Standardmässig liegt die SQLite-Datei unter Windows weiterhin in `%LOCALAPPDATA%\hbTec\ModbusInspector\profiles.sqlite3`. Unter Linux wird `$XDG_DATA_HOME/hbtec-modbus-inspector/profiles.sqlite3` beziehungsweise `~/.local/share/hbtec-modbus-inspector/profiles.sqlite3` verwendet. Diese internen Pfade bleiben aus Kompatibilitätsgründen erhalten, damit vorhandene Profile nach dem Wechsel auf das CKO-Branding automatisch weiterverwendet werden. Mit `HBMODBUS_DATA_DIR` kann ein anderer Speicherordner festgelegt werden.

## KI-gestützte Online-Datenpunkt-Suche (Beta, optional)

Über den Knopf **⚙ KI** in der Kopfzeile lässt sich ein API-Schlüssel für **Anthropic (Claude)** und/oder **Google (Gemini)** hinterlegen (lokal gespeichert, gleicher Datenordner wie die Profilbibliothek) sowie der aktive Anbieter auswählen. Google AI Studio (aistudio.google.com) bietet dabei ein kostenloses Kontingent ohne Kreditkarte und ohne die u. U. blockierende "Organisation unter dieser Domain"-Prüfung der Anthropic Console – eine praktische Alternative, falls der Anthropic-Zugang über die Firmendomain nicht möglich ist.

Im Tab **Gerät & Profil** kann anschliessend bei bekanntem Hersteller/Modell online nach den wichtigsten Datenpunkten gesucht werden ("Wichtigste Datenpunkte online suchen") oder gezielt nach einer einzelnen Grösse wie Leistung oder Netzfrequenz ("Diese Grösse online suchen"). Der gewählte Anbieter sucht dazu mit Websuche nach der Herstellerdokumentation.

Die Ergebnisse sind **unverifizierte KI-Vermutungen**, keine Messwerte, und werden entsprechend gekennzeichnet. Über "Im Register-Finder testen" lässt sich der vermutete Adressbereich direkt für eine echte Modbus-Abfrage übernehmen, bevor ein Datenpunkt wie gewohnt über Register-Finder/Decoder/"Plausiblen Wert suchen" geprüft und erst danach in der Visu eingesetzt wird. Diese Funktion ist die einzige im Tool, die das lokale Netz verlässt, und wird nie automatisch ausgelöst.

## Geräte-Nachschlagewerk (lokal, kein Internetzugriff)

Im Tab **Gerät & Profil** gibt es zusätzlich zur Online-Suche ein rein lokales **Geräte-Nachschlagewerk**: eine wachsende, lokal gespeicherte Sammlung von Registerkarten bekannter Geräte (z. B. per Chat recherchiert), durchsuchbar nach Hersteller/Modell (Freitext) und filterbar nach Gerätetyp (feste Kategorien: Wechselrichter, Energiezähler, Wärmepumpe, Wärmemengenzähler, Batteriespeicher, Ladestation, Heizung/Lüftung/Klima, Kälte-/Kühltechnik, Sensor, Gateway/Datenlogger, Sonstiges), ganz ohne Internetzugriff oder API-Key. Einträge werden über **„Katalog-Datei importieren"** eingelesen (Format `.hbdevicecatalog.json`, ein einzelner Eintrag oder eine Sammlung mit `"schema": "hbtec-device-catalog"`). Wie bei der KI-Suche gilt: Einträge sind Herstellerangaben bzw. Recherche-Ergebnisse, keine Messwerte, und müssen vor Verwendung über den Register-Finder verifiziert werden. Manche Geräte (z. B. SunSpec-basierte Wechselrichter) skalieren Werte über ein separates Skalierungsfaktor-Register statt eines festen Faktors – das wird im Katalog als `scale_factor_address` gekennzeichnet und muss einmalig ausgelesen werden, um den tatsächlichen Faktor (`10^SF`) zu bestimmen. Die Startdateien aus `device-catalog-entries/` werden beim Start automatisch ins Nachschlagewerk übernommen – nur fehlende Einträge und jeder nur einmal: eigene Änderungen bleiben erhalten, ein gelöschter mitgelieferter Eintrag kommt nicht zurück.

## Modbus-Hinweise

- Eine TCP-Verbindung auf Port 502 beweist noch nicht, dass das Ziel tatsächlich korrekt auf Modbus-Anfragen antwortet.
- Transparente Seriell-Server benötigen **Modbus RTU über TCP**: RTU-Frames inklusive CRC werden unverändert durch den TCP-Kanal transportiert.
- Mehrere TCP-Verbindungen bedeuten nicht automatisch mehrere sichere Modbus-Master. Gleichzeitige Abfragen können auf dem seriellen Bus kollidieren.
- Manche native Modbus-TCP-Geräte ignorieren die Unit-ID. Wenn viele IDs identisch antworten, zeigt das Werkzeug einen Hinweis.
- Die Registeradresse wird technisch nullbasiert übertragen. Eine Dokumentation mit `40001` kann daher je nach Hersteller Adresse `0` oder `1` meinen.
- Für `Float32` und `Int32` werden zwei Register benötigt, für 64-Bit-Werte vier.
- Der Register-Finder prüft zuerst jede Adresse einzeln. Bei Modbus-Exception 2 testet er zusätzlich zusammenhängende Blöcke mit 2, 4, 6 und 8 Registern, weil manche Geräte Daten nur als vollständigen Herstellerblock liefern.
- Pro Registersuche sind maximal 512 Adressen möglich. Grosse Bereiche werden schrittweise geprüft, damit ein serieller 9600-Baud-Bus nicht unkontrolliert lange belegt wird.
- Ein Scan kann gültige und veränderte Register finden. Die fachliche Bedeutung, Einheit und Skalierung müssen anschliessend über Herstellerdokumentation, kontrollierte Zustandsänderungen oder einen bekannten Vergleichswert bestätigt werden.
- Die Zielwertsuche gewichtet Kandidaten fachlich, kann die Herstellerdokumentation aber nicht ersetzen. Eine Empfehlung immer mit Live-Verlauf oder einer gezielten Anlagenänderung verifizieren.

## Entwicklung und Tests

```bash
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python app.py
```

Die lokale Portnummer kann über `HBMODBUS_PORT` geändert werden. Öffentliche Zieladressen sind absichtlich gesperrt; für einen ausdrücklich gewollten Sonderfall kann `HBMODBUS_ALLOW_PUBLIC=1` gesetzt werden.

### Ohne echtes Gerät ausprobieren

In einem zweiten Terminal kann ein lokales Demo-Gerät gestartet werden:

```bash
python demo_server.py
```

Danach im Inspector `127.0.0.1`, Port `15020`, Unit-ID `1`, FC03 und Startadresse `0` verwenden. Die ersten beiden Holding Register ergeben als `Float32 / ABCD` den Wert `21,5`.

Für RTU über TCP stattdessen `python demo_server.py --rtu-tcp` starten und im Inspector Port `15021` sowie **Modbus RTU über TCP** auswählen.

## Geplante nächste Ausbaustufen

- Modbus RTU/ASCII über USB/RS-485
- Veränderungssuche „vorher/nachher“ für unbekannte Register
- Telegramm-Trace und Exception-Auswertung
- sicher freizugebende Schreibfunktionen
- gemeinsame CKO-Gerätebibliothek (die KI-Online-Suche liefert dafür künftig möglicherweise verwertbare Ausgangsdaten)
- Node-RED- und KNX-Projektplaner-Export
- Windows-Paket ohne separate Python-Installation

## Änderungen in 0.1.1

- Arbeitsablauf auf Netzwerk-Scan → Verbindung → Unit-IDs umgestellt
- VPN-Zielnetze im Netzwerk-Scan klarer beschrieben
- Verbindungstest ausdrücklich als TCP-Test gekennzeichnet
- Unit-Scan zeigt nun Timeout, keine Antwort und Gateway-Exceptions statt Fehler zu verschlucken
- Diagnosehinweis für Gateways mit nur einem erlaubten Modbus-Client ergänzt

## Änderungen in 0.1.2

- Modbus RTU über TCP für transparente Seriell-Server ergänzt
- Transportart wird in Geräteprofilen gespeichert
- Unit-Scan baut nach jedem Versuch eine neue TCP-Verbindung auf
- Warnung vor mehreren gleichzeitigen Modbus-Mastern auf einer seriellen Strecke
- Starter erkennt eine bereits laufende ältere Version auf Port 48722

## Änderungen in 0.1.3

- Faktor-Eingabe mit 0,1-Schritten und typischen Modbus-Faktoren bis 0,0001 ergänzt
- Vorschau wendet Faktor, Offset und Einheit jetzt sofort an
- grosse Zahlen werden lesbar mit Tausendertrennzeichen dargestellt
- Visu-CSV mit Unit-ID, Funktionscode, Register, Datentyp, Reihenfolge, Faktor und Einheit ergänzt
- Register-Finder für FC03 und FC04 mit maximal 512 Adressen pro Durchlauf ergänzt
- Vorher/Nachher-Referenz hebt veränderte Register hervor
- gültige Register lassen sich direkt an den Decoder übergeben

## Änderungen in 0.1.4

- laufende Fortschrittsanzeige für die Registersuche ergänzt
- zeigt Prozent, aktuellen Adressbereich, Abfragen, Treffer und Laufzeit
- Registerscan kann kontrolliert abgebrochen werden; Teilresultate bleiben erhalten
- Suche wird in kleine Bereiche aufgeteilt, damit der Fortschritt regelmässig sichtbar aktualisiert wird
- empfohlene Standardpause für transparente 9600-Baud-Gateways auf 50 ms erhöht
- häufige `0xFFFF`-Platzhalter werden separat gezählt, erklärt und standardmässig ausgeblendet
- Zusammenfassung unterscheidet Modbus-Antworten, wahrscheinliche Datenkandidaten und ungültige Adressen

## Änderungen in 0.1.5

- Rohregister im Decoder sind anklickbar und starten die Interpretation direkt an der gewählten Adresse
- Vorher-/Nächstes-Register-Navigation für schrittweises Springen ergänzt
- Zielwertsuche bewertet alle Offsets, Datentypen, Byte-/Word-Reihenfolgen und typische Faktoren von 1000 bis 0,0001
- Messgrösse, Bezeichnung, Erwartungswert, Einheit, Toleranz und Datentypbereich können vorgegeben werden
- passende Kandidaten lassen sich direkt anzeigen oder mit gefundener Skalierung in den Monitor übernehmen
- Live-Monitor kann eine laufende HTTP-/Modbus-Abfrage jetzt sofort abbrechen
- Monitorpunkt-Dialog lässt sich zuverlässig über Abbrechen, ×, Esc oder Klick auf den Hintergrund schliessen
- Bezeichnungen um „Unit-ID (Slave-ID)“ ergänzt
- Nullregister bleiben sichtbar, wenn sie Teil eines möglichen benachbarten 32-Bit-Werts sind
- neuer Beenden-Button stoppt Monitor und lokalen Python-Server

## Änderungen in 0.1.6

- Oberfläche an den hellen Stil des KNX Projektplaners angepasst
- feste weisse Sidebar mit klarer blauer Schrittnavigation ergänzt
- Kopfzeile, Karten, Formulare und Tabellen kompakter und ruhiger gestaltet
- Beenden-Funktion als gut sichtbarer Button dauerhaft unten in der Sidebar platziert
- Sidebar und Beenden-Funktion bleiben auch bei langen Decoder- und Suchergebnissen erreichbar
- responsive Navigation für kleinere Notebook- und Tablet-Auflösungen angepasst

## Änderungen in 0.1.7

- Zielwertsuche bewertet nicht mehr nur den Zahlenabstand, sondern zusätzlich Messgrösse, Datentyp, Registerbreite, Reihenfolge und Adressausrichtung
- typische Skalierungen um 0,00001 und 0,000001 ergänzt; ein herstellerspezifischer Zusatzfaktor kann frei angegeben werden
- negative Leistungswerte bevorzugen plausible vorzeichenbehaftete 32-Bit-Interpretationen
- gleichwertige signed/unsigned- und Reihenfolge-Dubletten werden zusammengefasst
- Ergebnisliste auf fünf eindeutige Kandidaten reduziert und um Vertrauenswert sowie Begründung ergänzt
- beste plausible Interpretation erscheint als fertiger Visu-Datenpunkt mit Unit-/Slave-ID, FC, Register, Datentyp, Reihenfolge, Faktor und Live-Wert
- Visu-Konfiguration kann kopiert oder direkt in den Live-Monitor übernommen werden

## Änderungen in 0.1.8

- Leistungssuche erkennt jetzt auch einen passenden Betrag mit entgegengesetztem Vorzeichen
- Bezug-/Lieferkonventionen des Geräts führen dadurch nicht mehr zu einem zufälligen positiven Byte-Swap-Treffer
- Eingabefeld weist darauf hin, den aktuellen Vergleichswert inklusive Vorzeichen vom Gerät oder aus der Visu zu übernehmen
- Rohwert und Vorzeichen bleiben unverändert; die Empfehlung wird sichtbar mit „Vorzeichen prüfen“ gekennzeichnet
- Ergebnisbegründung nennt die mögliche Energieflussrichtung ausdrücklich
- der reale Testfall mit `23316 / SINT32 / ABCD / 0,00001` wird bei einem Vergleichswert von `+59 kW` korrekt als `−59,65626 kW` empfohlen

## Änderungen in 0.1.9

- neuer Startschritt **Gerät & Profil** mit Suche nach Produkt, Hersteller, Modell und Projekt
- bekannte Geräteprofile können direkt geöffnet oder als Vorlage für ein neues Projekt übernommen werden
- unbekannte Geräte lassen sich vor dem Netzwerkscan mit Produkt- und Projektdaten anlegen
- dauerhafte lokale SQLite-Profilbibliothek ergänzt; sie bleibt auch nach Programmupdates erhalten
- vollständige Bibliothekssicherung und Wiederherstellung über `.hbmodbusdb` ergänzt
- Profilinformationen um Projekt/Anlage und Firmware erweitert
- Gerätewissen und projektspezifische Verbindung werden in der Oberfläche klar unterschieden

## Änderungen in 0.1.10

- Register-Finder erkennt Geräte, die 32-Bit-Werte nur als gemeinsamen 2-Register-Block beantworten
- bei Modbus-Exception 2 wird die Adresse automatisch noch einmal mit zwei Registern geprüft
- erkannte 32-Bit-Startadressen und zugehörige zweite Register werden in der Tabelle gekennzeichnet
- Fortschritt unterscheidet geprüfte Adressen von den tatsächlich gesendeten Modbus-Abfragen
- der Decoder übernimmt bei solchen Treffern automatisch die erkannte 2-Register-Abfrage

## Änderungen in 0.1.11

- Register-Finder erweitert: nach Modbus-Exception 2 werden Blockgrössen mit 2, 4, 6 und 8 Registern geprüft
- Blocktreffer bleiben auch über die internen Fortschrittsabschnitte hinweg vollständig erhalten
- Zielwertsuche erkennt identische 16-/32-Bit-Werte und bevorzugt den vollständigen 32-Bit-Datenpunkt ohne falsche hohe Sicherheit
- mehrdeutige Kandidaten werden in Hinweis, Empfehlung und Trefferliste ausdrücklich als „16/32 Bit prüfen“ markiert
- „Anzeigen“ markiert den Treffer im bereits gelesenen Block und löst keine möglicherweise unzulässige Einzelabfrage aus
- Monitorpunkte speichern Abfrage-Start, Blockgrösse und Wert-Offset; Geräte mit vorgeschriebener Blockabfrage funktionieren dadurch auch im Live-Monitor
- mehrere Monitorpunkte aus demselben Block verwenden pro Zyklus nur eine gemeinsame Modbus-Abfrage
- Visu-CSV enthält zusätzlich Abfrage-Start, Abfrageanzahl und Wert-Offset

## Änderungen in 0.1.12

- neue, optionale KI-gestützte Online-Datenpunkt-Suche (Anthropic oder Google Gemini, je mit Websuche) im Tab „Gerät & Profil“
- eigener API-Schlüssel für Anthropic und/oder Gemini sowie der aktive Anbieter lassen sich über ⚙ KI in der Kopfzeile lokal hinterlegen
- KI-Vorschläge sind klar als ungetestet gekennzeichnet und lassen sich direkt für eine echte Abfrage in den Register-Finder übernehmen
- diese Funktion ist die einzige im Tool, die das lokale Netz verlässt, und wird ausschliesslich per Knopfdruck ausgelöst

## Änderungen in 0.1.13

- neues, rein lokales Geräte-Nachschlagewerk im Tab „Gerät & Profil“ (kein Internetzugriff, kein API-Key)
- Katalogeinträge (Hersteller, Modell, Register, Quelle, Notizen) lassen sich als `.hbdevicecatalog.json`-Datei importieren
- unterstützt Geräte mit dynamischem Skalierungsfaktor-Register (z. B. SunSpec-Wechselrichter) über ein eigenes `scale_factor_address`-Feld je Datenpunkt
- Katalog-Datenpunkte lassen sich wie KI-Vorschläge direkt für eine echte Abfrage in den Register-Finder übernehmen

## Änderungen in 0.1.14

- sichtbares Branding vollständig auf **CKO Modbus Inspector** umgestellt
- originales CKO-Logo in Sidebar, Browser-Icon und Downloadpaket integriert
- eindeutige Startdatei `CKO Modbus Inspector starten.bat` ergänzt
- Windows-Verknüpfung mit CKO-Icon wird beim ersten Start automatisch erzeugt
- technische Profil- und Katalogformate bleiben vollständig kompatibel

## Änderungen in 0.2.0

- Windows-Setup statt ZIP mit Einzeldateien: nur `CKO-Modbus-Inspector-Setup.exe`, Startmenü- und Desktop-Verknüpfung, keine Python-Installation nötig
- Start ohne Konsolenfenster; ein zweiter Start öffnet nur den Browser
- mitgelieferte Geräteeinträge werden beim Start automatisch ins Nachschlagewerk übernommen
- Button «Fehler oder Idee melden» (Feedback der CKO Toolbox)

## Änderungen in 0.2.1

- Arbeitsablauf sichtbar: Überblick «So gehst du vor», erledigte Schritte mit Häkchen in der Seitenleiste und «Weiter zu Schritt …» am Ende jeder Seite; optionale Schritte sind gekennzeichnet
- Decoder: lehnt das Gerät einen Block ab (Ausnahme 2/3), wird automatisch der grösste lesbare Teil ab der Startadresse gelesen und die Anzahl angepasst – auch beim Anklicken eines Rohregisters
- Modbus-Ausnahmen mit Klartext und Tipp (z. B. «Ausnahme 2 – unzulässige Datenadresse»), inkl. Hinweis, wenn eine Nachbaradresse lesbar ist; auch im Live-Monitor
- Netzwerk-Scan erkennt transparente RS485-Gateways (Modbus RTU über TCP); «Verwenden» stellt die Übertragungsart passend ein
- Unit-ID-Scan: verständlicherer Hinweis, wenn ein Gerät die Unit-ID nicht auswertet (z. B. Askoheat)
- Nachschlagewerk: Askoheat-Eintrag mit Praxishinweis zur Unit-ID

## Änderungen in 0.2.2

- Schritt 01 «Gerät & Profil» ist als optional gekennzeichnet – es geht auch ohne Geräteauswahl; optionale Schritte tragen «OPTIONAL» in der Überschrift

## Open Source

Dieses Projekt steht unter GPL-3.0 (siehe `LICENSE`). Es nutzt unter anderem
[Flask](https://github.com/pallets/flask), [pymodbus](https://github.com/pymodbus-dev/pymodbus)
und [psutil](https://github.com/giampaolo/psutil).
