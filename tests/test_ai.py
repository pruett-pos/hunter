import json
from types import SimpleNamespace

from hunter.ai import Claude, _schema
from hunter.models import ArvEstimate, Listing, ListingBatch


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)


def reply(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, stop_details=None, content=[SimpleNamespace(type="text", text=text)])


def client(replies):
    msgs = FakeMessages(replies)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_schema_is_strict():
    s = _schema(ListingBatch)
    item = s["$defs"]["Listing"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])


def test_extract_and_arv_requests():
    batch = {"listings": [Listing(address="1 A St", county="Howell", state="MO", deal_type="tax_sale").model_dump()]}
    arv = ArvEstimate(arv=80000, confidence="medium", reasoning="r").model_dump()
    c, msgs = client([reply(json.dumps(batch)), reply("", "pause_turn"), reply(json.dumps(arv))])
    cl = Claude({"model": "claude-opus-5-5"}, client=c)
    got = cl.extract("page text", "https://x", "tax_sale", ["MO: Howell"])
    assert got[0].address == "1 A St"
    est = cl.estimate_arv(got[0])
    assert est.arv == 80000
    first = msgs.calls[0]
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert msgs.calls[1]["tools"][0]["type"] == "web_search_20260209"
    assert msgs.calls[2]["messages"][1]["role"] == "assistant"  # resumed after pause_turn


def test_api_key_pulled_from_pasted_curl(monkeypatch):
    from hunter.ai import api_key_from_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", 'curl https://api.anthropic.com/v1/messages \\\n --header "x-api-key: sk-ant-api03-AbC_d-123" \\\n --data \'{}\'')
    assert api_key_from_env() == "sk-ant-api03-AbC_d-123"
    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-ant-xyz \n")
    assert api_key_from_env() == "sk-ant-xyz"
