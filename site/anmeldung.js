/* Die Warteliste: eine E-Mail-Adresse in ein Google Sheet schreiben.
 *
 * WARUM SO. GitHub Pages liefert Dateien aus und führt nichts aus - es kann nichts speichern.
 * Die Adresse muss also zu einem Dienst, der das tut. Hier ist das ein Google Apps Script, das
 * als Web-App veröffentlicht ist und eine Zeile an ein Google Sheet anhängt. Der Quelltext dazu
 * liegt in apps-script/Code.gs, damit er versioniert ist und nicht nur in einem Browsertab lebt.
 *
 * WARUM DIE ADRESSE HIER OFFEN STEHT. Sie ist kein Geheimnis und kann keines sein: der Browser
 * jedes Besuchers muss sie kennen, um die Anfrage zu stellen. Sie in ein Repository-Secret zu
 * legen und beim Ausliefern einzusetzen, sähe nur sicherer aus - im ausgelieferten HTML stünde
 * sie genauso. Gegen Missbrauch hilft nicht Verstecken, sondern was das Skript prüft: eine Falle
 * für Ausfüllroboter, eine Prüfung der Adresse und ein Deckel auf der Menge je Tag.
 */

/* Die Web-App-Adresse des Apps Script. Endet auf /exec, nicht auf /dev.
 * Solange hier nichts steht, sagt das Formular ehrlich, dass es noch nicht eingerichtet ist -
 * statt so zu tun, als sei die Adresse angekommen. */
const ENDPUNKT = "https://script.google.com/macros/s/AKfycbx3R5pU3alqdQFSAUeS-Ook-VoqOY3mY1EJzrpmwOcJOlLQIrzeTNnzbEh2uOJ_-BdOkQ/exec";

/* Wie lange „Danke" stehen bleibt, bevor wieder ein Formular da ist. Null heisst: dauerhaft. */
const MELDUNGEN = {
  leer: "Bitte trag deine E-Mail-Adresse ein.",
  ungueltig: "Diese Adresse sieht nicht vollständig aus. Fehlt vielleicht das @ oder die Endung?",
  einwilligung: "Setz bitte das Häkchen, dann dürfen wir dir schreiben.",
  laeuft: "Wird eingetragen …",
  fehler:
    "Das hat gerade nicht geklappt. Versuch es bitte noch einmal - oder schreib uns direkt, dann tragen wir dich von Hand ein.",
  nichtEingerichtet:
    "Die Warteliste ist noch nicht scharf geschaltet. Schau in ein paar Stunden wieder vorbei.",
};

/* Absichtlich grosszügig: eine Adresse muss ein @ und dahinter einen Punkt haben, sonst kann sie
 * nicht zugestellt werden. Alles darüber hinaus weist echte Adressen ab - es gibt gültige
 * Adressen, die jeder strengeren Regel widersprechen. Die Wahrheit sagt ohnehin erst die
 * Zustellung. */
function adresseSiehtEchtAus(wert) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(wert);
}

function start() {
  const form = document.getElementById("anmeldung");
  const feld = document.getElementById("email");
  const haken = document.getElementById("einwilligung");
  const knopf = document.getElementById("absenden");
  const meldung = document.getElementById("anmeldung-meldung");
  if (!form || !feld || !haken || !knopf || !meldung) return;

  function sagen(text, art) {
    meldung.textContent = text;
    meldung.className = "meldung" + (art ? " meldung-" + art : "");
  }

  /* Wer nach einem Fehler weitertippt, soll den Fehler loswerden, ohne ihn erst abzusenden. */
  feld.addEventListener("input", () => {
    if (feld.getAttribute("aria-invalid") === "true") {
      feld.removeAttribute("aria-invalid");
      sagen("");
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    /* Die Falle: ein Feld, das Menschen nicht sehen. Ist es ausgefüllt, war es eine Maschine.
     * Kein Fehler, keine Meldung - wer das ausfüllt, soll nicht lernen, woran es lag. */
    const falle = form.elements.namedItem("website");
    if (falle && falle.value) return;

    const email = feld.value.trim();
    if (!email) {
      feld.setAttribute("aria-invalid", "true");
      feld.focus();
      sagen(MELDUNGEN.leer, "fehler");
      return;
    }
    if (!adresseSiehtEchtAus(email)) {
      feld.setAttribute("aria-invalid", "true");
      feld.focus();
      sagen(MELDUNGEN.ungueltig, "fehler");
      return;
    }
    if (!haken.checked) {
      haken.focus();
      sagen(MELDUNGEN.einwilligung, "fehler");
      return;
    }
    if (!ENDPUNKT) {
      sagen(MELDUNGEN.nichtEingerichtet, "fehler");
      return;
    }

    knopf.disabled = true;
    feld.disabled = true;
    sagen(MELDUNGEN.laeuft, "warte");

    try {
      /* text/plain und sonst nichts: damit gilt die Anfrage als „einfach" und der Browser fragt
       * nicht vorher per OPTIONS nach. Apps Script beantwortet OPTIONS nicht, und die Anfrage
       * scheiterte, bevor sie gestellt wäre. Das Skript liest den Text selbst als JSON. */
      const antwort = await fetch(ENDPUNKT, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify({
          email: email,
          quelle: location.hostname || "lokal",
          zeit: new Date().toISOString(),
        }),
      });
      const daten = await antwort.json();
      if (!antwort.ok || !daten || daten.ok !== true) throw new Error("abgelehnt");
      zeigeDanke(form, email);
    } catch (err) {
      knopf.disabled = false;
      feld.disabled = false;
      sagen(MELDUNGEN.fehler, "fehler");
    }
  });
}

/* Das Formular durch eine Bestätigung ersetzen. Das Formular stehen zu lassen lädt zum zweiten
 * Absenden ein, und die Person weiss nie, ob es geklappt hat. */
function zeigeDanke(form, email) {
  const kasten = document.createElement("div");
  kasten.className = "erfolg";
  kasten.setAttribute("role", "status");

  const titel = document.createElement("p");
  titel.className = "erfolg-titel";
  titel.innerHTML =
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  titel.append("Du stehst auf der Liste");

  const text = document.createElement("p");
  /* Die Adresse als Text einsetzen, nicht als HTML: sie kommt aus einem Eingabefeld. */
  text.textContent =
    "Wir schreiben an " + email + ", sobald chopstr startet. Sonst hörst du nichts von uns.";

  kasten.append(titel, text);
  form.replaceWith(kasten);
  kasten.focus?.();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start);
} else {
  start();
}
