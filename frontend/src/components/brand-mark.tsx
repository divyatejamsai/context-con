import { cn } from "@/lib/utils";

/** The Agaxes mark: an A drawn as one stroke, on the foreground colour. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn("grid size-7 shrink-0 place-items-center rounded-[7px] bg-foreground text-background", className)}>
      <svg viewBox="0 0 16 16" className="size-[15px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M2.5 13.5 8 2.5l5.5 11" />
        <path d="M5.2 9.5h5.6" />
      </svg>
    </span>
  );
}
