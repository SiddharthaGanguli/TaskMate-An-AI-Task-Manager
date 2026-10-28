"""Adapt Ollama's chat API to the small interface our agent already uses."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx


class OllamaError(Exception):
    """A local model request failed, with a message we can show in the terminal."""


class OllamaClient:
    def __init__(self, host="http://localhost:11434", timeout=180, transport=None):
        self.http = httpx.Client(base_url=host.rstrip("/") + "/", timeout=timeout,
                                 transport=transport, trust_env=False)
        # TaskAgent only uses responses.create; this is not a full OpenAI client.
        self.responses = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def create(self, *, model, instructions, tools, input, **unused):
        messages = [{"role": "system", "content": instructions}]
        call_names = {}
        for item in input:
            if isinstance(item, dict):
                if item.get("type") == "function_call_output":
                    messages.append({"role": "tool", "tool_name": call_names[item["call_id"]],
                                     "content": item["output"]})
                else:
                    messages.append(item)
            elif item.type == "ollama_message":
                messages.append(item.message)
            elif item.type == "function_call":
                call_names[item.call_id] = item.name

        local_tools = [{"type": "function", "function": {
            "name": tool["name"], "description": tool["description"],
            "parameters": tool["parameters"],
        }} for tool in tools]
        try:
            response = self.http.post("api/chat", json={
                "model": model, "messages": messages, "tools": local_tools, "stream": False,
            })
            response.raise_for_status()
        except httpx.TimeoutException:
            raise OllamaError("The local model timed out. Try a smaller model or increase OLLAMA_TIMEOUT.") from None
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise OllamaError(f"Model or endpoint not found. Run: ollama pull {model}. Also check OLLAMA_HOST.") from None
            raise OllamaError(f"Ollama returned HTTP {error.response.status_code}. "
                              "Check its logs and choose a model that supports tools.") from None
        except httpx.RequestError:
            raise OllamaError("Could not reach Ollama. Open the Ollama app or run ollama serve, then check OLLAMA_HOST.") from None

        try:
            data = response.json()
            if data.get("error"):
                raise ValueError("Ollama returned an error.")
            message = data["message"]
            if message.get("role") != "assistant" or not isinstance(message.get("content", ""), str):
                raise ValueError("Invalid assistant message.")
            output = [SimpleNamespace(type="ollama_message", message=message)]
            for call in message.get("tool_calls") or []:
                function = call["function"]
                if not isinstance(function["name"], str) or not isinstance(function["arguments"], dict):
                    raise ValueError("Invalid tool call.")
                output.append(SimpleNamespace(
                    type="function_call", name=function["name"],
                    arguments=json.dumps(function["arguments"]), call_id=uuid4().hex,
                ))
            return SimpleNamespace(output=output, output_text=message.get("content", ""))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise OllamaError("Ollama returned an invalid response. Try a model with tool-calling support.") from None
