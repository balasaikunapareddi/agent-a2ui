"""agent-a2ui: a clinic booking agent that answers with A2UI surfaces."""

from .agent import A2UIBookingAgent, DemoModel
from .catalog import ClinicCatalog
from .renderer import HtmlRenderer

__all__ = ["A2UIBookingAgent", "DemoModel", "ClinicCatalog", "HtmlRenderer"]
__version__ = "0.1.0"
