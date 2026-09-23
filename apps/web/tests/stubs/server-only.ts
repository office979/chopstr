/* Ersatz für das Marker-Paket "server-only". Next.js löst es über die react-server-Condition auf eine
 * leere Datei auf; außerhalb davon wirft das Paket beim Import. Im Test-Lauf (environment "node") gibt
 * es keine React-Server-Condition, deshalb zeigt der Alias in vitest.config.ts hierher. */
export {};
