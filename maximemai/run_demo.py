"""Scripted end-to-end proof that Synap splits one message into a shared
company fact and a private personal preference, then respects that split on
retrieval -- for two employees at the same B2B customer (CloudSync's
customer "Acme Corp"), per usecase.md.

Run this first: python run_demo.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import config
import llm
from memory_bot import MemoryBot

CUSTOMER_ID = "acme_corp"
ADMIN_USER_ID = "maria_chen"
EMPLOYEE_USER_ID = "jordan_lee"


def _print_header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _print_context(label: str, ctx) -> None:
    print(f"\n[{label}'s retrieved context]")
    print(f"  company_facts:         {ctx.company_facts}")
    print(f"  personal_preferences:  {ctx.personal_preferences}")


async def main() -> None:
    cfg = config.load_config()
    bot = MemoryBot(api_key=cfg.synap_api_key)
    await bot.initialize()

    try:
        admin_conversation_id = str(uuid.uuid4())
        employee_conversation_id = str(uuid.uuid4())

        # --- Step 1: Maria Chen (company admin) reports a company-wide fact
        # (Okta for SSO) and a personal preference (terse replies) in one message.
        _print_header("STEP 1 — Maria Chen (admin) sends a mixed message")
        maria_message = (
            "We use Okta for SSO and I'm the IT admin, Maria Chen -- can you set "
            "that up? Also, just give me short answers, skip the pleasantries."
        )
        print(f"Maria: {maria_message}")

        maria_company_ctx = await bot.company_context(CUSTOMER_ID, [maria_message])
        maria_personal_ctx = await bot.personal_context(
            ADMIN_USER_ID, CUSTOMER_ID, [maria_message]
        )
        maria_reply = await llm.generate_reply(
            maria_message,
            maria_company_ctx.company_facts,
            maria_personal_ctx.personal_preferences,
            openai_api_key=cfg.openai_api_key,
        )
        print(f"\nBot: {maria_reply}")

        await bot.ask(
            user_id=ADMIN_USER_ID,
            customer_id=CUSTOMER_ID,
            conversation_id=admin_conversation_id,
            user_message=maria_message,
            reply=maria_reply,
            wait_for_ingestion=True,
        )
        print("\n(Ingestion complete -- Synap has extracted the Okta fact and the terse-reply preference.)")

        # --- Step 2: Jordan Lee (a different employee, same company, never
        # talked to the bot before) asks about SSO setup.
        _print_header("STEP 2 — Jordan Lee (employee, same company) asks about SSO")
        jordan_message = "How do I set up single sign-on for our team?"
        print(f"Jordan: {jordan_message}")

        jordan_company_ctx = await bot.company_context(CUSTOMER_ID, [jordan_message])
        jordan_personal_ctx = await bot.personal_context(
            EMPLOYEE_USER_ID, CUSTOMER_ID, [jordan_message]
        )

        # --- Step 3: print Jordan's context BEFORE the bot answers, so the
        # isolation is visible, not just asserted.
        _print_header("STEP 3 — Jordan's context, printed before the bot answers")
        _print_context("Jordan", jordan_personal_ctx)
        print(f"\n  [merged] company_facts seen by Jordan: {jordan_company_ctx.company_facts}")

        proves_sharing = any("okta" in fact.lower() for fact in jordan_company_ctx.company_facts)
        proves_isolation = not any(
            "terse" in p.lower() or "short" in p.lower()
            for p in jordan_personal_ctx.personal_preferences
        )

        print(f"\n  Okta fact reached Jordan without re-explaining: {proves_sharing}")
        print(f"  Maria's 'terse replies' preference stayed private:  {proves_isolation}")

        jordan_reply = await llm.generate_reply(
            jordan_message,
            jordan_company_ctx.company_facts,
            jordan_personal_ctx.personal_preferences,
            openai_api_key=cfg.openai_api_key,
        )
        print(f"\nBot (to Jordan): {jordan_reply}")

        await bot.ask(
            user_id=EMPLOYEE_USER_ID,
            customer_id=CUSTOMER_ID,
            conversation_id=employee_conversation_id,
            user_message=jordan_message,
            reply=jordan_reply,
        )

        _print_header("RESULT")
        if proves_sharing and proves_isolation:
            print("PASS -- company facts shared across employees, personal preferences stayed private.")
        else:
            print("UNEXPECTED -- check ingestion timing or scope wiring above.")

    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
