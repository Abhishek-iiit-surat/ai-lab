"""Interactive CLI -- have your own conversation as any employee at any company,
with extra commands for stress-testing Synap beyond the 2-message demo:

    python chat.py --user raj --customer acme_corp

Commands (type at the prompt instead of a message):
    /context          Show full diagnostics for the last retrieved context
                       (confidence/strength, extracted_at, temporal fields,
                       cache-vs-cloud source) -- not just the flattened text.
    /history          Fetch and print cross-session recall: summaries of this
                       user's past conversations + caller profile, via
                       context_mode="conversation-summary". Independent of the
                       current conversation_id -- this is the real cross-session
                       test.
    /new              Start a brand-new conversation_id for the same user, to
                       simulate them "returning later" without restarting the
                       process. Use this, then /history, to check recall
                       persists outside the original thread.
    /noise N          Send N canned small-talk/off-topic filler messages (each
                       ingested normally) to bury real facts under volume --
                       then ask your real question and see if search_query
                       relevance still surfaces it.
    /help             Show this list.
    exit / quit       End the session.
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

_NOISE_MESSAGES = [
    "What's the weather like over there today?",
    "Just wanted to say the new dashboard looks great.",
    "Quick one -- do you know if the office is open on Friday?",
    "Random thought: we should get lunch sometime.",
    "Testing testing, ignore this one.",
    "Any updates on the company picnic?",
    "I saw a good movie last night, nothing work related.",
    "Ping -- just checking you're still there.",
    "Unrelated question: what time zone are you in?",
    "Here's a fun fact about octopuses.",
    "Following up on nothing in particular.",
    "Do you support markdown in replies?",
    "Just rambling to add some noise to the conversation history.",
    "What's your favorite color? Not important, just curious.",
    "Reminder to self: buy coffee for the office.",
    "Is this thing on?",
    "Another filler message, please disregard.",
    "Sharing a joke: why did the developer go broke? Used up all their cache.",
    "Checking in, no real question here.",
    "This is distractor message number filling up the buffer.",
]


def _print_diag(label: str, diag_items) -> None:
    if not diag_items:
        print(f"    ({label}: none)")
        return
    for item in diag_items:
        extra = f", temporal={item.temporal_category}" if item.temporal_category else ""
        extra += f", valid_until={item.valid_until}" if item.valid_until else ""
        print(
            f"    - \"{item.content}\" "
            f"[confidence={item.confidence:.2f}, extracted_at={item.extracted_at}{extra}]"
        )


async def _send_turn(bot, args, user_message, cfg, conversation_id, *, verbose=True):
    company_ctx = await bot.company_context(args.customer, [user_message])
    personal_ctx = await bot.personal_context(args.user, args.customer, [user_message])

    if verbose:
        print(f"  [context source: company={company_ctx.source}, personal={personal_ctx.source}]")
        print(f"  [context] company_facts={company_ctx.company_facts}")
        print(f"  [context] personal_preferences={personal_ctx.personal_preferences}")

    reply = await llm.generate_reply(
        user_message,
        company_ctx.company_facts,
        personal_ctx.personal_preferences,
        openai_api_key=cfg.openai_api_key,
    )
    if verbose:
        print(f"bot> {reply}\n")

    await bot.ask(
        user_id=args.user,
        customer_id=args.customer,
        conversation_id=conversation_id,
        user_message=user_message,
        reply=reply,
    )
    return company_ctx, personal_ctx, reply


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

    last_company_ctx = None
    last_personal_ctx = None
    turn_count = 0

    print(f"Chatting as user='{args.user}' at customer='{args.customer}'.")
    print(f"conversation_id={conversation_id}")
    print("Type 'exit'/'quit' to end, or '/help' for stress-test commands.\n")

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

            if user_message.lower() == "/help":
                print(__doc__)
                continue

            if user_message.lower() == "/new":
                conversation_id = str(uuid.uuid4())
                print(f"  [new conversation_id={conversation_id} -- same user/customer, fresh thread]\n")
                continue

            if user_message.lower() == "/context":
                if last_company_ctx is None:
                    print("  (no context fetched yet -- send a message first)\n")
                    continue
                print(f"  [last fetch source: company={last_company_ctx.source} ({last_company_ctx.retrieved_at}), "
                      f"personal={last_personal_ctx.source} ({last_personal_ctx.retrieved_at})]")
                print("  company_facts:")
                _print_diag("company_facts", last_company_ctx.company_facts_diag)
                print("  personal_preferences:")
                _print_diag("personal_preferences", last_personal_ctx.personal_preferences_diag)
                print()
                continue

            if user_message.lower() == "/history":
                print("  [fetching cross-session summary -- context_mode='conversation-summary']")
                summary = await bot.cross_session_summary(args.user, args.customer)
                if not summary["conversations"]:
                    print("  (no past conversations found for this user)")
                else:
                    for conv in summary["conversations"]:
                        print(f"  - conversation_id={conv['conversation_id']} "
                              f"started_at={conv['started_at']} messages={conv['message_count']} "
                              f"status={conv['summary_status']}")
                        if conv["overview"]:
                            print(f"      overview: {conv['overview']}")
                        if conv["outcome"]:
                            print(f"      outcome: {conv['outcome']}")
                if summary["profile_attributes"]:
                    print(f"  profile_attributes: {summary['profile_attributes']}")
                if summary["profile_overview"]:
                    print(f"  profile_overview: {summary['profile_overview']}")
                print()
                continue

            if user_message.lower().startswith("/noise"):
                parts = user_message.split()
                n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
                print(f"  [sending {n} noise/distractor messages...]")
                for i in range(n):
                    filler = _NOISE_MESSAGES[i % len(_NOISE_MESSAGES)]
                    await _send_turn(bot, args, filler, cfg, conversation_id, verbose=False)
                    turn_count += 1
                print(f"  [done -- {n} distractor turns ingested, {turn_count} total this session]\n")
                continue

            turn_count += 1
            print(f"  [turn {turn_count}]")
            last_company_ctx, last_personal_ctx, _ = await _send_turn(
                bot, args, user_message, cfg, conversation_id
            )
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
