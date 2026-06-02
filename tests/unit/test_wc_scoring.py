import pytest

from app.services.wc.scoring import POINTS, score


@pytest.mark.parametrize(
    "bet_type,pick,hs,as_,line,hcap_team,hcap_line,expected",
    [
        ("1x2", "home", 2, 1, None, None, None, 1),
        ("1x2", "home", 1, 1, None, None, None, 0),
        ("1x2", "draw", 1, 1, None, None, None, 1),
        ("1x2", "away", 0, 2, None, None, None, 1),
        ("1x2", "away", 2, 0, None, None, None, 0),
        ("ou", "over", 2, 1, 2.5, None, None, 1),
        ("ou", "over", 1, 1, 2.5, None, None, 0),
        ("ou", "under", 1, 0, 2.5, None, None, 1),
        ("cs", "2-1", 2, 1, None, None, None, 5),
        ("cs", "2-1", 1, 1, None, None, None, 0),
        ("ah", "favorite", 3, 1, None, "home", 1.0, 2),
        ("ah", "favorite", 2, 1, None, "home", 1.0, 0),
        ("ah", "underdog", 2, 2, None, "home", 1.0, 2),
        ("ah", "favorite", 0, 1, None, "away", 0.5, 2),
        ("ah", "underdog", 1, 1, None, "away", 0.5, 2),
    ],
)
def test_score_cases(bet_type, pick, hs, as_, line, hcap_team, hcap_line, expected):
    assert (
        score(
            bet_type,
            pick,
            home_score=hs,
            away_score=as_,
            ou_line=line,
            handicap_team=hcap_team,
            handicap_line=hcap_line,
        )
        == expected
    )


def test_points_table_difficulty():
    assert POINTS == {"1x2": 1, "ou": 1, "ah": 2, "cs": 5}


def test_unknown_bet_type_scores_zero():
    assert score("xxx", "home", home_score=1, away_score=0) == 0
