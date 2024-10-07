import pytest
import asyncio
from langchain_community.llms import BaseLLM
from langchain_core.embeddings import Embeddings

from cat.agents.main_agent import MainAgent
from cat.looking_glass.stray_cat import StrayCat
from cat.memory.long_term_memory import LongTermMemory
from cat.memory.working_memory import WorkingMemory
from cat.convo.messages import MessageWhy, CatMessage
from cat.factory.custom_embedder import DumbEmbedder
from cat.factory.custom_llm import LLMDefault


@pytest.fixture
def stray(client) -> StrayCat:
    yield StrayCat(user_id="Alice", main_loop=asyncio.new_event_loop())


def test_stray_initialization(stray):
    assert isinstance(stray, StrayCat)
    assert stray.user_id == "Alice"

    assert isinstance(stray.memory, LongTermMemory)

    assert isinstance(stray.working_memory, WorkingMemory)
    assert isinstance(stray.llm, BaseLLM)
    assert isinstance(stray.embedder, Embeddings)

    assert isinstance(stray.main_agent, MainAgent)


def test_default_llm_loaded(stray):
    assert isinstance(stray.llm, LLMDefault)

    out = stray.llm("Hey")
    assert "You did not configure a Language Model" in out


def test_default_embedder_loaded(stray):
    assert isinstance(stray.embedder, DumbEmbedder)

    sentence = "I'm smarter than a random embedder BTW"
    sample_embed = DumbEmbedder().embed_query(sentence)
    out = stray.embedder.embed_query(sentence)
    assert sample_embed == out


def test_stray_nlp(stray):
    res = stray.llm("hey")
    assert "You did not configure" in res

    embedding = stray.embedder.embed_documents(["hey"])
    assert isinstance(embedding[0], list)
    assert isinstance(embedding[0][0], float)


def test_stray_call(stray):
    msg = {"text": "Where do I go?", "user_id": "Alice"}

    reply = stray.loop.run_until_complete(stray.__call__(msg))

    assert isinstance(reply, CatMessage)
    assert "You did not configure" in reply.content
    assert reply.user_id == "Alice"
    assert reply.type == "chat"
    assert isinstance(reply.why, MessageWhy)


# TODO: update these tests once we have a real LLM in tests
def test_stray_classify(stray):
    label = stray.classify("I feel good", labels=["positive", "negative"])
    assert label is None  # TODO: should be "positive"

    label = stray.classify(
        "I feel bad", labels={"positive": ["I'm happy"], "negative": ["I'm sad"]}
    )
    assert label is None  # TODO: should be "negative"


def test_recall_to_working_memory(stray):
    # empty working memory / episodic
    assert stray.working_memory.episodic_memories == []

    msg_text = "Where do I go?"
    msg = {"text": msg_text, "user_id": "Alice"}

    # send message
    stray.loop.run_until_complete(stray.__call__(msg))

    # recall after episodic memory was stored
    stray.recall_relevant_memories_to_working_memory(msg_text)

    assert stray.working_memory.recall_query == msg_text
    assert len(stray.working_memory.episodic_memories) == 1
    assert stray.working_memory.episodic_memories[0][0].page_content == msg_text


def test_procedures_embedded(stray):
    # get embedded tools
    procedures = stray.memory.vectors.procedural.get_all_points()
    assert len(procedures) == 3

    for p in procedures:
        assert p.payload["metadata"]["source"] == "get_the_time"
        assert p.payload["metadata"]["type"] == "tool"
        trigger_type = p.payload["metadata"]["trigger_type"]
        content = p.payload["page_content"]
        assert trigger_type in ["start_example", "description"]

        if trigger_type == "start_example":
            assert content in ["what time is it", "get the time"]
        if trigger_type == "description":
            assert (
                content
                == "get_the_time: Useful to get the current time when asked. Input is always None."
            )

        # some check on the embedding
        assert isinstance(p.vector, list)
        expected_embed = stray.embedder.embed_query(content)
        assert len(p.vector) == len(expected_embed)  # same embed
        # assert p.vector == expected_embed TODO: Qdrant does unwanted normalization
