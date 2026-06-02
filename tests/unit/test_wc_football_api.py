import pytest


@pytest.mark.asyncio
async def test_parse_fixtures_maps_fields(monkeypatch):
    import app.services.wc.football_api as fa

    sample = {
        "matches": [
            {
                "id": 1001,
                "stage": "GROUP_STAGE",
                "matchday": 1,
                "utcDate": "2026-06-20T12:00:00Z",
                "status": "FINISHED",
                "homeTeam": {"name": "Brazil", "tla": "BRA"},
                "awayTeam": {"name": "Argentina", "tla": "ARG"},
                "score": {"fullTime": {"home": 2, "away": 1}},
            }
        ]
    }

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return sample

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(fa.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fa.settings, "FOOTBALL_DATA_API_KEY", "k", raising=False)

    matches = await fa.fetch_wc_matches()
    assert len(matches) == 1
    m = matches[0]
    assert m["id"] == 1001 and m["home_team"] == "Brazil" and m["home_code"] == "BRA"
    assert m["status"] == "finished" and m["home_score"] == 2 and m["away_score"] == 1
    assert m["kickoff_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_fetch_no_key_returns_empty(monkeypatch):
    import app.services.wc.football_api as fa

    monkeypatch.setattr(fa.settings, "FOOTBALL_DATA_API_KEY", "", raising=False)
    assert await fa.fetch_wc_matches() == []
