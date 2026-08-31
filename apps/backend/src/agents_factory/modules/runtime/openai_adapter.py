from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol, cast

from agents import Agent, FunctionTool, ModelSettings, RunConfig, Runner, Tool
from agents.models.openai_provider import OpenAIProvider
from agents.retry import ModelRetrySettings
from agents.run_config import ToolExecutionConfig
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from agents_factory.common.deferral import JobDeferred

from agents_factory.modules.runtime.contracts import (
    AgentTurnInput,
    AgentTurnResult,
    RuntimeTool,
    RuntimeToolCall,
    RuntimeUsage,
    ToolInvocationContext,
    reject_sensitive_fields,
)
from agents_factory.modules.runtime.errors import AgentRuntimeError as AgentRuntimeError
from agents_factory.modules.runtime.errors import (
    RuntimeToolLimitExceeded as RuntimeToolLimitExceeded,
)
from agents_factory.modules.runtime.metering import RuntimeMeter, count


class _SdkRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        input_items: list[dict[str, object]],
        *,
        max_turns: int,
        run_config: RunConfig,
    ) -> object: ...


class _DefaultSdkRunner:
    async def run(
        self,
        agent: Agent[Any],
        input_items: list[dict[str, object]],
        *,
        max_turns: int,
        run_config: RunConfig,
    ) -> object:
        # The durable queue owns retries. Hidden HTTP/SDK retries would bypass
        # tenant attempt limits and merge distinct billable occurrences.
        async with AsyncOpenAI(max_retries=0) as client:
            run_config.model_provider = OpenAIProvider(
                openai_client=client, use_responses=True
            )
            return await Runner.run(
                agent,
                cast(Any, input_items),
                max_turns=max_turns,
                run_config=run_config,
            )


class OpenAIAgentsRuntime:
    def __init__(
        self,
        *,
        runner: _SdkRunner | None = None,
        require_api_key: bool = True,
    ) -> None:
        self._runner = runner or _DefaultSdkRunner()
        self._require_api_key = require_api_key

    async def run(self, turn: AgentTurnInput) -> AgentTurnResult:
        if self._require_api_key and not os.environ.get("OPENAI_API_KEY"):
            raise AgentRuntimeError("openai_api_key_missing", retryable=False)

        tool_calls: list[RuntimeToolCall] = []
        meter = RuntimeMeter(turn)
        sdk_tools: list[Tool] = (
            [
                self._to_sdk_tool(
                    turn=turn, tool=tool, tool_calls=tool_calls, meter=meter
                )
                for tool in turn.tools
            ]
            if meter.max_tools > 0
            else []
        )
        model_settings = ModelSettings(
            max_tokens=turn.agent_spec.limits.max_output_tokens,
            reasoning=Reasoning(
                effort=turn.agent_spec.model.reasoning_effort,
            ),
            parallel_tool_calls=False,
            store=False,
            include_usage=True,
            preserve_raw_usage=True,
            retry=ModelRetrySettings(max_retries=0),
            timeout=turn.agent_spec.limits.timeout_seconds,
        )
        agent = Agent[Any](
            name="Agents Factory Customer Service",
            instructions=turn.agent_spec.instructions,
            model=turn.agent_spec.model.model,
            model_settings=model_settings,
            tools=sdk_tools,
            handoffs=[],
            hooks=meter,
        )
        run_config = RunConfig(
            workflow_name="Agents Factory Customer Service Turn",
            group_id=str(turn.trace.conversation_id),
            trace_include_sensitive_data=False,
            trace_metadata=turn.trace.as_sdk_metadata(),
            call_model_input_filter=meter.filter_input,
            tool_execution=ToolExecutionConfig(max_function_tool_concurrency=1),
        )
        input_items: list[dict[str, object]] = [
            {"role": message.role, "content": message.text} for message in turn.messages
        ]
        try:
            async with asyncio.timeout(turn.agent_spec.limits.timeout_seconds):
                raw_result = await self._runner.run(
                    agent,
                    input_items,
                    max_turns=max(1, meter.max_tools + 1),
                    run_config=run_config,
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise AgentRuntimeError("runtime_timeout", retryable=True) from None
        except (AgentRuntimeError, JobDeferred):
            raise
        except Exception as error:
            # The SDK wraps local tool exceptions in UserError. Preserve our
            # typed terminal signal, never infer retry policy from error text.
            cause: BaseException | None = error.__cause__
            for _ in range(8):
                if isinstance(cause, (AgentRuntimeError, JobDeferred)):
                    raise cause from None
                if cause is None:
                    break
                cause = cause.__cause__
            raise AgentRuntimeError("runtime_provider_error", retryable=True) from None
        finally:
            await meter.unfinished_request()

        output = getattr(raw_result, "final_output", None)
        if not isinstance(output, str) or not output.strip():
            raise AgentRuntimeError("runtime_invalid_output", retryable=False)
        usage = getattr(getattr(raw_result, "context_wrapper", None), "usage", None)
        provider_response_id = getattr(raw_result, "last_response_id", None)
        return AgentTurnResult(
            output_text=output,
            tool_calls=tuple(tool_calls),
            usage=meter.aggregate() if meter.responses else _map_usage(usage),
            provider_response_id=(
                provider_response_id if isinstance(provider_response_id, str) else None
            ),
        )

    def _to_sdk_tool(
        self,
        *,
        turn: AgentTurnInput,
        tool: RuntimeTool,
        tool_calls: list[RuntimeToolCall],
        meter: RuntimeMeter,
    ) -> FunctionTool:
        async def invoke(_context: object, arguments_json: str) -> object:
            if turn.admission:
                await turn.admission.before_tool()
            started_at = meter.start_tool()
            try:
                return await execute(arguments_json)
            finally:
                await meter.finish_tool(tool.name, started_at)

        async def execute(arguments_json: str) -> object:
            try:
                arguments = json.loads(arguments_json)
            except json.JSONDecodeError:
                raise ValueError("runtime tool arguments are invalid") from None
            if not isinstance(arguments, dict):
                raise ValueError("runtime tool arguments must be an object")
            reject_sensitive_fields(arguments)
            invocation_context = ToolInvocationContext(
                tenant_id=turn.trace.tenant_id,
                conversation_id=turn.trace.conversation_id,
                inbound_message_id=turn.trace.inbound_message_id,
                correlation_id=turn.trace.correlation_id,
            )
            output = await tool.handler(invocation_context, arguments)
            reject_sensitive_fields(output)
            try:
                normalized_output = json.loads(json.dumps(output, allow_nan=False))
            except (TypeError, ValueError):
                raise ValueError("runtime tool output must be JSON") from None
            tool_calls.append(
                RuntimeToolCall(
                    tool_name=tool.name,
                    arguments=arguments,
                    output=normalized_output,
                )
            )
            return normalized_output

        schema = cast(
            dict[str, Any],
            json.loads(json.dumps(dict(tool.input_schema), allow_nan=False)),
        )
        return FunctionTool(
            name=_sdk_tool_name(tool.name),
            description=(f"Business operation `{tool.name}`. {tool.description}"),
            params_json_schema=schema,
            on_invoke_tool=invoke,
            strict_json_schema=True,
            timeout_seconds=turn.agent_spec.limits.timeout_seconds,
        )


def _sdk_tool_name(internal_name: str) -> str:
    return internal_name.replace(".", "__")


def _map_usage(usage: object) -> RuntimeUsage:
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return RuntimeUsage(
        requests=count(usage, "requests"),
        input_tokens=count(usage, "input_tokens"),
        cached_input_tokens=count(input_details, "cached_tokens"),
        output_tokens=count(usage, "output_tokens"),
        reasoning_tokens=count(output_details, "reasoning_tokens"),
        total_tokens=count(usage, "total_tokens"),
    )
