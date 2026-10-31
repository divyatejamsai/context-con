"use client";
// A centered confirm dialog in the console's style, in place of the browser's window.confirm / window.prompt.
import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ConfirmOptions {
  title: string;
  body?: React.ReactNode;
  confirm: string;
  tone?: "danger" | "primary";
  /** Ask for a reason too; the value is passed to onConfirm. */
  reason?: { label: string; placeholder?: string; initial?: string };
  onConfirm: (reason: string) => unknown | Promise<unknown>;
}

/** Returns [ask, dialog]: call ask({...}) to open it, and render dialog once. */
export function useConfirm(): [(o: ConfirmOptions) => void, React.ReactNode] {
  const [opts, setOpts] = React.useState<ConfirmOptions | null>(null);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const ask = React.useCallback((o: ConfirmOptions) => {
    setReason(o.reason?.initial ?? "");
    setOpts(o);
  }, []);
  const go = async () => {
    if (!opts || (opts.reason && !reason.trim())) return;
    setBusy(true);
    try {
      await opts.onConfirm(reason.trim());
      setOpts(null);
    } finally {
      setBusy(false);
    }
  };
  const dialog = (
    <Dialog.Root open={!!opts} onOpenChange={(o) => !o && !busy && setOpts(null)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 animate-fade" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] max-w-[440px] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border-strong bg-panel p-5 shadow-xl animate-fade"
          onOpenAutoFocus={(e) => {
            if (!opts?.reason) return;
            e.preventDefault();
            (document.getElementById("confirm-reason") as HTMLInputElement | null)?.select();
          }}
        >
          <Dialog.Title className="text-[15px] font-[620] tracking-[-0.01em]">{opts?.title}</Dialog.Title>
          {opts?.body && <Dialog.Description className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{opts.body}</Dialog.Description>}
          {opts?.reason && (
            <label className="mt-4 block">
              <span className="mb-1.5 block text-[12px] font-[510] text-muted-foreground">{opts.reason.label}</span>
              <input
                id="confirm-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && go()}
                placeholder={opts.reason.placeholder}
                className="h-9 w-full rounded-md border border-border-strong bg-panel px-3 text-[13px] outline-none focus:border-ring"
              />
            </label>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close
              disabled={busy}
              className="inline-flex h-8 items-center rounded-md px-3 text-[13px] text-muted-foreground transition hover:bg-hover hover:text-foreground"
            >
              Cancel
            </Dialog.Close>
            <button
              onClick={go}
              disabled={busy || (!!opts?.reason && !reason.trim())}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-[510] text-white transition disabled:opacity-50",
                opts?.tone === "danger" ? "bg-contradicted hover:opacity-90" : "bg-primary hover:bg-primary-strong",
              )}
            >
              {busy && <Loader2 className="size-3.5 animate-spin" />} {opts?.confirm}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
  return [ask, dialog];
}
