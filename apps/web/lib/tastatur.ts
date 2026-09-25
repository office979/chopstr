/* Tastenkürzel, die im ganzen Fenster gelten, ohne den zu stören, der gerade tippt.
 *
 * Ein Kürzel am Dokument hört überall mit. Das ist der Punkt - wer die Leertaste drückt, will
 * abspielen, egal wo der Fokus gerade steht - und zugleich die Gefahr: in einem Textfeld ist die
 * Leertaste ein Leerzeichen, und auf einem Knopf löst sie ihn aus. Beides darf ein Kürzel nicht
 * überfahren, sonst zerstört es Eingaben oder klickt ungefragt.
 */

/* Tippt hier gerade jemand? Dann gehört die Taste ihm. */
export function tipptGerade(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/* Hat die Leertaste an dieser Stelle schon eine eigene Bedeutung?
 *
 * Auf einem Knopf, einem Link, einem Schalter oder einem Reiter löst sie ihn aus. Dort das
 * Abspielen dazwischenzuschieben hiesse, den Knopf unbrauchbar zu machen - und wer mit der
 * Tastatur bedient, hat genau dann den Fokus auf einem Knopf. */
export function leertasteGehoertDemElement(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.tagName === "BUTTON" || el.tagName === "A") return true;
  const rolle = el.getAttribute("role");
  return rolle === "button" || rolle === "switch" || rolle === "tab" || rolle === "checkbox" || rolle === "radio";
}

/* Ist ein Dialog offen? Dann gehört die Tastatur ihm.
 *
 * Gefragt wird das Dokument und nicht ein Zustand der Seite: Dialoge kommen aus verschiedenen
 * Komponenten, und ein Kürzel, das jeden davon einzeln kennen muss, vergisst irgendwann einen. */
export function dialogOffen(): boolean {
  if (typeof document === "undefined") return false;
  return document.querySelector('[role="dialog"], [role="alertdialog"], dialog[open]') != null;
}
