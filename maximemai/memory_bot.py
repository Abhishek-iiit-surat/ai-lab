"""The only file that imports the Synap SDK.

Wraps ingestion (conversation.record_message + memories.create) and scoped
retrieval (customer-scope "company" context vs user-scope "personal" context),
plus a thin retry: one retry on SynapTransientError, fail fast on
SynapPermanentError (the SDK's own transport layer already retries transient
errors internally with backoff+jitter -- this extra retry is a second, cheap
safety net at the call-site level, not a replacement for that).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from maximem_synap import (
    MaximemSynapSDK,
    SynapPermanentError,
    SynapTransientError,
)


@dataclass
class FactDiag:
    """One fact/preference plus the metadata needed to judge retrieval quality."""

    content: str
    confidence: float
    extracted_at: str
    temporal_category: str = ""
    valid_until: str = ""


@dataclass
class ScopedContext:
    """Flattened view of a ContextResponse: just the text an LLM prompt needs."""

    company_facts: List[str] = field(default_factory=list)
    personal_preferences: List[str] = field(default_factory=list)
    # Diagnostics: same items as above, kept alongside their confidence/
    # timestamp/temporal metadata so a caller can inspect *why* something was
    # or wasn't retrieved, instead of just seeing the flattened text.
    company_facts_diag: List[FactDiag] = field(default_factory=list)
    personal_preferences_diag: List[FactDiag] = field(default_factory=list)
    source: str = ""  # "cache" or "cloud" -- from ResponseMetadata
    retrieved_at: str = ""


class MemoryBot:
    def __init__(self, api_key: str):
        # instance_id is left for the SDK to auto-resolve from the API key.
        self._sdk = MaximemSynapSDK(api_key=api_key)
        self._initialized = False

    async def initialize(self) -> None:
        if not self._initialized:
            await self._sdk.initialize()
            self._initialized = True

    async def shutdown(self) -> None:
        if self._initialized:
            await self._sdk.shutdown()
            self._initialized = False

    async def _with_retry(self, coro_fn, *args, **kwargs):
        try:
            return await coro_fn(*args, **kwargs)
        except SynapTransientError:
            return await coro_fn(*args, **kwargs)
        except SynapPermanentError:
            raise

    @staticmethod
    def _diag_facts(items) -> List[FactDiag]:
        diags = []
        for item in items:
            diags.append(
                FactDiag(
                    content=item.content,
                    confidence=getattr(item, "confidence", None)
                    if getattr(item, "confidence", None) is not None
                    else getattr(item, "strength", 0.0),
                    extracted_at=str(getattr(item, "extracted_at", "") or ""),
                    temporal_category=getattr(item, "temporal_category", "") or "",
                    valid_until=str(getattr(item, "valid_until", "") or ""),
                )
            )
        return diags

    async def company_context(
        self, customer_id: str, search_queries: List[str], max_results: int = 10
    ) -> ScopedContext:
        """Customer-scope facts: shared across every employee at this company."""
        response = await self._with_retry(
            self._sdk.customer.context.fetch,
            customer_id=customer_id,
            search_query=search_queries or None,
            max_results=max_results,
        )
        return ScopedContext(
            company_facts=[fact.content for fact in response.facts],
            company_facts_diag=self._diag_facts(response.facts),
            source=response.metadata.source,
            retrieved_at=str(response.metadata.retrieved_at),
        )

    async def personal_context(
        self, user_id: str, customer_id: str, search_queries: List[str], max_results: int = 10
    ) -> ScopedContext:
        """User-scope facts/preferences: private to this one employee."""
        response = await self._with_retry(
            self._sdk.user.context.fetch,
            user_id=user_id,
            customer_id=customer_id,
            search_query=search_queries or None,
            max_results=max_results,
        )
        return ScopedContext(
            company_facts=[fact.content for fact in response.facts],
            personal_preferences=[pref.content for pref in response.preferences],
            company_facts_diag=self._diag_facts(response.facts),
            personal_preferences_diag=self._diag_facts(response.preferences),
            source=response.metadata.source,
            retrieved_at=str(response.metadata.retrieved_at),
        )

    async def cross_session_summary(
        self, user_id: str, customer_id: str, last_n_conversations: int = 5
    ) -> Dict[str, Any]:
        """Cross-session recall: summaries of this user's past conversations,
        fetched via context_mode="conversation-summary" -- a genuinely
        different code path from company_context/personal_context (which
        only ever see the *current* conversation's relevance window). This
        is Synap's dedicated "what happened last time" lookup, independent
        of conversation_id.
        """
        response = await self._with_retry(
            self._sdk.user.context.fetch,
            user_id=user_id,
            customer_id=customer_id,
            context_mode="conversation-summary",
            include_profile=True,
            last_n_conversations=last_n_conversations,
        )
        conversations = []
        for conv in response.conversations or []:
            conversations.append(
                {
                    "conversation_id": conv.conversation_id,
                    "started_at": str(conv.started_at or ""),
                    "message_count": conv.message_count,
                    "summary_status": conv.summary_status,
                    "overview": conv.overview_text(),
                    "outcome": conv.outcome_text(),
                }
            )
        profile_attrs = {}
        if response.profile is not None:
            for name, attr in response.profile.attributes.items():
                profile_attrs[name] = attr.value
        return {
            "conversations": conversations,
            "profile_attributes": profile_attrs,
            "profile_overview": response.profile.overview if response.profile else None,
        }

    async def ask(
        self,
        user_id: str,
        customer_id: str,
        conversation_id: str,
        user_message: str,
        reply: str,
        wait_for_ingestion: bool = False,
    ) -> None:
        """Registers a turn and persists it so Synap can extract new facts/preferences.

        `reply` is generated by the caller (via llm.generate_reply) using context
        already fetched through company_context/personal_context -- this method only
        handles recording the turn, not producing the response.
        """
        await self._with_retry(
            self._sdk.conversation.record_message,
            conversation_id=conversation_id,
            role="user",
            content=user_message,
            user_id=user_id,
            customer_id=customer_id,
        )
        await self._with_retry(
            self._sdk.conversation.record_message,
            conversation_id=conversation_id,
            role="assistant",
            content=reply,
            user_id=user_id,
            customer_id=customer_id,
        )

        create_response = await self._with_retry(
            self._sdk.memories.create,
            document=f"User: {user_message}\nAssistant: {reply}",
            user_id=user_id,
            customer_id=customer_id,
        )

        if wait_for_ingestion:
            # Blocks until extraction finishes -- fine for a demo proving the
            # shared/private split; a production app would not block a
            # user-facing request on this and needs a plan for "not ready yet".
            await self._sdk.memories.wait_for_completion(create_response.ingestion_id)
