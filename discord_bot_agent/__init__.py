"""Discord-first trading research bot for Hermes."""

# CD pipeline test marker — verifies webhook -> deploy.sh end-to-end deploy.

from .config import DiscordBotAgentConfig
from .models import TradeSetup

__all__ = ["DiscordBotAgentConfig", "TradeSetup"]
