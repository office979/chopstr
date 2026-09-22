/* Claim-Check: Spiegel von workers/chopstr_worker/pipeline/fidelity.hook_claim_check.
 * Ein Hook darf keine Zahlen oder Zuspitzungen enthalten, die im Clip nicht vorkommen (UWG: Irreführung). */

export const SUPERLATIVES = ["beste", "einzige", "garantiert", "immer", "100 %", "100%", "sofort", "heilt", "nie wieder", "jeder"];

export function hookClaimCheck(hookText: string, clipText: string): string[] {
  const issues: string[] = [];
  for (const num of hookText.match(/\d[\d.,]*/g) ?? []) {
    if (!clipText.includes(num)) issues.push(`Zahl '${num}' steht nicht im Clip`);
  }
  const lowHook = hookText.toLowerCase();
  const lowClip = clipText.toLowerCase();
  for (const sup of SUPERLATIVES) {
    if (lowHook.includes(sup) && !lowClip.includes(sup)) issues.push(`Zuspitzung '${sup}' nicht durch Clip gedeckt`);
  }
  return issues;
}
