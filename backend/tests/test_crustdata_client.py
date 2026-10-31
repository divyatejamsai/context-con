import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from app.crustdata import CrustdataClient, CrustdataError, ResponseCache


def make_client(tmp_path, handler, mode="cache"):
    cache = ResponseCache(tmp_path / "cache", tmp_path / "fixtures")
    return CrustdataClient(api_key="test", mode=mode, cache=cache,
                           transport=httpx.MockTransport(handler), backoff_base=0.01)


@pytest.mark.asyncio
async def test_headers_source_and_cache(tmp_path):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"profiles": [{"name": "Asha"}, {"name": "Ravi"}]})

    async with make_client(tmp_path, handler) as c:
        rows = await c.person_search({"title": "backend"})
        again = await c.person_search({"title": "backend"})
    assert [r["name"] for r in rows] == ["Asha", "Ravi"]
    assert rows[0]["_source"]["endpoint"] == "person/search"
    assert rows[0]["_source"]["origin"] == "live"
    assert again[0]["_source"]["origin"] == "cache"
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer test"
    assert calls[0].headers["x-api-version"] == "2025-11-01"


@pytest.mark.asyncio
async def test_retries_then_succeeds(tmp_path):
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(503 if n["i"] == 1 else 429)
        return httpx.Response(200, json=[{"matched_on": "acme.com", "match_type": "domain", "matches": [
            {"confidence_score": 0.4, "company_data": {"crustdata_company_id": 2, "basic_info": {"name": "Acme Old"}}},
            {"confidence_score": 0.9, "company_data": {"crustdata_company_id": 1, "basic_info": {"name": "Acme"}}}]}])

    async with make_client(tmp_path, handler, mode="live") as c:
        out = await c.company_enrich(domain="acme.com")
    assert out["basic_info"]["name"] == "Acme" and out["_source"]["endpoint"] == "company/enrich" and n["i"] == 3 and c.stats["retries"] == 2


@pytest.mark.asyncio
async def test_retries_exhausted_raises(tmp_path):
    async with make_client(tmp_path, lambda r: httpx.Response(500), mode="live") as c:
        with pytest.raises(CrustdataError):
            await c.web_search("x")


@pytest.mark.asyncio
async def test_timeout_is_retried(tmp_path):
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        if n["i"] == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json={"results": [{"url": "u"}]})

    async with make_client(tmp_path, handler, mode="live") as c:
        assert (await c.web_search("q"))[0]["url"] == "u"


@pytest.mark.asyncio
async def test_404_and_empty_are_not_errors(tmp_path):
    async with make_client(tmp_path, lambda r: httpx.Response(404, json={"error": "nf"})) as c:
        assert await c.person_enrich("https://linkedin.com/in/nobody") is None
        assert await c.person_search({"x": 1}) == []
        assert await c.person_enrich("") is None


@pytest.mark.asyncio
async def test_400_raises_without_retry(tmp_path):
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        return httpx.Response(400, json={"error": "bad filter"})

    async with make_client(tmp_path, handler, mode="live") as c:
        with pytest.raises(CrustdataError) as e:
            await c.job_search({"bad": 1})
    assert e.value.status == 400 and n["i"] == 1


@pytest.mark.asyncio
async def test_replay_serves_cache_and_never_hits_network(tmp_path):
    body = [{"matched_on": "https://www.linkedin.com/in/asha/", "match_status": "matched",
             "matches": [{"confidence_score": 1, "person_data": {"basic_profile": {"name": "Asha"}}}]}]
    async with make_client(tmp_path, lambda r: httpx.Response(200, json=body)) as c:
        await c.person_enrich("https://linkedin.com/in/asha")

    def boom(req):
        raise AssertionError("network used in replay")

    async with make_client(tmp_path, boom, mode="replay") as c:
        hit = await c.person_enrich("https://linkedin.com/in/asha")
        miss = await c.person_enrich("https://linkedin.com/in/other")
    assert hit["basic_profile"]["name"] == "Asha" and hit["_source"]["origin"] == "cache"
    assert miss is None and c.stats["miss"] == 1


def test_replay_needs_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUSTDATA_API_KEY", raising=False)
    CrustdataClient(mode="replay", cache=ResponseCache(tmp_path, None))


@pytest.mark.asyncio
async def test_person_enrich_many_batches_and_not_found(tmp_path):
    seen = []

    def handler(req):
        import json
        urls = json.loads(req.content)["professional_network_profile_urls"]
        seen.append(len(urls))
        return httpx.Response(200, json=[
            {"matched_on": u, "match_status": "not_found" if u.endswith("9") else "matched",
             "matches": [] if u.endswith("9") else [{"confidence_score": 1, "person_data": {"basic_profile": {"name": u}}}]}
            for u in urls])

    urls = [f"https://linkedin.com/in/p{i}" for i in range(30)]
    async with make_client(tmp_path, handler, mode="live") as c:
        out = await c.person_enrich_many(urls)
    assert sorted(seen) == [5, 25]
    assert out[urls[0]]["basic_profile"]["name"] == urls[0]
    assert out[urls[9]] is None and len(out) == 30


@pytest.mark.asyncio
async def test_web_fetch_and_identify_shapes(tmp_path):
    def handler(req):
        if req.url.path == "/web/enrich/live":
            return httpx.Response(200, json=[{"success": True, "url": "https://x.com", "title": "X", "content": "hi"}])
        return httpx.Response(200, json=[{"matched_on": "x.com", "matches": []}])

    async with make_client(tmp_path, handler, mode="live") as c:
        page = await c.web_fetch("https://x.com")
        assert page["content"] == "hi" and page["_source"]["url"] == "https://x.com"
        assert await c.company_identify(domain="x.com") is None
