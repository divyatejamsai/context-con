import type { Metadata } from "next";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = {
  title: `${BRAND.name} · ${BRAND.tagline.toLowerCase()} for AI agents`,
  description: `${BRAND.name} issues AI agents a passport tied to a real sponsor, checks every message before it leaves, and keeps a tamper-evident ledger.`,
};

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return children;
}
