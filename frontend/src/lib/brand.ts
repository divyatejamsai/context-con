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
