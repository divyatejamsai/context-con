import { redirect } from "next/navigation";

// Agaxes is the home page: the console for every agent. Each agent's own app (Sourced at /sourced) opens from there.
export default function Home() {
  redirect("/console");
}
