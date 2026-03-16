export type PlanId = "free" | "developer" | "business" | "enterprise";

export const PLAN_LIMITS: Record<
  PlanId,
  {
    maxKeys: number;
    rateLimit: number;
    monthlyTokens: number;
  }
> = {
  free: {
    maxKeys: 2,
    rateLimit: 10,
    monthlyTokens: 1_000,
  },
  developer: {
    maxKeys: 5,
    rateLimit: 60,
    monthlyTokens: 50_000,
  },
  business: {
    maxKeys: 20,
    rateLimit: 200,
    monthlyTokens: 500_000,
  },
  enterprise: {
    maxKeys: 100,
    rateLimit: 1_000,
    monthlyTokens: 5_000_000,
  },
};
