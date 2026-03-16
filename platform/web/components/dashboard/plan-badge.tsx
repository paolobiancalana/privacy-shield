import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Plan = "free" | "dev" | "growth" | "scale" | "enterprise";

interface PlanBadgeProps {
  plan: string;
  className?: string;
}

const PLAN_STYLES: Record<Plan, string> = {
  free: "border-border text-muted-foreground",
  dev: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  growth: "border-violet-500/40 bg-violet-500/10 text-violet-400",
  scale: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  enterprise: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
};

const PLAN_LABELS: Record<Plan, string> = {
  free: "Free",
  dev: "Dev",
  growth: "Growth",
  scale: "Scale",
  enterprise: "Enterprise",
};

export function PlanBadge({ plan, className }: PlanBadgeProps) {
  const key = (plan?.toLowerCase() as Plan) ?? "free";
  const style = PLAN_STYLES[key] ?? PLAN_STYLES.free;
  const label = PLAN_LABELS[key] ?? plan;

  return (
    <Badge
      variant="outline"
      className={cn("border font-medium capitalize", style, className)}
    >
      {label}
    </Badge>
  );
}
