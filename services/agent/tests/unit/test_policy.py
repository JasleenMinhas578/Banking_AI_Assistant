"""Phase 5: chunking, hybrid search, the FAQ cache, the grounding check, the node."""

from pathlib import Path

import pytest

from app.nodes.policy_answer_node import PolicyAnswerNode
from app.policy.answerer import UNKNOWN, RagAnswerer, is_grounded, numbers_in
from app.policy.chunker import chunk_policy, load_policies
from app.policy.index import Faq, Hit, PolicyIndex
from app.replies import POLICY_UNAVAILABLE
from tests.unit.fakes import FakeAnswerer, FakeChatModel, FakeEmbedder

pytestmark = pytest.mark.anyio
POLICIES = Path(__file__).resolve().parents[4] / "data" / "policies"

SAMPLE = """---
policy_id: POL-009
title: Sample
effective: 2026-01-01
---

# POL-009 Sample

Intro line.

## Fees

| Fee | Amount |
| --- | --- |
| Thing | $9.99 |

## Hours

Open 8 am to 8 pm.
"""


def test_chunker_keeps_front_matter_and_splits_by_section() -> None:
    chunks = chunk_policy(SAMPLE)

    assert [c.section for c in chunks] == ["Overview", "Fees", "Hours"]
    assert chunks[1].policy_id == "POL-009" and chunks[1].title == "Sample"
    assert "| Thing | $9.99 |" in chunks[1].text  # the table stays whole


def test_the_real_policies_chunk_into_sections() -> None:
    chunks = load_policies(POLICIES)

    assert {c.policy_id for c in chunks} == {"POL-001", "POL-002", "POL-003", "POL-004", "POL-005"}
    assert 20 <= len(chunks) <= 60


async def build_index() -> PolicyIndex:
    embedder = FakeEmbedder()
    index = PolicyIndex(embed_model="fake")
    index.chunks = load_policies(POLICIES)
    index.chunk_vectors = await embedder.embed([f"{c.section}\n{c.text}" for c in index.chunks])
    index.faqs = [Faq("What is the NSF fee?", "The NSF fee is $45.00.", "POL-001")]
    index.faq_vectors = await embedder.embed([f.question for f in index.faqs])
    return index


async def test_hybrid_search_finds_the_exact_term_chunk() -> None:
    index = await build_index()
    vector = (await FakeEmbedder().embed(["NSF fee"]))[0]

    hits = index.search(vector, "NSF fee", k=3)

    assert hits[0].chunk.policy_id == "POL-001"
    assert any("NSF" in h.chunk.text for h in hits)  # the exact term is in the top 3


async def test_index_round_trips_through_json(tmp_path: Path) -> None:
    index = await build_index()
    index.save(tmp_path / "index.json")

    loaded = PolicyIndex.load(tmp_path / "index.json")

    assert len(loaded.chunks) == len(index.chunks) and loaded.faqs == index.faqs


def test_numbers_and_grounding() -> None:
    chunk = next(c for c in load_policies(POLICIES) if c.section == "Account fees")
    hit = Hit(chunk, 0.9, 0.1)

    assert numbers_in("The fee is $4.95, waived above $1,500.") == {"4.95", "1500"}
    assert is_grounded("Chequing costs $4.95 a month.", [hit])
    assert not is_grounded("Chequing costs $6.95 a month.", [hit])


async def test_faq_hit_needs_no_model() -> None:
    index = await build_index()
    model = FakeChatModel("should not be called")
    answerer = RagAnswerer(index, FakeEmbedder(), model, faq_min_similarity=0.9)

    answer = await answerer.answer("What is the NSF fee?")

    assert (answer.source, answer.text, model.calls) == ("faq", "The NSF fee is $45.00.", 0)


async def test_rag_answer_must_be_grounded_or_falls_back() -> None:
    index = await build_index()
    bad_then_good = FakeChatModel("The NSF fee is $99.", "The NSF fee is $45.00.")
    answerer = RagAnswerer(
        index, FakeEmbedder(), bad_then_good, faq_min_similarity=1.1, min_similarity=0.0
    )

    answer = await answerer.answer("how much is the non-sufficient funds charge")

    assert (answer.source, answer.text, bad_then_good.calls) == ("rag", "The NSF fee is $45.00.", 2)

    always_bad = FakeChatModel("The NSF fee is $99.")
    answerer = RagAnswerer(
        index, FakeEmbedder(), always_bad, faq_min_similarity=1.1, min_similarity=0.0
    )
    answer = await answerer.answer("how much is the non-sufficient funds charge")

    assert (answer.source, answer.text, answer.grounded) == ("unknown", UNKNOWN, False)


async def test_below_the_relevance_gate_says_so() -> None:
    index = await build_index()
    model = FakeChatModel("made up")
    answerer = RagAnswerer(
        index, FakeEmbedder(), model, faq_min_similarity=1.1, min_similarity=0.99
    )

    answer = await answerer.answer("what's the weather on the moon")

    assert (answer.source, answer.text, model.calls) == ("unknown", UNKNOWN, 0)


async def test_node_without_an_index_is_honest() -> None:
    update = await PolicyAnswerNode(None).run({"messages": [{"role": "caller", "text": "fees?"}]})

    assert update["reply"] == POLICY_UNAVAILABLE


async def test_node_passes_the_answer_and_keeps_the_policy_id_for_the_trace() -> None:
    update = await PolicyAnswerNode(FakeAnswerer()).run(
        {"messages": [{"role": "caller", "text": "what's the NSF fee"}]}
    )

    assert update["reply"].endswith("$45.00.")
    assert update["policy"]["policy_id"] == "POL-001"
