"""Validated, server-owned assistant policy shared by transport and harness."""

from dataclasses import asdict, dataclass
import math
import os


@dataclass(frozen=True)
class AgentSettings:
    model: str = "claude-haiku-5-5"
    max_turns: int = 4
    max_budget_usd: float = 0.05
    max_output_tokens: int = 768
    max_message_chars: int = 1000
    request_timeout_seconds: int = 90
    action_timeout_seconds: int = 15
    max_concurrent_runs: int = 4

    @classmethod
    def from_env(cls):
        values = {}
        bounds = {
            "max_turns": (int, 1, 12),
            "max_budget_usd": (float, 0.001, 1.0),
            "max_output_tokens": (int, 128, 2048),
            "max_message_chars": (int, 100, 4000),
            "request_timeout_seconds": (int, 15, 180),
            "action_timeout_seconds": (int, 5, 30),
            "max_concurrent_runs": (int, 1, 8),
        }
        for name, (parse, minimum, maximum) in bounds.items():
            raw = os.getenv("AGENT_" + name.upper())
            if raw is not None:
                try:
                    value = parse(raw)
                except ValueError:
                    raise ValueError(f"AGENT_{name.upper()} must be numeric") from None
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(
                        f"AGENT_{name.upper()} must be between {minimum} and {maximum}"
                    )
                values[name] = value
        model = os.getenv("AGENT_MODEL", cls.model).strip()
        if not model or len(model) > 128:
            raise ValueError("AGENT_MODEL must be a nonempty model identifier")
        return cls(model=model, **values)

    def public_config(self):
        return {
            **asdict(self),
            "mode": "read-only",
            "synthetic_only": False,
            "independent_requests": False,
            "navigation_timeout_ms": min(
                8000, (self.action_timeout_seconds - 1) * 1000
            ),
            "capabilities": [
                "search_feedback",
                "get_feedback",
                "search_opportunities",
                "get_opportunity",
                "search_tasks",
                "get_task",
                "open_page",
            ],
        }

    def worker_env(self):
        return {
            "AGENT_MODEL": self.model,
            "AGENT_MAX_TURNS": str(self.max_turns),
            "AGENT_MAX_BUDGET_USD": str(self.max_budget_usd),
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(self.max_output_tokens),
        }
