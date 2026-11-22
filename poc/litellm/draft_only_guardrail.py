"""Gateway rule (level 3 in the report): agents may write visit notes only as drafts.

A LiteLLM custom guardrail (open source) that runs before every MCP tool call. A call to
demo_crm's draft_visit_note with any status other than "draft" stops here, before it reaches
the MCP server. demo-crm enforces the same rule on its own (act 6), so the two layers are
independent.
"""
import json
import re
from typing import Final

from fastapi import HTTPException
from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.guardrails import GuardrailEventHooks

# tool name (with or without the server prefix) -> argument -> required pattern
RULES: Final = {"draft_visit_note": {"status": re.compile(r"^draft$")}}


def _tool_and_args(data: dict) -> tuple[str, dict]:
    name = data.get("mcp_tool_name") or data.get("name") or ""
    args = data.get("mcp_arguments") or data.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return str(name), args if isinstance(args, dict) else {}


class DraftOnlyGuardrail(CustomGuardrail):
    def __init__(self, **kwargs):
        super().__init__(supported_event_hooks=[GuardrailEventHooks.pre_mcp_call], **kwargs)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type: str):
        name, args = _tool_and_args(data)
        bare = name.split("-", 1)[-1].split("/")[-1]       # demo_crm-draft_visit_note, demo_crm/draft_visit_note
        for arg, pattern in RULES.get(bare, {}).items():
            value = str(args.get(arg, "draft" if arg == "status" else ""))
            if not pattern.match(value):
                verbose_proxy_logger.warning("draft-only guardrail blocked %s %s=%s for %s",
                                             bare, arg, value, getattr(user_api_key_dict, "team_id", None))
                raise HTTPException(status_code=403, detail={
                    "error": "Violated guardrail policy",
                    "guardrail": self.guardrail_name,
                    "detection_message": f"{bare}: {arg}={value!r} is not allowed; agents write notes only as drafts",
                })
        return data
