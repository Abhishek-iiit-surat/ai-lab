"""Interactive CLI -- have your own conversation as any employee at any company.

    python chat.py --user raj --customer acme_corp
    python chat.py --user priya --customer acme_corp
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import config
import llm
from memory_bot import MemoryBot


async def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the CloudSync support bot as a given employee.")
    parser.add_argument("--user", required=True, help="user_id for this employee")
    parser.add_argument("--customer", required=True, help="customer_id for their company")
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Reuse a conversation UUID across runs; a new one is generated if omitted.",
    )
    args = parser.parse_args()

    conversation_id = args.conversation_id or str(uuid.uuid4())

    cfg = config.load_config()
    bot = MemoryBot(api_key=cfg.synap_api_key)
    await bot.initialize()

    print(f"Chatting as user='{args.user}' at customer='{args.customer}'.")
    print(f"conversation_id={conversation_id}")
    print("Type 'exit' or 'quit' to end.\n")

    try:
        while True:
            try:
                user_message = input(f"{args.user}> ").strip()
            except EOFError:
                break
            if not user_message:
                continue
            if user_message.lower() in {"exit", "quit"}:
                break

            company_ctx = await bot.company_context(args.customer, [user_message])
            personal_ctx = await bot.personal_context(args.user, args.customer, [user_message])

            print(f"  [context] company_facts={company_ctx.company_facts}")
            print(f"  [context] personal_preferences={personal_ctx.personal_preferences}")

            reply = await llm.generate_reply(
                user_message,
                company_ctx.company_facts,
                personal_ctx.personal_preferences,
                openai_api_key=cfg.openai_api_key,
            )
            print(f"bot> {reply}\n")

            await bot.ask(
                user_id=args.user,
                customer_id=args.customer,
                conversation_id=conversation_id,
                user_message=user_message,
                reply=reply,
            )
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
