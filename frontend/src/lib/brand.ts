// The product names users see. Change them here and every page follows.
// Code identifiers, API routes and storage keys keep the old "countersign" name on purpose, so a rename never breaks a stored token or a URL.
export const BRAND = {
  /** The control plane that issues agent passports, checks every message and keeps the ledger. */
  name: "Agaxes",
  /** What the name stands for, shown next to the logo. */
  tagline: "Agent access",
  /** The hiring agent that runs under it. */
  agent: "Sourced",
} as const;

/** Older stored records (agent jobs, ledger notes, source names) still say "Countersign". Show them under the current name. Display only: never run this on a passport you will send back, its signature covers the text. */
export const brandText = (s?: string | null) => (s ?? "").replace(/Countersign/g, BRAND.name).replace(/countersign/g, BRAND.name.toLowerCase());
