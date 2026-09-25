# Warteliste: wie sie aufgebaut ist

**Eingerichtet und in Betrieb seit 26.09.2026.** Hier steht, was wo liegt und was zu tun ist,
wenn sich etwas ändert. Zum Einrichten ist nichts mehr zu tun.

## Der Weg einer E-Mail-Adresse

```
Formular auf chopstr.io          site/index.html
   -> fetch, Content-Type: text/plain    site/anmeldung.js  (ENDPUNKT, Zeile 18)
      -> Apps Script "chopstr Warteliste", Web-App
         -> Blatt "Warteliste" im Google Sheet "chopstr Warteliste"
```

`text/plain` ist kein Versehen: damit gilt die Anfrage als „einfach", und der Browser fragt nicht
vorher per OPTIONS nach. Apps Script beantwortet OPTIONS nicht, und die Anmeldung scheiterte,
bevor sie gestellt wäre. Das Skript liest den Text selbst als JSON.

## Was wo liegt

| Teil | Wo |
|---|---|
| Tabelle | Google Drive von office@placemedia.at, **chopstr Warteliste**, Blatt **Warteliste** |
| Skript | an die Tabelle gebunden: dort **Erweiterungen → Apps Script** |
| Quelltext des Skripts | [`Code.gs`](Code.gs) in diesem Ordner — die versionierte Fassung |
| Adresse der Web-App | `site/anmeldung.js`, Zeile 18 |

Die Adresse der Tabelle steht bewusst nicht hier: dieses Repository ist öffentlich.

## Einstellungen der Bereitstellung

| Feld | Wert |
|---|---|
| Typ | Web-App |
| Ausführen als | Ich (office@placemedia.at) |
| Zugriff | **Jeder** |

„Jeder" klingt weit, ist aber nötig: die Anmeldung kommt vom Browser eines Besuchers, der bei
Google nicht angemeldet ist. Herausgegeben wird dabei nichts — `doGet` antwortet mit einem Satz,
`doPost` schreibt nur. Die Liste bleibt in Ferdis Drive.

## Wenn du Code.gs änderst

Der Quelltext hier ist die Wahrheit, das Skript in Google ist die Kopie. Nach einer Änderung:

1. Inhalt von `Code.gs` in den Apps-Script-Editor kopieren, speichern
2. **Bereitstellen → Bereitstellungen verwalten → Bearbeiten (Stift) → Version: Neu → Bereitstellen**

Ohne Schritt 2 läuft weiter die alte Fassung. Das ist der Fehler, den man genau einmal macht.
Die Adresse bleibt dabei gleich; nur eine *neue Bereitstellung* (statt einer neuen Version) gibt
eine neue Adresse, die dann auch in `anmeldung.js` nachgezogen werden muss.

## Was dieser Weg nicht kann

- **Kein Double-Opt-in.** Es wird nicht geprüft, ob die Adresse der Person gehört, die sie
  eingetippt hat. Für eine Warteliste mit genau einer Mail zum Start ist das vertretbar. Wenn
  daraus je ein Newsletter wird, braucht es einen Mailanbieter mit Bestätigungsmail.
- **Kein Schutz gegen jemanden, der es darauf anlegt.** Die Adresse der Web-App steht im
  ausgelieferten HTML — sie muss, sonst könnte kein Browser sie aufrufen. Dagegen hilft der
  Deckel von 500 Einträgen je Tag (`MAX_JE_TAG` in `Code.gs`), die Adressprüfung und das
  Fallenfeld im Formular. Das hält Gelegenheitsmüll ab, keinen entschlossenen Angreifer.
- **Google ist ein US-Anbieter.** Auftragsverarbeitung über Google Ireland Ltd., Rechtsgrundlage
  für die Drittlandübermittlung ist das EU-US Data Privacy Framework. Das steht so in
  `site/datenschutz.html` und muss dort stehen bleiben, solange die Liste dort liegt.
- **Das Skript darf mehr, als es tut.** Die erteilte Berechtigung lautet „alle Google-Tabellen
  sehen, bearbeiten, erstellen und löschen" — enger geht es bei `SpreadsheetApp` nicht. Das
  Skript rührt nur das Blatt „Warteliste" in seiner eigenen Tabelle an; nachprüfbar in `Code.gs`.
  Zurücknehmen lässt sich die Berechtigung unter myaccount.google.com → Sicherheit → Apps von
  Drittanbietern, dann nimmt die Warteliste allerdings nichts mehr entgegen.
