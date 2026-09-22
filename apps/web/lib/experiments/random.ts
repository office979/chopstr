/* Deterministische Zufallsquelle (mulberry32) plus Gamma- und Beta-Ziehungen. Ohne Abhängigkeiten, auch im Client nutzbar.
 * Seed aus einem String (FNV-1a), damit Reihenfolgen und Konfidenzen je Clip oder Experiment reproduzierbar sind. */

export function seedFromString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export class Rng {
  private a: number;
  constructor(seed: number) {
    this.a = seed >>> 0;
  }
  next(): number {
    this.a = (this.a + 0x6d2b79f5) >>> 0;
    let t = this.a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  /* Standardnormal (Box-Muller) */
  normal(): number {
    let u = 0;
    let v = 0;
    while (u === 0) u = this.next();
    while (v === 0) v = this.next();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }
  /* Gamma(shape, 1) nach Marsaglia und Tsang; shape < 1 über Boost */
  gamma(shape: number): number {
    if (shape <= 0) return 0;
    if (shape < 1) {
      const u = this.next();
      return this.gamma(shape + 1) * Math.pow(u, 1 / shape);
    }
    const d = shape - 1 / 3;
    const c = 1 / Math.sqrt(9 * d);
    for (;;) {
      let x: number;
      let v: number;
      do {
        x = this.normal();
        v = 1 + c * x;
      } while (v <= 0);
      v = v * v * v;
      const u = this.next();
      if (u < 1 - 0.0331 * x * x * x * x) return d * v;
      if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
    }
  }
  /* Beta(alpha, beta) über zwei Gamma-Ziehungen (wie Pythons random.betavariate) */
  beta(alpha: number, beta: number): number {
    const x = this.gamma(alpha);
    const y = this.gamma(beta);
    return x + y === 0 ? 0 : x / (x + y);
  }
}
