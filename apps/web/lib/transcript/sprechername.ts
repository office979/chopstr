/* Wie heisst der Sprecher, wenn ihn niemand benannt hat?
 *
 * Die Spracherkennung liefert Kennungen: SPEAKER_00, SPEAKER_01. Das ist eine technische Marke
 * aus der Diarisierung, kein Name - und sie stand bisher genau so in der Oberfläche, im
 * Auswahlfeld über jedem Textblock. Wer den Text korrigiert, muss entscheiden, wem ein Satz
 * gehört; „SPEAKER_00" hilft dabei nicht, und schlimmer: es sieht nach einem Fehler aus.
 *
 * Solange niemand einen echten Namen vergeben hat, heisst es hier „Sprecher 1", „Sprecher 2".
 * Das ist keine Erfindung - die Nummer steckt in der Kennung, sie wird nur lesbar gemacht und
 * beginnt bei eins statt bei null.
 */

const KENNUNG = /^SPEAKER_(\d+)$/i;

export function sprecherName(kennung: string, namen: Record<string, string> = {}): string {
  const eigener = namen[kennung]?.trim();
  if (eigener) return eigener;
  const m = KENNUNG.exec(kennung.trim());
  if (m) return `Sprecher ${Number(m[1]) + 1}`;
  /* Etwas anderes als die bekannte Form: unverändert durchreichen. Eine Kennung, die wir nicht
   * kennen, umzubenennen hiesse, etwas zu behaupten. */
  return kennung;
}

/* Trägt diese Kennung einen echten, von Hand vergebenen Namen? Gebraucht, um dem Nutzer zu
 * sagen, dass er einen vergeben kann. */
export function hatEigenenNamen(kennung: string, namen: Record<string, string> = {}): boolean {
  return Boolean(namen[kennung]?.trim());
}
