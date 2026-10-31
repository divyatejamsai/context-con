import { cn } from "@/lib/utils";

/** The Sourced mark: a magnifier over a person, for an agent that finds and checks candidates. Same tile as the Agaxes mark. */
export function SourcedMark({ className }: { className?: string }) {
  return (
    <span className={cn("grid size-6 shrink-0 place-items-center rounded-[5px] bg-foreground text-background", className)}>
      <svg viewBox="0 0 16 16" className="size-[14px]" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <circle cx="6.75" cy="6.75" r="4.75" />
        <path d="m10.2 10.2 3.8 3.8" />
        <circle cx="6.75" cy="5.6" r="1.25" fill="currentColor" stroke="none" />
        <path d="M4.4 9.1c.55-.95 1.35-1.4 2.35-1.4s1.8.45 2.35 1.4" strokeWidth="1.4" />
      </svg>
    </span>
  );
}
