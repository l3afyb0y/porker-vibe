from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from vibe.core.modes import AgentMode
from vibe.core.types import Role
from vibe.core.utils import VIBE_STOP_EVENT_TAG, VIBE_WARNING_TAG

if TYPE_CHECKING:
    from vibe.collaborative.vibe_integration import CollaborativeVibeIntegration
    from vibe.core.config import VibeConfig
    from vibe.core.plan_manager import PlanManager
    from vibe.core.planning_models import ItemStatus
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
    current_turn_messages: list[LLMMessage]


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


class LoopDetectionMiddleware:
    """Detects repetitive patterns in LLM responses and tool calls to prevent infinite loops."""

    # Configuration for loop detection
    LOOP_WINDOW_SIZE = 10  # Extended window for better sequence detection
    LOOP_REPETITION_THRESHOLD = 5  # Higher threshold for standard repetition warning
    STRICT_REPETITION_THRESHOLD = (
        75  # Hard stop if exactly the same thing repeats 75 times
    )

    def __init__(self) -> None:
        self._recent_tool_calls: deque[str] = deque(maxlen=self.LOOP_WINDOW_SIZE)
        self._recent_llm_responses: deque[str] = deque(maxlen=self.LOOP_WINDOW_SIZE)
        self._repetition_counts: dict[str, int] = {}
        self._pending_warning: str | None = None

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        # Inject any pending loop warning from the previous turn
        if self._pending_warning:
            warning = self._pending_warning
            self._pending_warning = None
            return MiddlewareResult(
                action=MiddlewareAction.INJECT_MESSAGE, message=warning
            )
        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        current_turn_llm_response = ""
        current_turn_tool_calls = []

        for message in context.current_turn_messages:
            if message.role == Role.assistant and message.content:
                current_turn_llm_response += message.content
            if message.tool_calls:
                for tc in message.tool_calls:
                    args_str = (
                        json.dumps(tc.function.arguments)
                        if tc.function and tc.function.arguments
                        else "{}"
                    )
                    current_turn_tool_calls.append(f"{tc.function.name}:{args_str}")

        # 1. Check for strict repetition (75x)
        total_output = current_turn_llm_response + "|".join(current_turn_tool_calls)
        if total_output:
            if total_output in self._repetition_counts:
                self._repetition_counts[total_output] += 1
            else:
                self._repetition_counts = {
                    total_output: 1
                }  # Reset if something else appears

            if (
                self._repetition_counts[total_output]
                >= self.STRICT_REPETITION_THRESHOLD
            ):
                return MiddlewareResult(
                    action=MiddlewareAction.STOP,
                    reason=f"Strict repetition threshold reached ({self.STRICT_REPETITION_THRESHOLD}x same output).",
                )

        if current_turn_llm_response:
            self._recent_llm_responses.append(current_turn_llm_response)
        if current_turn_tool_calls:
            self._recent_tool_calls.append("|".join(current_turn_tool_calls))

        loop_detected, loop_reason = self._detect_loop()

        if loop_detected:
            # Alert the model so it can correct itself
            self._pending_warning = f"<{VIBE_WARNING_TAG}>Loop detected ({loop_reason})! Please analyze your recent actions and adjust your strategy to avoid repetition.</{VIBE_WARNING_TAG}>"
        else:
            self._pending_warning = None

        return MiddlewareResult()

    def _detect_loop(self) -> tuple[bool, str]:
        """Check for repetitive patterns in responses and tool calls."""
        if len(self._recent_llm_responses) >= self.LOOP_REPETITION_THRESHOLD:
            result = self._check_for_repetition(
                list(self._recent_llm_responses), "repetitive LLM responses"
            )
            if result[0]:
                return result

        if len(self._recent_tool_calls) >= self.LOOP_REPETITION_THRESHOLD:
            result = self._check_for_repetition(
                list(self._recent_tool_calls), "repetitive tool calls"
            )
            if result[0]:
                return result

        return False, ""

    def _check_for_repetition(self, items: list[str], reason: str) -> tuple[bool, str]:
        """Check if items contain a repeating pattern."""
        window_size = len(items)
        for i in range(window_size - self.LOOP_REPETITION_THRESHOLD + 1):
            pattern = items[i : i + self.LOOP_REPETITION_THRESHOLD]
            if len(pattern) >= self.LOOP_REPETITION_THRESHOLD and all(
                p == pattern[0] for p in pattern
            ):
                return True, reason
        return False, ""

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        self._recent_tool_calls.clear()
        self._recent_llm_responses.clear()
        self._repetition_counts.clear()
        self._pending_warning = None


class AutoTaskTrackingMiddleware:
    """Automatically tracks tasks and subtasks in the PlanManager based on tool execution."""

    def __init__(self, plan_manager: PlanManager) -> None:
        self.plan_manager = plan_manager
        # Map tool_call_id to PlanItem.id
        self._current_tool_call_to_plan_item: dict[str, UUID] = {}

    def register_tool_call_for_plan_item(
        self, tool_call_id: str, plan_item_id: UUID
    ) -> None:
        """Registers an association between a tool call and a plan item."""
        self._current_tool_call_to_plan_item[tool_call_id] = plan_item_id

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        # We need to look at the new messages added in this turn
        # For simplicity for now, we'll iterate all messages, but ideally
        # we'd only look at messages added since the last after_turn call.
        # This will be handled implicitly by the Agent's message handling
        # after tool execution.

        for message in context.current_turn_messages:
            if message.role == "tool" and message.tool_call_id:
                tool_call_id = message.tool_call_id
                plan_item_id = self._current_tool_call_to_plan_item.get(tool_call_id)

                if plan_item_id:
                    # Determine status based on tool result
                    if (
                        message.content and VIBE_STOP_EVENT_TAG not in message.content
                    ):  # Assuming no specific error tag yet
                        # If tool result indicates success
                        self.plan_manager.update_item_status(
                            plan_item_id, ItemStatus.COMPLETED
                        )
                    else:
                        # If tool result indicates failure or skipped
                        self.plan_manager.update_item_status(
                            plan_item_id, ItemStatus.FAILED
                        )
                    # Clear the mapping for this tool call after processing
                    self._current_tool_call_to_plan_item.pop(tool_call_id, None)

        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        self._current_tool_call_to_plan_item.clear()


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
    """Middleware that routes tasks to the collaborative framework.

    Ensures that Devstral offloads appropriate tasks to local models by integrating
    the CollaborativeRouter into the main agent flow.
    """

    def __init__(self, collaborative_integration: CollaborativeVibeIntegration) -> None:
        self.collaborative_integration = collaborative_integration
        self.current_routing_task_id: str | None = None
        self.current_routing_result: dict[str, Any] | None = None

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        """Check if the current prompt should use collaborative routing."""
        if (
            not self.collaborative_integration
            or not self.collaborative_integration.is_collaborative_mode_enabled()
        ):
            return MiddlewareResult()

        # Get the latest user message
        user_messages = [msg for msg in context.messages if msg.role == "user"]
        if not user_messages:
            return MiddlewareResult()

        latest_user_message = user_messages[-1].content

        # Check if this prompt should use collaborative routing
        if not self.collaborative_integration.should_use_collaborative_routing(
            latest_user_message
        ):
            return MiddlewareResult()

        # Route the prompt collaboratively with error handling
        try:
            routing_result = (
                self.collaborative_integration.route_prompt_collaboratively(
                    prompt=latest_user_message, messages=context.messages
                )
            )
        except Exception as e:
            # Handle any unexpected errors in collaborative routing
            error_message = f"<{VIBE_WARNING_TAG}>Collaborative routing error: {e!s}. Falling back to Devstral.</{VIBE_WARNING_TAG}>"
            return MiddlewareResult(
                action=MiddlewareAction.INJECT_MESSAGE, message=error_message
            )

        # Store the routing result for potential follow-up
        self.current_routing_task_id = routing_result.get("routing_task_id")
        self.current_routing_result = routing_result

        if routing_result.get("use_collaborative", False):
            return self._handle_routing_result(routing_result)

        return MiddlewareResult()

    def _handle_routing_result(
        self, routing_result: dict[str, Any]
    ) -> MiddlewareResult:
        """Handle the collaborative routing result based on status."""
        status = routing_result.get("status")
        model_used = routing_result.get("model_used", "unknown")

        if status == "system_busy":
            retry_after = routing_result.get("retry_after", 2.0)
            message = f"<{VIBE_WARNING_TAG}>Collaborative system is busy. Please wait {retry_after:.1f} seconds and try again.</{VIBE_WARNING_TAG}>"
        elif status == "failed":
            error_msg = routing_result.get("message", "Collaborative routing failed")
            error_type = routing_result.get("error_type", "unknown")
            message = f"<{VIBE_WARNING_TAG}>Collaborative routing failed ({error_type}): {error_msg}. Falling back to Devstral.</{VIBE_WARNING_TAG}>"
        elif status == "partial_success":
            partial_result = routing_result.get("partial_result", "")
            message = f"<{VIBE_WARNING_TAG}>Partial result from {model_used} via collaborative routing</{VIBE_WARNING_TAG}>\n\n{partial_result}\n\nContinuing with Devstral..."
        else:
            result_message = routing_result.get(
                "result", "Task completed via collaborative routing"
            )
            message = f"<{VIBE_WARNING_TAG}>Task completed by {model_used} via collaborative routing</{VIBE_WARNING_TAG}>\n\n{result_message}"

        return MiddlewareResult(action=MiddlewareAction.INJECT_MESSAGE, message=message)

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        """Clean up after collaborative routing if needed."""
        # Reset routing state after each turn
        self.current_routing_task_id = None
        self.current_routing_result = None
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        """Reset middleware state."""
        self.current_routing_task_id = None
        self.current_routing_result = None


class AutoCompactMiddleware:
    def __init__(self, mode_getter: Callable[[], AgentMode]) -> None:
        self._mode_getter = mode_getter

    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        # Autocompact only in DEFAULT mode, not in PLAN mode
        if self._mode_getter() == AgentMode.PLAN:
            return MiddlewareResult()

        if (
            context.config.autocompact_enabled
            and context.stats.context_tokens > 0
            and (
                context.stats.context_tokens
                / context.config.get_active_model().context_size
            )
            >= context.config.auto_compact_threshold
        ):
            return MiddlewareResult(
                action=MiddlewareAction.COMPACT,
                metadata={
                    "old_tokens": context.stats.context_tokens,
                    "threshold": context.config.auto_compact_threshold,
                },
            )
        return MiddlewareResult()

    async def after_turn(self, context: ConversationContext) -> MiddlewareResult:
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        pass


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
