from langchain.base_language import BaseLanguageModel
from langchain_core.embeddings import Embeddings
from cat.mad_hatter.mad_hatter import MadHatter
from cat.memory.long_term_memory import LongTermMemory
from cat.factory.custom_embedder import DumbEmbedder
from cat.factory.custom_llm import LLMDefault


def test_main_modules_loaded(cheshire_cat):
    assert isinstance(cheshire_cat.mad_hatter, MadHatter)
    assert isinstance(cheshire_cat.memory, LongTermMemory)
    assert isinstance(cheshire_cat.llm, BaseLanguageModel)
    assert isinstance(cheshire_cat.embedder, Embeddings)


def test_default_llm_loaded(cheshire_cat):
    assert isinstance(cheshire_cat.llm, LLMDefault)

    out = cheshire_cat.llm_response("Hey")
    assert "You did not configure a Language Model" in out


def test_default_embedder_loaded(cheshire_cat):
    assert isinstance(cheshire_cat.embedder, DumbEmbedder)

    sentence = "I'm smarter than a random embedder BTW"
    sample_embed = DumbEmbedder().embed_query(sentence)
    out = cheshire_cat.embedder.embed_query(sentence)
    assert sample_embed == out


def test_procedures_embedded(cheshire_cat):
    # get embedded tools
    procedures = cheshire_cat.memory.vectors.procedural.get_all_points()
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
        expected_embed = cheshire_cat.embedder.embed_query(content)
        assert len(p.vector) == len(expected_embed)  # same embed
        # assert p.vector == expected_embed TODO: Qdrant does unwanted normalization
