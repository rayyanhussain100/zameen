"""ADK agent definition. `root_agent` is the conventional name ADK tooling
(adk web / adk run) looks for when discovering an agent module."""

from __future__ import annotations

from google.adk.agents import Agent

from zameen_agent.agent.prompts import SYSTEM_INSTRUCTION
from zameen_agent.config import settings
from zameen_agent.tools.semantic_search_tool import semantic_search
from zameen_agent.tools.sql_tool import sql_query

root_agent = Agent(
    name="zameen_agent",
    model=settings.agent_model,
    description=(
        "Answers questions about Zameen.com property listings (for sale and "
        "for rent, priced in PKR) using read-only SQL and semantic search."
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[sql_query, semantic_search],
)
