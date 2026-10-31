import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium [&_svg]:size-3", {
  variants: {
    variant: {
      default: "border-transparent bg-muted text-foreground",
      outline: "border-border text-muted-foreground",
      verified: "border-transparent bg-verified/15 text-verified",
      contradicted: "border-transparent bg-contradicted/15 text-contradicted",
      unverifiable: "border-transparent bg-unverifiable/15 text-unverifiable",
      flag: "border-transparent bg-flag/15 text-flag",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
