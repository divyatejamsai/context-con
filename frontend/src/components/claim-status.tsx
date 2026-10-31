import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ClaimStatus } from "@/lib/types";

const META: Record<ClaimStatus, { label: string; Icon: typeof CheckCircle2 }> = {
  verified: { label: "Verified", Icon: CheckCircle2 },
  contradicted: { label: "Contradicted", Icon: XCircle },
  unverifiable: { label: "Unverifiable", Icon: CircleHelp },
};

export function normalizeStatus(s: string | undefined): ClaimStatus {
  return s === "verified" || s === "contradicted" ? s : "unverifiable";
}

export function ClaimBadge({ status, count }: { status: ClaimStatus; count?: number }) {
  const { label, Icon } = META[status];
  return (
    <Badge variant={status}>
      <Icon />
      {count !== undefined ? `${count} ${label.toLowerCase()}` : label}
    </Badge>
  );
}
