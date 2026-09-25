/* chopstr · Warteliste — das Stück, das die Adresse ins Google Sheet schreibt.
 *
 * Dieser Quelltext läuft NICHT in diesem Repository. Er gehört in ein Google Apps Script, das mit
 * dem Sheet verbunden und als Web-App veröffentlicht ist. Er liegt hier, damit er versioniert ist
 * und nicht nur in einem Browsertab lebt, den irgendwann niemand mehr findet. Wer ihn hier ändert,
 * muss ihn drüben einfügen und neu veröffentlichen - siehe README.md daneben.
 *
 * WAS DIE WEB-APP KANN UND WAS NICHT. Sie nimmt eine Adresse entgegen und hängt eine Zeile an.
 * Sie verschickt nichts, bestätigt nichts und prüft nicht, ob die Adresse wirklich der Person
 * gehört, die sie eingetippt hat. Ein Double-Opt-in gibt es also nicht. Für eine Warteliste, deren
 * einzige Mail die Startnachricht ist, ist das vertretbar - für einen Newsletter wäre es das
 * nicht.
 */

/* Wie das Blatt heisst, in das geschrieben wird. Muss genau so im Sheet stehen. */
var BLATT = "Warteliste";

/* Deckel je Tag. Ohne ihn kann jemand, der die Adresse der Web-App kennt, das Sheet in einer
 * Nacht mit hunderttausend Zeilen füllen. Mit Deckel verliert man im schlimmsten Fall einen Tag. */
var MAX_JE_TAG = 500;

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) return antwort(false, "leer");

    var daten;
    try {
      daten = JSON.parse(e.postData.contents);
    } catch (fehler) {
      return antwort(false, "kein_json");
    }

    /* Zwei Arten von Nachricht kommen hier an: eine Anmeldung und eine nachgereichte Antwort.
     * Ohne Angabe ist es eine Anmeldung - so war es vorher, und so bleibt es. */
    if (String(daten.art || "") === "nachfrage") return nachfrageSpeichern(daten);

    var email = String(daten.email || "").trim().toLowerCase();
    if (!adresseSiehtEchtAus(email)) return antwort(false, "ungueltig");
    if (email.length > 254) return antwort(false, "ungueltig");

    var quelle = String(daten.quelle || "").slice(0, 80);

    /* Ein Schloss: zwei Anmeldungen in derselben Sekunde würden sonst dieselbe Zeile überschreiben
     * oder die Doppelprüfung aushebeln. */
    var schloss = LockService.getScriptLock();
    schloss.waitLock(10000);
    try {
      var blatt = blattHolen();
      var vorhanden = blatt.getLastRow() > 1
        ? blatt.getRange(2, 2, blatt.getLastRow() - 1, 1).getValues()
        : [];

      /* Schon eingetragen? Dann ist das kein Fehler. Wer zweimal klickt, soll zweimal „Danke"
       * sehen und nicht „das hat nicht geklappt" - und im Sheet steht die Adresse trotzdem
       * nur einmal. */
      for (var i = 0; i < vorhanden.length; i++) {
        if (String(vorhanden[i][0]).trim().toLowerCase() === email) {
          return antwort(true, "schon_da");
        }
      }

      var heute = new Date();
      if (heuteGezaehlt(blatt, heute) >= MAX_JE_TAG) return antwort(false, "zu_viele");

      blatt.appendRow([heute, email, quelle, "", ""]);
      return antwort(true, "eingetragen");
    } finally {
      schloss.releaseLock();
    }
  } catch (fehler) {
    /* Nie den inneren Fehlertext nach aussen geben: er verrät Aufbau und Namen. */
    return antwort(false, "fehler");
  }
}

/* Ein Aufruf im Browser soll nicht ins Leere laufen - und vor allem nicht die Liste zeigen. */
function doGet() {
  return ContentService.createTextOutput(
    "chopstr · Warteliste. Diese Adresse nimmt nur Anmeldungen entgegen."
  ).setMimeType(ContentService.MimeType.TEXT);
}

function antwort(ok, grund) {
  return ContentService.createTextOutput(
    JSON.stringify({ ok: ok, grund: grund })
  ).setMimeType(ContentService.MimeType.JSON);
}

function adresseSiehtEchtAus(wert) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(wert);
}

var SPALTEN = ["Zeitpunkt", "E-Mail", "Quelle", "Tätigkeit", "Material je Monat"];

/* Welche Spalte zu welcher Nachfrage gehört. Nur diese beiden dürfen nachträglich beschrieben
 * werden - alles andere käme aus dem offenen Netz und hat in der Tabelle nichts verloren. */
var NACHFRAGEN = { taetigkeit: 4, menge: 5 };

function blattHolen() {
  var mappe = SpreadsheetApp.getActiveSpreadsheet();
  var blatt = mappe.getSheetByName(BLATT);
  if (!blatt) {
    blatt = mappe.insertSheet(BLATT);
  }
  if (blatt.getLastRow() === 0) {
    blatt.appendRow(SPALTEN);
    blatt.getRange(1, 1, 1, SPALTEN.length).setFontWeight("bold");
    blatt.setFrozenRows(1);
    return blatt;
  }
  /* Eine Tabelle aus der Zeit vor den Nachfragen hat nur drei Spalten. Fehlende Überschriften
   * werden ergänzt, vorhandene nicht angefasst - sonst überschriebe ein Lauf, was jemand von
   * Hand umbenannt hat. */
  for (var i = 0; i < SPALTEN.length; i++) {
    var zelle = blatt.getRange(1, i + 1);
    if (String(zelle.getValue()).trim() === "") {
      zelle.setValue(SPALTEN[i]).setFontWeight("bold");
    }
  }
  return blatt;
}

/* Eine Nachfrage nachtragen.
 *
 * Die Adresse steht zu diesem Zeitpunkt schon in der Tabelle - das Wertvolle ist also gesichert,
 * und diese Antwort ist eine Zugabe. Genau darin liegt der Unterschied zu einem Formular, das
 * sechs Fragen stellt, BEVOR es die Adresse bekommt: dort kostet jeder Abbruch einen Kontakt,
 * hier kostet er nichts. */
function nachfrageSpeichern(daten) {
  var email = String(daten.email || "").trim().toLowerCase();
  if (!adresseSiehtEchtAus(email)) return antwort(false, "ungueltig");

  var spalte = NACHFRAGEN[String(daten.feld || "")];
  if (!spalte) return antwort(false, "unbekanntes_feld");

  var wert = String(daten.wert || "").trim().slice(0, 60);
  if (!wert) return antwort(false, "leer");

  var schloss = LockService.getScriptLock();
  schloss.waitLock(10000);
  try {
    var blatt = blattHolen();
    if (blatt.getLastRow() < 2) return antwort(false, "nicht_gefunden");
    var adressen = blatt.getRange(2, 2, blatt.getLastRow() - 1, 1).getValues();
    for (var i = adressen.length - 1; i >= 0; i--) {
      if (String(adressen[i][0]).trim().toLowerCase() === email) {
        blatt.getRange(i + 2, spalte).setValue(wert);
        return antwort(true, "vermerkt");
      }
    }
    return antwort(false, "nicht_gefunden");
  } finally {
    schloss.releaseLock();
  }
}

function heuteGezaehlt(blatt, heute) {
  if (blatt.getLastRow() < 2) return 0;
  var zeiten = blatt.getRange(2, 1, blatt.getLastRow() - 1, 1).getValues();
  var tag = Utilities.formatDate(heute, Session.getScriptTimeZone(), "yyyy-MM-dd");
  var anzahl = 0;
  for (var i = 0; i < zeiten.length; i++) {
    var wert = zeiten[i][0];
    if (wert instanceof Date) {
      if (Utilities.formatDate(wert, Session.getScriptTimeZone(), "yyyy-MM-dd") === tag) anzahl++;
    }
  }
  return anzahl;
}
