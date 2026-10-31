// Agents that come with their own app. Agaxes is the home; each app opens from its agent's page and from the sidebar.
// Add an entry here (keyed by the agent's name, lower case) and the console links to it everywhere.
export interface AgentApp {
  name: string;
  /** One line on what the app is for. */
  what: string;
  href: string;
  pages: { href: string; label: string; what: string }[];
}

export const AGENT_APPS: Record<string, AgentApp> = {
  sourced: {
    name: "Sourced",
    what: "Hiring: ranked shortlists, campaigns run to a signed offer, and shift staffing.",
    href: "/sourced",
    pages: [
      { href: "/sourced", label: "Shortlist", what: "Paste a brief, get a ranked shortlist with every claim checked" },
      { href: "/searches", label: "Searches", what: "Every past brief, its shortlist, and each candidate's stage" },
      { href: "/campaigns", label: "Campaigns", what: "One brief to a signed offer, about 100 conversations at once" },
      { href: "/staffing", label: "Shift staffing", what: "Fill 1,000 shifts and catch applicants who lie" },
    ],
  },
};

export const appFor = (agent?: { name: string } | null) => (agent ? AGENT_APPS[agent.name.trim().toLowerCase()] : undefined);
