import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface PlanBadgeProps {
  plan: string;
  className?: string;
}

export function PlanBadge({ plan, className }: PlanBadgeProps) {
  const isBeta = plan === "free";

  return (
    <Badge
      variant="outline"
      className={cn(
        "border font-medium",
        isBeta
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
          : plan === "enterprise"
            ? "border-violet-500/40 bg-violet-500/10 text-violet-400"
            : "border-blue-500/40 bg-blue-500/10 text-blue-400",
        className
      )}
    >
      {isBeta ? "Beta (Free)" : plan}
    </Badge>
  );
}
