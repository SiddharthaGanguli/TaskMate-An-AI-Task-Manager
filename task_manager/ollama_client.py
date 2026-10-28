"""Adapt Ollama's chat API to the small interface our agent already uses."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx


class OllamaError(Exception):
    """A local model request failed, with a message we can show in the terminal."""


def recover_tool_plan(content, tools):
    """Accept a complete JSON tool plan, never JSON embedded in ordinary prose."""
    text = content.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    try:
        plan = json.loads(text)
    except ValueError:
        return []
    if isinstance(plan, dict):
        plan = [plan]
    if not isinstance(plan, list) or not plan or len(plan) > 50:
        return []
    names = {tool["name"] for tool in tools}
    calls = []
    for item in plan:
        if not isinstance(item, dict) or set(item) != {"function", "arguments"}:
            return []
        if not isinstance(item["function"], str) or item["function"] not in names:
            return []
        if not isinstance(item["arguments"], dict):
            return []
        calls.append({"function": {"name": item["function"], "arguments": item["arguments"]}})
    return calls


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

    def _request(self, payload):
        model = payload["model"]
        try:
            response = self.http.post("api/chat", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise OllamaError("The local model timed out. Try a smaller model or increase OLLAMA_TIMEOUT.") from None
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise OllamaError(f"Model or endpoint not found. Run: ollama pull {model}. Also check OLLAMA_HOST.") from None
            raise OllamaError(f"Ollama returned HTTP {error.response.status_code}. "
                              "Check its logs and choose a model that supports tools.") from None
        except httpx.RequestError:
            raise OllamaError("Could not reach Ollama. Open the Ollama app or run ollama serve, then check OLLAMA_HOST.") from None
        except ValueError:
            raise OllamaError("Ollama returned invalid JSON.") from None

    def _repair_plan(self, model, messages, message, tools):
        # Ask the model to name its intended tools. I don't want to guess a
        # write operation from anonymous argument blocks.
        choices = [{
            "type": "object", "additionalProperties": False,
            "properties": {"function": {"const": tool["name"], "type": "string"},
                           "arguments": tool["parameters"]},
            "required": ["function", "arguments"],
        } for tool in tools]
        schema = {"type": "array", "minItems": 0, "maxItems": 50, "items": {"anyOf": choices}}
        data = self._request({
            "model": model, "stream": False,
            "messages": [*messages, message, {"role": "user", "content":
                "Your previous reply did not execute any tools. Read the original user request again, "
                "rather than copying mistakes in your previous reply. Convert the intended actions into "
                "a JSON array of objects with function and arguments, matching the supplied schema. "
                "Use the original user's request and dates. Include the requested list operation. "
                "Use null for priority and search when listing without those filters. "
                "Do not add actions the user did not request. Return [] if the user only wants conversation "
                "or clarification is needed. Schema: " + json.dumps(schema)}],
            "format": schema,
        })
        return recover_tool_plan(data["message"]["content"], tools)

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
        data = self._request({
            "model": model, "messages": messages, "tools": local_tools, "stream": False,
        })

        try:
            if data.get("error"):
                raise ValueError("Ollama returned an error.")
            message = data["message"]
            if message.get("role") != "assistant" or not isinstance(message.get("content", ""), str):
                raise ValueError("Invalid assistant message.")
            # Some local models write their first tool plan as text. Convert only
            # an exact plan at the start of a user turn. Never replay a plan after
            # results, when an action might already have succeeded.
            if not message.get("tool_calls") and input and isinstance(input[-1], dict) and input[-1].get("role") == "user":
                recovered = recover_tool_plan(message.get("content", ""), tools)
                content = message.get("content", "").strip()
                if not recovered:
                    recovered = self._repair_plan(model, messages, message, tools)
                    if not recovered and (content.startswith("[tool_call]") or '"arguments"' in content or '"parameters"' in content):
                        raise ValueError("The model did not produce a valid tool plan.")
                if recovered:
                    message = {**message, "content": "", "tool_calls": recovered}
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
