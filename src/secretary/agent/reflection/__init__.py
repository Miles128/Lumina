"""F21 Reflexion-style memory: failure detection and reflection generation."""

from secretary.agent.reflection.runner import ReflectionRunner
from secretary.agent.reflection.trigger import FailureSignal, ReflectionTrigger

__all__ = ["FailureSignal", "ReflectionTrigger", "ReflectionRunner"]
