from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanDecision:
    route: str
    credits_required: int
    reason: str
    ai_allowed: bool


class FreePremiumPolicy:
    """Deterministic product policy. It decides routing, never performs billing."""

    VERSION = "free-premium-policy-v1"

    DEFAULT_COSTS = {
        "basic_audit": 0,
        "video_optimization": 0,
        "keyword_research": 0,
        "channel_strategy": 0,
        "premium_ai_rewrite": 5,
        "premium_ai_strategy": 6,
        "premium_ai_channel_audit": 8,
    }

    def decide(self, *, action: str, plan: str = "free", credits: int = 0, ai_opt_in: bool = False) -> dict[str, Any]:
        action = str(action or "").strip()
        plan = str(plan or "free").strip().casefold()
        cost = int(self.DEFAULT_COSTS.get(action, 0))
        premium_plan = plan in {"pro", "premium", "business"}
        if not ai_opt_in or cost == 0:
            decision = PlanDecision("deterministic_free", 0, "A ação pode ser executada pelo motor próprio sem IA externa.", False)
        elif premium_plan:
            decision = PlanDecision("premium_ai", 0, "O plano inclui acesso à camada de IA premium.", True)
        elif credits >= cost:
            decision = PlanDecision("premium_ai_with_credits", cost, "Créditos disponíveis para a camada de IA premium.", True)
        else:
            decision = PlanDecision("deterministic_free", 0, "Créditos insuficientes; manter o motor determinístico sem degradar a função básica.", False)
        return {
            "engine": self.VERSION,
            "action": action,
            "plan": plan,
            "route": decision.route,
            "credits_required": decision.credits_required,
            "credits_available": max(0, int(credits)),
            "ai_allowed": decision.ai_allowed,
            "reason": decision.reason,
            "writes_performed": 0,
        }
