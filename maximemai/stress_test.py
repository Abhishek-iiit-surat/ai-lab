"""Scripted, non-interactive stress test of Synap covering:

  1. Multiple users at the same company (Maria=admin, Jordan=employee) --
     company-fact sharing + personal-preference isolation.
  2. A second company entirely (Globex/Priya) -- cross-customer isolation.
  3. Long multi-turn growth for Maria (20+ turns) with callback questions to
     early facts, to see if recall degrades as the store grows.
  4. Conflicting/updated facts (Okta -> Azure AD) -- does retrieval return the
     old fact, the new one, or both, and what do extracted_at/temporal_category
     say about it.
  5. Noise/distractor burial -- 20 filler messages, then re-ask a real question.
  6. Cross-conversation / cross-session persistence -- new conversation_id
     (same user), then re-fetch context AND call context_mode="conversation-summary"
     to see if Synap recalls prior sessions independent of conversation_id.

No input() -- everything scripted so it can run unattended. Every step's raw
result is appended to `results` and dumped as JSON at the end, plus a running
human-readable log to stdout.

Run: python stress_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import config
import llm
from memory_bot import MemoryBot

CUSTOMER_A = "acme_corp"
CUSTOMER_B = "globex_inc"

MARIA = "maria_chen"     # Acme admin
JORDAN = "jordan_lee"    # Acme employee
PRIYA = "priya_sharma"   # Globex employee (different company entirely)

results = []


def log(msg: str) -> None:
    print(msg)


def record(section: str, **data) -> None:
    results.append({"section": section, **data})


async def turn(bot, cfg, user_id, customer_id, conversation_id, message, *, label=""):
    """One full turn: fetch context, generate reply, ingest. Returns the raw ScopedContext objects."""
    company_ctx = await bot.company_context(customer_id, [message])
    personal_ctx = await bot.personal_context(user_id, customer_id, [message])
    reply = await llm.generate_reply(
        message, company_ctx.company_facts, personal_ctx.personal_preferences,
        openai_api_key=cfg.openai_api_key,
    )
    await bot.ask(
        user_id=user_id, customer_id=customer_id, conversation_id=conversation_id,
        user_message=message, reply=reply,
    )
    log(f"  [{label or user_id}] > {message}")
    log(f"      company_facts={company_ctx.company_facts}")
    log(f"      personal_preferences={personal_ctx.personal_preferences}")
    log(f"      bot> {reply[:120]}")
    return company_ctx, personal_ctx, reply


def diag_dump(ctx):
    return {
        "source": ctx.source,
        "retrieved_at": ctx.retrieved_at,
        "company_facts": [
            {"content": d.content, "confidence": d.confidence, "extracted_at": d.extracted_at,
             "temporal_category": d.temporal_category, "valid_until": d.valid_until}
            for d in ctx.company_facts_diag
        ],
        "personal_preferences": [
            {"content": d.content, "confidence": d.confidence, "extracted_at": d.extracted_at,
             "temporal_category": d.temporal_category, "valid_until": d.valid_until}
            for d in ctx.personal_preferences_diag
        ],
    }


async def main() -> None:
    cfg = config.load_config()
    bot = MemoryBot(api_key=cfg.synap_api_key)
    await bot.initialize()

    try:
        # ============================================================
        # SECTION 1 -- multi-user sharing + isolation baseline (Acme)
        # ============================================================
        log("\n" + "=" * 70)
        log("SECTION 1: Multi-user sharing + isolation (Acme: Maria + Jordan)")
        log("=" * 70)
        conv_maria = str(uuid.uuid4())
        conv_jordan = str(uuid.uuid4())

        _, _, _ = await turn(
            bot, cfg, MARIA, CUSTOMER_A, conv_maria,
            "We use Okta for SSO and I'm the IT admin, Maria Chen. Also, just give me short answers, skip pleasantries.",
            label="Maria",
        )
        await asyncio.sleep(2)  # brief grace period for async extraction

        jordan_company, jordan_personal, _ = await turn(
            bot, cfg, JORDAN, CUSTOMER_A, conv_jordan,
            "How do I set up single sign-on for our team?",
            label="Jordan",
        )
        sharing_ok = any("okta" in f.lower() for f in jordan_company.company_facts)
        isolation_ok = not any("terse" in p.lower() or "short" in p.lower() for p in jordan_personal.personal_preferences)
        record("multi_user_sharing_isolation", sharing_ok=sharing_ok, isolation_ok=isolation_ok,
               jordan_company_ctx=diag_dump(jordan_company), jordan_personal_ctx=diag_dump(jordan_personal))
        log(f"  RESULT: company fact shared to Jordan={sharing_ok}, Maria's preference stayed private={isolation_ok}")

        # ============================================================
        # SECTION 2 -- second company entirely: cross-customer isolation
        # ============================================================
        log("\n" + "=" * 70)
        log("SECTION 2: Cross-customer isolation (Globex: Priya, unrelated company)")
        log("=" * 70)
        conv_priya = str(uuid.uuid4())
        _, _, _ = await turn(
            bot, cfg, PRIYA, CUSTOMER_B, conv_priya,
            "We use Azure AD for SSO here at Globex, and I prefer detailed explanations, not short answers.",
            label="Priya",
        )
        await asyncio.sleep(2)

        priya_company, priya_personal, _ = await turn(
            bot, cfg, PRIYA, CUSTOMER_B, conv_priya,
            "What SSO provider do we use?",
            label="Priya",
        )
        # cross-customer leak check: Acme's Okta fact must never appear for Globex
        leaked_okta = any("okta" in f.lower() for f in priya_company.company_facts)
        record("cross_customer_isolation", leaked_okta=leaked_okta,
               priya_company_ctx=diag_dump(priya_company), priya_personal_ctx=diag_dump(priya_personal))
        log(f"  RESULT: Acme's Okta fact leaked into Globex's context={leaked_okta} (should be False)")

        # ============================================================
        # SECTION 3 -- long multi-turn growth for Maria, with callbacks
        # ============================================================
        log("\n" + "=" * 70)
        log("SECTION 3: Long multi-turn growth (Maria, Acme) + callback recall")
        log("=" * 70)
        seed_facts = [
            "Our support hours are 9am to 6pm IST, Monday through Friday.",
            "Our billing contact is finance@acme.com, please loop them in on invoice questions.",
            "We're on the Enterprise plan, renewed in January.",
            "Our primary data region is ap-south-1, that's a compliance requirement for us.",
        ]
        seed_prefs = [
            "Also, always give me bullet points instead of paragraphs.",
            "I'm usually only online in the mornings, IST time.",
            "Don't CC me on routine notifications, only escalations.",
            "I prefer email over Slack for anything that needs a paper trail.",
        ]
        filler_qs = [
            "How do most companies handle SSO rollouts?",
            "What's a good rollout timeline for enabling SSO org-wide?",
            "Can you give me a checklist for SSO migration risks?",
            "What should I communicate to employees before the SSO switch?",
        ]
        for msg in seed_facts + seed_prefs:
            await turn(bot, cfg, MARIA, CUSTOMER_A, conv_maria, msg, label="Maria/seed")
        await asyncio.sleep(2)
        for msg in filler_qs:
            await turn(bot, cfg, MARIA, CUSTOMER_A, conv_maria, msg, label="Maria/filler")

        log("\n  --- callback recall checks (facts seeded many turns ago) ---")
        callbacks = {
            "sso_provider": "Remind me, what SSO provider do we use?",
            "data_region": "What's our data region again, for the compliance doc I'm writing?",
            "billing_contact": "Who's our billing contact, I forgot?",
            "support_hours": "What are our support hours?",
        }
        callback_results = {}
        for key, q in callbacks.items():
            company_ctx, personal_ctx, _ = await turn(bot, cfg, MARIA, CUSTOMER_A, conv_maria, q, label=f"Maria/callback:{key}")
            callback_results[key] = diag_dump(company_ctx)
        record("long_growth_callback_recall", turn_count_before_callbacks=len(seed_facts) + len(seed_prefs) + len(filler_qs),
               callbacks=callback_results)

        # preference-consistency check
        style_company, style_personal, style_reply = await turn(
            bot, cfg, MARIA, CUSTOMER_A, conv_maria, "Give me a quick status update on SSO setup.", label="Maria/style-check"
        )
        record("preference_consistency", reply=style_reply, personal_ctx=diag_dump(style_personal))

        # ============================================================
        # SECTION 4 -- conflicting / updated facts
        # ============================================================
        log("\n" + "=" * 70)
        log("SECTION 4: Conflicting/updated facts (Okta -> Azure AD, same user)")
        log("=" * 70)
        await turn(bot, cfg, MARIA, CUSTOMER_A, conv_maria,
                   "Correction -- we actually switched off Okta. We now use Azure AD for SSO as of this month.",
                   label="Maria/conflict")
        await asyncio.sleep(2)
        conflict_company, _, _ = await turn(
            bot, cfg, MARIA, CUSTOMER_A, conv_maria, "Just to confirm, what SSO provider are we using?", label="Maria/conflict-check"
        )
        mentions_okta = any("okta" in f.lower() for f in conflict_company.company_facts)
        mentions_azure = any("azure" in f.lower() for f in conflict_company.company_facts)
        record("conflicting_facts", mentions_okta=mentions_okta, mentions_azure=mentions_azure,
               ctx=diag_dump(conflict_company))
        log(f"  RESULT: still mentions Okta={mentions_okta}, mentions Azure AD={mentions_azure}")

        # ============================================================
        # SECTION 5 -- noise / distractor burial
        # ============================================================
        log("\n" + "=" * 70)
        log("SECTION 5: Noise/distractor burial (Jordan, 20 filler messages)")
        log("=" * 70)
        noise_messages = [
            "What's the weather like over there today?", "The new dashboard looks great.",
            "Is the office open on Friday?", "We should get lunch sometime.",
            "Testing testing, ignore this.", "Any updates on the company picnic?",
            "I saw a good movie last night.", "Just checking you're still there.",
            "What time zone are you in?", "Fun fact about octopuses.",
            "Following up on nothing in particular.", "Do you support markdown?",
            "Just adding some noise here.", "What's your favorite color?",
            "Reminder: buy coffee for the office.", "Is this thing on?",
            "Another filler message.", "Why did the developer go broke? Cache issues.",
            "Checking in, no real question.", "Distractor message number twenty.",
        ]
        # Jordan states a real fact buried nowhere near this burst, then we bury it.
        await turn(bot, cfg, JORDAN, CUSTOMER_A, conv_jordan,
                   "By the way, my direct manager is Alex Kim and I'm on the platform team.",
                   label="Jordan/real-fact")
        await asyncio.sleep(2)
        for m in noise_messages:
            cctx, pctx, _ = await bot.company_context(CUSTOMER_A, [m]), None, None
            reply = await llm.generate_reply(m, [], [], openai_api_key=cfg.openai_api_key)
            await bot.ask(user_id=JORDAN, customer_id=CUSTOMER_A, conversation_id=conv_jordan,
                          user_message=m, reply=reply)
        log(f"  [sent {len(noise_messages)} noise messages]")
        recall_company, recall_personal, _ = await turn(
            bot, cfg, JORDAN, CUSTOMER_A, conv_jordan, "Who is my manager again?", label="Jordan/recall-after-noise"
        )
        recalled = any("alex kim" in f.lower() for f in recall_personal.personal_preferences + recall_personal.company_facts)
        record("noise_burial_recall", recalled_after_noise=recalled, noise_count=len(noise_messages),
               personal_ctx=diag_dump(recall_personal))
        log(f"  RESULT: real fact recalled after {len(noise_messages)} distractors={recalled}")

        # ============================================================
        # SECTION 6 -- cross-conversation / cross-session persistence
        # ============================================================
        log("\n" + "=" * 70)
        log("SECTION 6: Cross-conversation / cross-session persistence")
        log("=" * 70)
        # Brand-new conversation_id for Maria -- simulates her returning on a new day/session.
        new_conv_maria = str(uuid.uuid4())
        log(f"  [Maria starts a NEW conversation_id={new_conv_maria}, old one was {conv_maria}]")

        new_session_company, new_session_personal, _ = await turn(
            bot, cfg, MARIA, CUSTOMER_A, new_conv_maria,
            "Hi again, can you remind me what SSO setup we settled on?",
            label="Maria/new-session",
        )
        persisted_across_conv_id = any(
            ("azure" in f.lower() or "okta" in f.lower()) for f in new_session_company.company_facts
        )
        record("cross_conversation_fact_persistence", persisted=persisted_across_conv_id,
               ctx=diag_dump(new_session_company))
        log(f"  RESULT: SSO fact persisted into brand-new conversation_id={persisted_across_conv_id}")

        # Now the *dedicated* cross-session API: context_mode="conversation-summary"
        log("\n  --- dedicated cross-session summary API (context_mode='conversation-summary') ---")
        history = await bot.cross_session_summary(MARIA, CUSTOMER_A, last_n_conversations=10)
        record("cross_session_summary_api", **history)
        log(f"  conversations found: {len(history['conversations'])}")
        for c in history["conversations"]:
            log(f"    - conv_id={c['conversation_id']} started_at={c['started_at']} "
                f"messages={c['message_count']} status={c['summary_status']} overview={c['overview']}")
        log(f"  profile_attributes: {history['profile_attributes']}")
        log(f"  profile_overview: {history['profile_overview']}")

        # ============================================================
        # DUMP
        # ============================================================
        out_path = "stress_test_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        log(f"\nFull raw results written to {out_path}")

    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
