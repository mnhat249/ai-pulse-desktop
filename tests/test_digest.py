from __future__ import annotations

import json
import re

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.core.models import Digest
from app.pipeline.digest import (
    ClusterInput,
    Provider,
    build_prompt,
    digest_batch,
    load_prompt,
    parse_digests,
)
from app.pipeline.embeddings import from_bytes, normalize, to_bytes
from app.storage.tables import clusters, llm_usage
from tests.helpers import FakeLLM, all_clusters, digest_json, gh, make


async def test_digest_is_saved_and_importance_uses_llm_score(engine: AsyncEngine) -> None:
    llm = FakeLLM()
    proc, writer = await make(engine, [gh("1", "acme/tool")], providers=[Provider(llm, 10)])
    result = await proc.run()
    await writer.stop()
    (cluster,) = await all_clusters(engine)
    digest = Digest.model_validate(cluster["digest"])
    assert digest.title_vi == f"Tiêu đề {cluster['id']}"
    assert result.digested == [cluster["id"]] and len(llm.prompts) == 1


async def test_clusters_are_batched_into_few_calls(engine: AsyncEngine) -> None:
    llm = FakeLLM()
    items = [gh(str(i), f"acme/tool{i}") for i in range(10)]
    settings = Settings.model_validate({"llm": {"batch_size": 4}})
    proc, writer = await make(engine, items, providers=[Provider(llm, 50)], settings=settings)
    result = await proc.run()
    await writer.stop()
    assert len(llm.prompts) == 3 and len(result.digested) == 10
    assert llm.prompts[0].count("<su_kien ") == 4
    assert all(c["digest"] is not None for c in await all_clusters(engine))


async def test_llm_declaring_noise_marks_the_cluster(engine: AsyncEngine) -> None:
    class NoisyLLM(FakeLLM):
        async def complete(self, prompt: str) -> str:
            ids = [int(i) for i in re.findall(r'cluster_id="(\d+)"', prompt)]
            return json.dumps(
                [
                    digest_json(
                        cluster_id=i,
                        importance=1,
                        is_noise=True,
                        noise_reason="quảng cáo khóa học",
                    )
                    for i in ids
                ]
            )

    proc, writer = await make(engine, [gh("1", "acme/tool")], providers=[Provider(NoisyLLM(), 10)])
    result = await proc.run()
    await writer.stop()
    (cluster,) = await all_clusters(engine)
    assert cluster["is_noise"] is True and cluster["noise_reason"] == "quảng cáo khóa học"
    assert result.digested == []


async def test_llm_failure_leaves_cluster_pending_with_original_title(engine: AsyncEngine) -> None:
    providers = [Provider(FakeLLM(fail=True), 10)]
    proc, writer = await make(engine, [gh("1", "acme/tool")], providers=providers)
    result = await proc.run()
    await writer.stop()
    (cluster,) = await all_clusters(engine)
    assert cluster["digest"] is None and cluster["is_noise"] is False and result.digested == []


async def test_no_providers_means_no_llm_calls_but_clusters_are_built(engine: AsyncEngine) -> None:
    proc, writer = await make(engine, [gh("1", "acme/tool")])
    result = await proc.run()
    await writer.stop()
    assert result.clustered == 1 and result.digested == []


async def test_daily_cap_is_never_exceeded_and_rest_waits(engine: AsyncEngine) -> None:
    llm = FakeLLM()
    items = [gh(str(i), f"acme/tool{i}") for i in range(30)]
    settings = Settings.model_validate({"llm": {"batch_size": 2}})
    proc, writer = await make(engine, items, providers=[Provider(llm, 2)], settings=settings)
    await proc.run()
    await proc.run()
    await writer.stop()
    assert len(llm.prompts) == 2
    async with engine.connect() as conn:
        usage = (await conn.execute(select(llm_usage.c.provider, llm_usage.c.calls))).all()
        pending = (
            await conn.execute(select(clusters.c.id).where(clusters.c.digest.is_(None)))
        ).all()
    assert [tuple(u) for u in usage] == [("gemini", 2)] and len(pending) == 26


async def test_exhausted_primary_falls_back_to_second_provider(engine: AsyncEngine) -> None:
    gemini, groq = FakeLLM("gemini"), FakeLLM("groq")
    providers = [Provider(gemini, 0), Provider(groq, 10)]
    proc, writer = await make(engine, [gh("1", "acme/tool")], providers=providers)
    result = await proc.run()
    await writer.stop()
    assert gemini.prompts == [] and len(groq.prompts) == 1 and len(result.digested) == 1


async def test_digest_text_has_no_links_and_primary_url_is_a_source_url(
    engine: AsyncEngine,
) -> None:
    class LinkyLLM(FakeLLM):
        async def complete(self, prompt: str) -> str:
            ids = [int(i) for i in re.findall(r'cluster_id="(\d+)"', prompt)]
            bad = digest_json(cluster_id=ids[0], title_vi="Xem https://bia-dat.example/fake")
            good = digest_json(cluster_id=ids[1], title_vi="Tiêu đề sạch")
            return json.dumps({"items": [bad, good]})

    items = [gh("1", "acme/one"), gh("2", "acme/two")]
    proc, writer = await make(engine, items, providers=[Provider(LinkyLLM(), 10)])
    await proc.run()
    await writer.stop()
    result = await all_clusters(engine)
    digested = [c for c in result if c["digest"]]
    assert len(digested) == 1
    link = re.compile(r"https?://|www\.", re.IGNORECASE)
    for cluster in digested:
        digest = cluster["digest"]
        assert isinstance(digest, dict)
        assert not any(link.search(str(digest[f])) for f in ("title_vi", "innovation", "impact"))
    assert {c["primary_url"] for c in result} <= {
        "https://github.com/acme/one",
        "https://github.com/acme/two",
    }


def test_parse_digests_accepts_list_or_items_dict_and_drops_bad_or_unknown() -> None:
    entries = [
        digest_json(cluster_id=1),
        digest_json(cluster_id=2, importance=9),
        digest_json(cluster_id=99),
        {"cluster_id": 3},
        digest_json(cluster_id=1, title_vi="trùng"),
    ]
    for payload in (entries, {"items": entries}):
        got = parse_digests(json.dumps(payload), {1, 2, 3})
        assert [d.cluster_id for d in got] == [1] and got[0].title_vi == "T"


def test_parse_digests_rejects_non_list_payload() -> None:
    with pytest.raises(ValueError):
        parse_digests(json.dumps({"khac": 1}), {1})
    with pytest.raises(ValueError):
        parse_digests("không phải json", {1})


@pytest.mark.parametrize("field", ["title_vi", "innovation", "impact", "noise_reason"])
@pytest.mark.parametrize(
    "bad", ["https://x.com/a", "xem www.example.com", "github.com/foo/bar xin"]
)
def test_digest_model_rejects_links_in_any_text_field(field: str, bad: str) -> None:
    with pytest.raises(ValueError):
        Digest.model_validate(digest_json(**{field: bad}))


def test_prompt_template_is_external_and_marks_content_as_data() -> None:
    cluster = ClusterInput(7, ["github"], ["acme/tool"], "x" * 5000)
    prompt = build_prompt(load_prompt(), [cluster], max_text_chars=100)
    assert '<su_kien cluster_id="7">' in prompt and "DỮ LIỆU" in prompt
    assert "x" * 101 not in prompt


async def quota_always(_name: str, _cap: int) -> bool:
    return True


async def no_record(_name: str) -> None:
    return None


async def test_schema_failure_is_retried_once_then_succeeds() -> None:
    llm = FakeLLM(bad=1)
    calls: list[str] = []

    async def record(name: str) -> None:
        calls.append(name)

    batch = [ClusterInput(1, ["a"], ["t"], "x")]
    got = await digest_batch([Provider(llm, 5)], batch, load_prompt(), 100, quota_always, record)
    assert len(got) == 1 and len(llm.prompts) == 2 and calls == ["gemini", "gemini"]


async def test_two_schema_failures_fall_through_to_the_next_provider() -> None:
    gemini, groq = FakeLLM("gemini", bad=2), FakeLLM("groq")
    batch = [ClusterInput(1, ["a"], ["t"], "x")]
    got = await digest_batch(
        [Provider(gemini, 5), Provider(groq, 5)], batch, load_prompt(), 100, quota_always, no_record
    )
    assert len(got) == 1 and len(gemini.prompts) == 2 and len(groq.prompts) == 1


async def test_every_provider_failing_schema_returns_nothing() -> None:
    gemini, groq = FakeLLM("gemini", bad=2), FakeLLM("groq", bad=2)
    batch = [ClusterInput(1, ["a"], ["t"], "x")]
    got = await digest_batch(
        [Provider(gemini, 5), Provider(groq, 5)], batch, load_prompt(), 100, quota_always, no_record
    )
    assert got == [] and len(gemini.prompts) == 2 and len(groq.prompts) == 2


async def test_network_error_falls_through_to_next_provider() -> None:
    gemini, groq = FakeLLM("gemini", fail=True), FakeLLM("groq")
    batch = [ClusterInput(1, ["a"], ["t"], "x")]
    got = await digest_batch(
        [Provider(gemini, 5), Provider(groq, 5)], batch, load_prompt(), 100, quota_always, no_record
    )
    assert len(got) == 1 and len(gemini.prompts) == 1 and len(groq.prompts) == 1


def test_vector_bytes_roundtrip() -> None:
    vec = normalize(np.array([3.0, 4.0], dtype=np.float32))
    assert np.allclose(from_bytes(to_bytes(vec)), [0.6, 0.8])
