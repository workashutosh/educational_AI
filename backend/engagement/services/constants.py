"""Engagement constants (tunable estimates)."""
from __future__ import annotations

# Teacher time-saved estimates (minutes)
MINUTES_PPT = 45
MINUTES_MOCK_GENERATE = 90
MINUTES_MICRO_AUTO = 15

# Mastery weights
MASTERY_WEIGHT_MOCK = 0.60
MASTERY_WEIGHT_MICRO = 0.25
MASTERY_WEIGHT_CHAT = 0.15
# Chat engagement: 10 turns → full chat component
CHAT_TURNS_FOR_FULL = 10

# Notification dedupe window
DEDUPE_HOURS = 24
