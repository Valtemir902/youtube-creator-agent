from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ai.runtime import AIRuntime
from ai.settings import AISettings
from desktop_local_server import app_data_dir
from elite_v2_orchestrator import AIProposal, AIProvider, CommandIntent, classify_command


class EliteV2AIError(RuntimeError):
    pass


def _fact(source: str, name: str, value: Any) -> dict[str, Any]:
    return {"source": source, "name": name, "value": value}


def _internal_proposal(command: str, context: dict[str, Any]) -> AIProposal:
    intent = classify_command(command)
    facts: list[dict[str, Any]] = []
    for key in ("video_id", "title", "description", "tags", "views", "privacy_status"):
        if key in context:
            facts.append(_fact(str(context.get("source") or "local_context"), key, context.get(key)))
    if not facts:
        facts.append(_fact("user_command", "command", command))

    proposed: dict[str, Any] = {}
    title = str(context.get("title") or "").strip()
    description = str(context.get("description") or "")
    tags = list(context.get("tags") or [])
    if intent is CommandIntent.PROPOSE_METADATA:
        proposed = {
            "title": title,
            "description": description,
            "tags": tags,
            "diagnostic": {
                "title_length": len(title),
                "description_length": len(description),
                "tag_count": len(tags),
            },
        }
    elif intent is CommandIntent.PROPOSE_PLAYLIST:
        proposed = {
            "playlist_strategy": "group_by_topic",
            "candidate_video_id": context.get("video_id"),
            "title_seed": title or None,
        }
    elif intent is CommandIntent.READ_ANALYZE:
        proposed = {
            "analysis_only": True,
            "focus": "official_facts_and_metadata",
        }
    else:
        proposed = {
            "plan_only": True,
            "intent": intent.value,
        }
    proposal = AIProposal(
        provider=AIProvider.INTERNAL,
        model="elite-v2-rules",
        intent=intent,
        facts=facts,
        proposed_changes=proposed,
        confidence=None,
        limitations=["Motor interno não inventa métricas ausentes e não executa escrita."],
        requires_write_gateway=True,
    )
    proposal.validate()
    return proposal


def _extract_response_text(response: Any) -> str:
    for attr in ("text", "content", "output_text"):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(response, dict):
        for key in ("text", "content", "output_text"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(response or "").strip()


def _parse_model_proposal(
    *,
    provider: AIProvider,
    model: str,
    intent: CommandIntent,
    text: str,
    context: dict[str, Any],
) -> AIProposal:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except Exception as exc:
        raise EliteV2AIError("A IA não retornou JSON estruturado; nenhuma proposta foi liberada.") from exc
    if not isinstance(payload, dict):
        raise EliteV2AIError("Resposta estruturada da IA deve ser um objeto JSON.")
    changes = payload.get("proposed_changes")
    if not isinstance(changes, dict) or not changes:
        raise EliteV2AIError("A IA não retornou proposed_changes válidas.")
    facts = payload.get("facts")
    if not isinstance(facts, list) or not facts:
        facts = [
            _fact(str(context.get("source") or "provided_context"), key, value)
            for key, value in context.items()
            if key not in {"source"}
        ]
    normalized_facts = []
    for row in facts:
        if isinstance(row, dict):
            normalized_facts.append({**row, "source": str(row.get("source") or context.get("source") or "provided_context")})
    confidence = payload.get("confidence")
    if confidence is not None:
        confidence = max(0.0, min(1.0, float(confidence)))
    proposal = AIProposal(
        provider=provider,
        model=model,
        intent=intent,
        facts=normalized_facts,
        proposed_changes=changes,
        confidence=confidence,
        limitations=[str(item) for item in (payload.get("limitations") or [])][:12],
        requires_write_gateway=True,
    )
    proposal.validate()
    return proposal


class EliteV2AIRuntime:
    """Explicit AI proposal engine. It never applies YouTube mutations."""

    def __init__(self, runtime: AIRuntime | None = None) -> None:
        path = Path(app_data_dir()) / "ai-settings.json"
        self.runtime = runtime or AIRuntime(path)

    def statuses(self) -> list[dict[str, Any]]:
        settings = self.runtime.load_settings()
        provider_name = str(settings.provider or "").strip().lower()
        model = str(settings.model or "").strip() or None
        return [
            {
                "provider": AIProvider.LOCAL.value,
                "available": provider_name == "ollama" and bool(model),
                "model": model if provider_name == "ollama" else None,
                "external": False,
                "reason": None if provider_name == "ollama" and model else "Configure Ollama/modelo local nas configurações de IA.",
            },
            {
                "provider": AIProvider.API.value,
                "available": bool(provider_name and provider_name != "ollama" and model),
                "model": model if provider_name and provider_name != "ollama" else None,
                "external": True,
                "reason": None if provider_name and provider_name != "ollama" and model else "Configure um provedor de API e modelo.",
            },
            {
                "provider": AIProvider.CHATGPT.value,
                "available": False,
                "model": None,
                "external": True,
                "reason": "ChatGPT atua pelo plugin/conector fora do EXE; o desktop não reutiliza credenciais da conversa.",
            },
            {
                "provider": AIProvider.INTERNAL.value,
                "available": True,
                "model": "elite-v2-rules",
                "external": False,
                "reason": None,
            },
        ]

    def propose(self, *, provider: AIProvider, command: str, context: dict[str, Any]) -> AIProposal:
        command = " ".join(str(command or "").split())
        if not command:
            raise ValueError("comando é obrigatório")
        if provider is AIProvider.INTERNAL:
            return _internal_proposal(command, context)
        if provider is AIProvider.CHATGPT:
            raise EliteV2AIError("ChatGPT deve ser usado pelo plugin/conector; nenhuma execução externa automática foi iniciada.")

        settings = self.runtime.load_settings()
        configured = str(settings.provider or "").strip().lower()
        if provider is AIProvider.LOCAL and configured != "ollama":
            raise EliteV2AIError("IA Local selecionada, mas Ollama não está configurado como provedor ativo.")
        if provider is AIProvider.API and configured == "ollama":
            raise EliteV2AIError("IA por API selecionada, mas o provedor ativo é local.")
        model = str(settings.model or "").strip()
        if not model:
            raise EliteV2AIError("Nenhum modelo está configurado para o provedor selecionado.")

        intent = classify_command(command)
        prompt = {
            "instruction": "Return ONLY one JSON object. Never claim to execute changes. proposed_changes must contain only a proposal. facts must include source for every fact. Do not invent metrics.",
            "command": command,
            "intent": intent.value,
            "context": context,
            "schema": {
                "facts": [{"source": "string", "name": "string", "value": "any"}],
                "proposed_changes": {"field": "value"},
                "confidence": "0..1 or null",
                "limitations": ["string"],
            },
        }
        response = self.runtime.generate(
            [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            settings=AISettings(
                provider=configured,
                model=model,
                base_url=str(getattr(settings, "base_url", "") or ""),
                remember_api_key=bool(getattr(settings, "remember_api_key", True)),
                auto_rotate_keys=bool(getattr(settings, "auto_rotate_keys", False)),
            ),
            model=model,
            temperature=0.1,
            max_output_tokens=1200,
            response_format="json",
        )
        return _parse_model_proposal(
            provider=provider,
            model=model,
            intent=intent,
            text=_extract_response_text(response),
            context=context,
        )


def proposal_payload(proposal: AIProposal) -> dict[str, Any]:
    payload = asdict(proposal)
    payload["provider"] = proposal.provider.value
    payload["intent"] = proposal.intent.value
    payload["youtube_write_performed"] = False
    payload["requires_explicit_approval"] = True
    return payload
