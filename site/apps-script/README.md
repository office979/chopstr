# Warteliste einrichten (Google Sheet + Apps Script)

Fünf Schritte, etwa zehn Minuten. Alles davon musst du selbst machen: es läuft in deinem
Google-Konto, und dort komme ich nicht hin.

## 1. Tabelle

Die Tabelle **chopstr Warteliste** liegt bereits in Ferdis Google Drive (angelegt am 25.09.2026).
Ihre Adresse steht bewusst nicht hier: dieses Repository ist öffentlich, und interne Dokumente
gehören nicht in öffentlichen Quelltext.

Blatt und Kopfzeile legt das Skript beim ersten Eintrag selbst an — das Blatt heisst dann
**Warteliste**, mit den Spalten Zeitpunkt, E-Mail und Quelle. Von Hand ist dort nichts zu tun.

## 2. Skript einfügen

In der Tabelle: **Erweiterungen → Apps Script**. Der Editor öffnet sich mit einer leeren
`Code.gs`. Deren Inhalt komplett löschen und den Inhalt von [`Code.gs`](Code.gs) aus diesem Ordner
einfügen. Speichern (⌘S).

## 3. Als Web-App veröffentlichen

Oben rechts **Bereitstellen → Neue Bereitstellung**.

| Feld | Wert |
|---|---|
| Typ (Zahnrad links) | **Web-App** |
| Beschreibung | `Warteliste chopstr.io` |
| Ausführen als | **Ich** (dein Konto) |
| Zugriff | **Jeder** |

„Jeder" klingt weit, ist aber nötig: die Anmeldung kommt vom Browser eines Besuchers, der bei
Google nicht angemeldet ist. Das Skript gibt nichts heraus – `doGet` antwortet mit einem Satz,
und `doPost` schreibt nur. Die Liste selbst bleibt in deinem Drive.

Beim ersten Mal fragt Google nach der Berechtigung. Der Warnhinweis „Diese App wurde nicht
überprüft" ist normal für eigene Skripte: **Erweitert → Weiter zu … (unsicher)**.

Am Ende zeigt Google eine **Web-App-URL**. Sie endet auf `/exec`. Diese Adresse kopieren.

## 4. Adresse in die Seite eintragen

In [`../anmeldung.js`](../anmeldung.js), ganz oben:

```js
const ENDPUNKT = "https://script.google.com/macros/s/AKfycb…/exec";
```

Solange dort nichts steht, sagt das Formular ehrlich, dass die Warteliste noch nicht scharf
geschaltet ist – es tut nicht so, als sei die Adresse angekommen.

## 5. Ausprobieren

Seite öffnen, eine Adresse eintragen, ins Sheet schauen. Es muss eine Zeile mit Zeitpunkt,
Adresse und Quelle dastehen. Dieselbe Adresse ein zweites Mal ergibt wieder „Du stehst auf der
Liste", aber keine zweite Zeile.

## Wenn du das Skript änderst

Nach jeder Änderung **Bereitstellen → Bereitstellungen verwalten → Bearbeiten (Stift) → Version:
Neu → Bereitstellen**. Ohne diesen Schritt läuft weiter die alte Fassung, und die Änderung wirkt
nicht – das ist der Fehler, den man genau einmal macht.

Die URL bleibt dabei gleich. Nur eine *neue Bereitstellung* (statt einer neuen Version) gibt eine
neue URL, die dann auch in `anmeldung.js` nachgezogen werden muss.

## Was dieser Weg nicht kann

- **Kein Double-Opt-in.** Es wird nicht geprüft, ob die Adresse der Person gehört, die sie
  eingetippt hat. Für eine Warteliste mit genau einer Mail zum Start ist das vertretbar. Wenn
  daraus je ein Newsletter wird, braucht es einen echten Mailanbieter mit Bestätigungsmail.
- **Kein Schutz gegen jemanden, der es darauf anlegt.** Die Adresse der Web-App steht im
  ausgelieferten HTML – sie muss, sonst könnte kein Browser sie aufrufen. Dagegen hilft der
  Deckel von 500 Einträgen je Tag (`MAX_JE_TAG` in `Code.gs`) und die Falle für Ausfüllroboter im
  Formular. Beides hält Gelegenheitsmüll ab, keinen entschlossenen Angreifer.
- **Google ist ein US-Anbieter.** Auftragsverarbeitung über Google Ireland Ltd., Rechtsgrundlage
  ist das EU-US Data Privacy Framework. Das steht so in der Datenschutzerklärung und muss dort
  stehen bleiben, solange die Liste dort liegt.
