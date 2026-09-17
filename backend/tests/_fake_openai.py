"""Shared fakes for the OpenAI chat-completions shape, used by
test_stage4_generate_email.py and test_agent_loop.py so a real API key/network
call is never needed to exercise the tool-calling loop logic.

Mirrors: response.choices[0].message.{content,tool_calls}, where each
tool_call has .id, .function.name, .function.arguments (a JSON string).
"""
from __future__ import annotations

import json


class FakeFunction:
    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.arguments = json.dumps(arguments)


class FakeToolCall:
    def __init__(self, name: str, arguments: dict, id_: str = "call_1") -> None:
        self.id = id_
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, tool_calls: list[FakeToolCall] | None = None, content: str | None = None) -> None:
        self.tool_calls = tool_calls
        self.content = content


class FakeChoice:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message


class FakeUsage:
    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class FakeResponse:
    def __init__(self, tool_calls: list[FakeToolCall] | None = None, content: str | None = None) -> None:
        self.choices = [FakeChoice(FakeMessage(tool_calls=tool_calls, content=content))]
        self.usage = FakeUsage()


class FakeCompletions:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if not self._responses:
            raise AssertionError("FakeCompletions.create called more times than scripted")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeChat:
    def __init__(self, responses: list) -> None:
        self.completions = FakeCompletions(responses)


class FakeClient:
    def __init__(self, responses: list) -> None:
        self.chat = FakeChat(responses)
