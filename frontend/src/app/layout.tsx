import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brief to Shortlist",
  description: "Verified recruiting agent on Crustdata: every claim cited.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
