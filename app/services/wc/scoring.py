"""Chấm điểm dự đoán WC — PURE, không I/O. Điểm theo độ khó kèo (spec)."""

# Điểm khi đoán ĐÚNG, theo độ khó (sai = 0, không âm).
POINTS = {"1x2": 1, "ou": 1, "ah": 2, "cs": 5}


def _winner(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def score(
    bet_type: str,
    pick: str,
    *,
    home_score: int,
    away_score: int,
    ou_line: float | None = None,
    handicap_team: str | None = None,
    handicap_line: float | None = None,
) -> int:
    """Trả điểm cho 1 dự đoán dựa trên kết quả thật. Đúng -> POINTS[bet_type]; sai/push -> 0."""
    pts = POINTS.get(bet_type, 0)
    if not pts:
        return 0
    if bet_type == "1x2":
        return pts if pick == _winner(home_score, away_score) else 0
    if bet_type == "ou":
        if ou_line is None:
            return 0
        total = home_score + away_score
        hit = (pick == "over" and total > ou_line) or (pick == "under" and total < ou_line)
        return pts if hit else 0
    if bet_type == "cs":
        try:
            ph, pa = (int(x) for x in pick.split("-", 1))
        except (ValueError, AttributeError):
            return 0
        return pts if (ph == home_score and pa == away_score) else 0
    if bet_type == "ah":
        if handicap_team not in ("home", "away") or handicap_line is None:
            return 0
        if handicap_team == "home":
            margin = (home_score - handicap_line) - away_score
        else:
            margin = (away_score - handicap_line) - home_score
        if margin > 0:
            return pts if pick == "favorite" else 0
        if margin < 0:
            return pts if pick == "underdog" else 0
        return 0
    return 0
