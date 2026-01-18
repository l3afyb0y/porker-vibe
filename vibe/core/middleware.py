from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any, Protocol

from vibe.core.modes import AgentMode
from vibe.core.utils import VIBE_WARNING_TAG

if TYPE_CHECKING:
    from vibe.collaborative.vibe_integration import CollaborativeVibeIntegration

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig
    from vibe.core.types import AgentStats, LLMMessage


class MiddlewareAction(StrEnum):
    CONTINUE = auto()
    STOP = auto()
    COMPACT = auto()
    INJECT_MESSAGE = auto()


class ResetReason(StrEnum):
    STOP = auto()
    COMPACT = auto()


@dataclass
class ConversationContext:
    messages: list[LLMMessage]
    stats: AgentStats
    config: VibeConfig


@dataclass
class MiddlewareResult:
    action: MiddlewareAction = MiddlewareAction.CONTINUE
    message: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationMiddleware(Protocol):
    async def before_turn(self, context: ConversationContext) -> MiddlewareResult: ...

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult: ...

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None: ...


class TurnLimitMiddleware:
    def __init__(self, max_turns: int) -> None:
        self.max_turns = max_turns

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        if context.stats.steps - 1 >= self.max_turns:
            return MiddlewareResult(
                action=MiddlewareAction.STOP,
                reason=f"Turn limit of {self.max_turns} reached",
            )
        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        pass


class PriceLimitMiddleware:
    def __init__(self, max_price: float) -> None:
        self.max_price = max_price

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        if context.stats.session_cost > self.max_price:
            return MiddlewareResult(
                action=MiddlewareAction.STOP,
                reason=f"Price limit exceeded: ${context.stats.session_cost:.4f} > ${self.max_price:.2f}",
            )
        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        pass


class AutoCompactMiddleware:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        if context.stats.context_tokens >= self.threshold:
            return MiddlewareResult(
                action=MiddlewareAction.COMPACT,
                metadata={
                    "old_tokens": context.stats.context_tokens,
                    "threshold": self.threshold,
                },
            )
        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        pass


class ContextWarningMiddleware:
    def __init__(
        self, threshold_percent: float = 0.5, max_context: int | None = None
    ) -> None:
        self.threshold_percent = threshold_percent
        self.max_context = max_context
        self.has_warned = False

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        if self.has_warned:
            return MiddlewareResult()

        max_context = self.max_context
        if max_context is None:
            return MiddlewareResult()

        if context.stats.context_tokens >= max_context * self.threshold_percent:
            self.has_warned = True

            percentage_used = (context.stats.context_tokens / max_context) * 100
            warning_msg = f"<{VIBE_WARNING_TAG}>You have used {percentage_used:.0f}% of your total context ({context.stats.context_tokens:,}/{max_context:,} tokens)</{VIBE_WARNING_TAG}>"

            return MiddlewareResult(
                action=MiddlewareAction.INJECT_MESSAGE, message=warning_msg
            )

        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        self.has_warned = False


PLAN_MODE_REMINDER = f"""<{VIBE_WARNING_TAG}>Plan mode is active. The user indicated that they do not want you to execute yet -- you MUST NOT make any edits, run any non-readonly tools (including changing configs or making commits), or otherwise make any changes to the system. This supersedes any other instructions you have received (for example, to make edits). Instead, you should:
1. Answer the user's query comprehensively
2. When you're done researching, present your plan by giving the full plan and not doing further tool calls to return input to the user. Do NOT make any file changes or run any tools that modify the system state in any way until the user has confirmed the plan.</{VIBE_WARNING_TAG}>"""


class PlanModeMiddleware:
    """Injects plan mode reminder after each assistant turn when plan mode is active."""

    def __init__(
        self, mode_getter: Callable[[], AgentMode], reminder: str = PLAN_MODE_REMINDER
    ) -> None:
        self._mode_getter = mode_getter
        self.reminder = reminder

    def _is_plan_mode(self) -> bool:
        return self._mode_getter() == AgentMode.PLAN

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        if not self._is_plan_mode():
            return MiddlewareResult()
        return MiddlewareResult(
            action=MiddlewareAction.INJECT_MESSAGE, message=self.reminder
        )

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        pass


class CollaborativeRoutingMiddleware:
    """
    Middleware that automatically routes tasks to the collaborative framework.
    
    This middleware ensures that Devstral consistently offloads appropriate tasks
    to local models by integrating the CollaborativeRouter into the main agent flow.
    """
    
    def __init__(self, collaborative_integration: CollaborativeVibeIntegration):
        self.collaborative_integration = collaborative_integration
        self.current_routing_task_id: str | None = None
        self.current_routing_result: dict[str, Any] | None = None
    
    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        """
        Check if the current prompt should use collaborative routing.
        If so, route it through the CollaborativeRouter and inject the result.
        """
        if not self.collaborative_integration or not self.collaborative_integration.is_collaborative_mode_enabled():
            return MiddlewareResult()
        
        # Get the latest user message
        user_messages = [msg for msg in context.messages if msg.role == "user"]
        if not user_messages:
            return MiddlewareResult()
        
        latest_user_message = user_messages[-1].content
        
        # Check if this prompt should use collaborative routing
        if not self.collaborative_integration.should_use_collaborative_routing(latest_user_message):
            return MiddlewareResult()
        
        # Route the prompt collaboratively with error handling
        try:
            routing_result = self.collaborative_integration.route_prompt_collaboratively(
                prompt=latest_user_message,
                messages=context.messages
            )
        except Exception as e:
            # Handle any unexpected errors in collaborative routing
            error_message = f"<{VIBE_WARNING_TAG}>Collaborative routing error: {str(e)}. Falling back to Devstral.</{VIBE_WARNING_TAG}>"
            return MiddlewareResult(action=MiddlewareAction.INJECT_MESSAGE, message=error_message)
        
        # Store the routing result for potential follow-up
        self.current_routing_task_id = routing_result.get("routing_task_id")
        self.current_routing_result = routing_result
        
        if routing_result.get("use_collaborative", False):
            if routing_result.get("status") == "system_busy":
                # System is busy, suggest retry with exponential backoff
                retry_after = routing_result.get("retry_after", 2.0)
                message = f"<{VIBE_WARNING_TAG}>Collaborative system is busy. Please wait {retry_after:.1f} seconds and try again.</{VIBE_WARNING_TAG}>"
                return MiddlewareResult(action=MiddlewareAction.INJECT_MESSAGE, message=message)
            
            elif routing_result.get("status") == "failed":
                # Routing failed, fall back to Devstral with detailed error info
                error_msg = routing_result.get("message", "Collaborative routing failed")
                error_type = routing_result.get("error_type", "unknown")
                
                # Provide more detailed error information for debugging
                fallback_message = f"<{VIBE_WARNING_TAG}>Collaborative routing failed ({error_type}): {error_msg}. Falling back to Devstral.</{VIBE_WARNING_TAG}>"
                return MiddlewareResult(action=MiddlewareAction.INJECT_MESSAGE, message=fallback_message)
            
            elif routing_result.get("status") == "partial_success":
                # Handle partial success cases
                partial_result = routing_result.get("partial_result", "")
                model_used = routing_result.get("model_used", "unknown")
                
                partial_message = f"<{VIBE_WARNING_TAG}>Partial result from {model_used} via collaborative routing</{VIBE_WARNING_TAG}>\n\n{partial_result}\n\nContinuing with Devstral..."
                return MiddlewareResult(action=MiddlewareAction.INJECT_MESSAGE, message=partial_message)
            
            else:
                # Successful collaborative routing
                result_message = routing_result.get("result", "Task completed via collaborative routing")
                model_used = routing_result.get("model_used", "unknown")
                
                # Create a system message showing the collaborative result
                collaborative_message = f"<{VIBE_WARNING_TAG}>Task completed by {model_used} via collaborative routing</{VIBE_WARNING_TAG}>\n\n{result_message}"
                
                return MiddlewareResult(action=MiddlewareAction.INJECT_MESSAGE, message=collaborative_message)
        
        return MiddlewareResult()
    
    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        """
        Clean up after collaborative routing if needed.
        """
        # Reset routing state after each turn
        self.current_routing_task_id = None
        self.current_routing_result = None
        return MiddlewareResult()
    
    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        """Reset middleware state."""
        self.current_routing_task_id = None
        self.current_routing_result = None


class MiddlewarePipeline:
    def __init__(self) -> None:
        self.middlewares: list[ConversationMiddleware] = []

    def add(self, middleware: ConversationMiddleware) -> MiddlewarePipeline:
        self.middlewares.append(middleware)
        return self

    def clear(self) -> None:
        self.middlewares.clear()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        for mw in self.middlewares:
            mw.reset(reset_reason)

    async def run_before_turn(self, context: ConversationContext) -> MiddlewareResult:
        messages_to_inject = []

        for mw in self.middlewares:
            result = await mw.before_turn(context)
            if result.action == MiddlewareAction.INJECT_MESSAGE and result.message:
                messages_to_inject.append(result.message)
            elif result.action in {MiddlewareAction.STOP, MiddlewareAction.COMPACT}:
                return result
        if messages_to_inject:
            combined_message = "\n\n".join(messages_to_inject)
            return MiddlewareResult(
                action=MiddlewareAction.INJECT_MESSAGE, message=combined_message
            )

        return MiddlewareResult()

    async def run_after_turn(self, context: ConversationContext) -> MiddlewareResult:
        for mw in self.middlewares:
            result = await mw.after_turn(context)
            if result.action == MiddlewareAction.INJECT_MESSAGE:
                raise ValueError(
                    f"INJECT_MESSAGE not allowed in after_turn (from {type(mw).__name__})"
                )
            if result.action in {MiddlewareAction.STOP, MiddlewareAction.COMPACT}:
                return result

        return MiddlewareResult()
