"use client";
import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Sheet = Dialog.Root;
export const SheetTitle = Dialog.Title;
export const SheetDescription = Dialog.Description;

export function SheetContent({ className, children, ...props }: React.ComponentProps<typeof Dialog.Content>) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 animate-fade" />
      <Dialog.Content
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-border bg-background shadow-xl sm:max-w-xl",
          "animate-slide",
          className,
        )}
        {...props}
      >
        {children}
        <Dialog.Close className="absolute right-4 top-4 rounded-md p-1 text-muted-foreground hover:bg-muted" aria-label="Close">
          <X className="size-4" />
        </Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  );
}
