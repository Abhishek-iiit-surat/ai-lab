"""Generates replies. Uses a real OpenAI call if OPENAI_API_KEY is configured,
otherwise falls back to a template so the memory demo works either way — the
point of this project is proving Synap's scoping, not the LLM call itself.
"""
from __future__ import annotations

from typing import List, Optional

_SYSTEM_PROMPT = (
    "You are the CloudSync support and onboarding assistant. Answer the "
    "employee's question using the company facts and personal preferences "
    "provided below, if any are relevant. Do not invent facts that aren't given."
)


async def generate_reply(
    user_message: str,
    company_facts: List[str],
    personal_preferences: List[str],
    openai_api_key: Optional[str] = None,
) -> str:
    if openai_api_key:
        return await _generate_with_openai(
            user_message, company_facts, personal_preferences, openai_api_key
        )
    return _generate_template_reply(user_message, company_facts, personal_preferences)


async def _generate_with_openai(
    user_message: str,
    company_facts: List[str],
    personal_preferences: List[str],
    openai_api_key: str,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)
    context_block = _format_context_block(company_facts, personal_preferences)

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if context_block:
        messages.append({"role": "system", "content": context_block})
    messages.append({"role": "user", "content": user_message})

    response = await client.chat.completions.create(model="gpt-4o-mini", messages=messages)
    return response.choices[0].message.content.strip()


def _generate_template_reply(
    user_message: str,
    company_facts: List[str],
    personal_preferences: List[str],
) -> str:
    lines = []

    terse = any("terse" in p.lower() or "short" in p.lower() for p in personal_preferences)

    if not terse:
        lines.append("Thanks for reaching out!")

    if company_facts:
        lines.append("Here's what we have on file for your company:")
        for fact in company_facts:
            lines.append(f"  - {fact}")
    else:
        lines.append(
            "I don't have any company-wide setup facts on file yet for this question."
        )

    if not terse and personal_preferences:
        lines.append("(Noted your preferences for how I should respond.)")

    return "\n".join(lines)


def _format_context_block(company_facts: List[str], personal_preferences: List[str]) -> str:
    parts = []
    if company_facts:
        parts.append("Company facts:\n" + "\n".join(f"- {f}" for f in company_facts))
    if personal_preferences:
        parts.append("This user's personal preferences:\n" + "\n".join(f"- {p}" for p in personal_preferences))
    return "\n\n".join(parts)
