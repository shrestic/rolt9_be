from app.services.moderation.escalation import next_escalation

RULES = [
    {"threshold": 5, "action": "ban"},
    {"threshold": 3, "action": "mute", "duration_seconds": 3600},
]


def test_no_rule_below_first_threshold():
    assert next_escalation(2, RULES) is None


def test_exact_threshold_returns_rule():
    rule = next_escalation(3, RULES)
    assert rule == {"threshold": 3, "action": "mute", "duration_seconds": 3600}


def test_highest_matching_threshold_wins():
    assert next_escalation(5, RULES)["action"] == "ban"


def test_between_thresholds_returns_none():
    assert next_escalation(4, RULES) is None


def test_empty_rules_returns_none():
    assert next_escalation(10, []) is None
