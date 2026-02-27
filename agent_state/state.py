"""
Agent state schema for landing page generation agent.

"""

from typing import TypedDict, Optional, Annotated
from typing_extensions import NotRequired
from langchain.agents import AgentState


class LandingPageAgentState(AgentState):
    user_id: NotRequired[str]
    project_id: NotRequired[str]

    memory_keys: NotRequired[list[str]]
