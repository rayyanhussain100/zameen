"""Interactive terminal chat loop for the Zameen agent.

Uses ADK's Runner + InMemorySessionService directly rather than relying on
`adk web`'s directory-discovery conventions, so it works regardless of where
this package is installed from.

    zameen-agent
    # or: python -m zameen_agent.agent.run
"""

from __future__ import annotations

import asyncio

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from zameen_agent.agent.agent import root_agent

APP_NAME = "zameen_agent"
USER_ID = "cli_user"


async def _chat_loop() -> None:
    session_service = InMemorySessionService()
    # NOTE: create_session()/run_async() signatures have shifted across ADK
    # releases — if this errors, check `pip show google-adk` against the ADK
    # docs for your installed version.
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

    print("Zameen Agent — ask a question about property listings (Ctrl+C to quit).")
    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue

        message = types.Content(role="user", parts=[types.Part(text=user_input)])
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                print(event.content.parts[0].text)


def main() -> None:
    asyncio.run(_chat_loop())


if __name__ == "__main__":
    main()
