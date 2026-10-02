from __future__ import annotations

import pytest
from translate_manager_rag import SparseMipsRetriever

from translation_backend.app.infrastructure.translation_memory.sentence_processing import (
    TOKENIZER_VERSION,
    TranslationMemoryVectorizer,
)
from translation_backend.app.infrastructure.translation_memory.index_format import (
    TranslationMemoryIndexFormat,
)


def test_index_format_restores_vectorizer_metadata_and_sparse_retriever():
    vectorizer = TranslationMemoryVectorizer(version="tfidf-test-v1").fit(
        [("hello world", "en"), ("hello there", "en")]
    )
    rows = [vectorizer.encode(text, "en") for text in ("hello world", "hello there")]
    retriever = SparseMipsRetriever(candidate_threshold=0.0)
    retriever.build(
        documents=[{"id": "world"}, {"id": "there"}],
        vectors=rows,
        num_features=vectorizer.num_features,
    )

    payload = TranslationMemoryIndexFormat.serialize(vectorizer, retriever)
    restored_vectorizer, restored_retriever = TranslationMemoryIndexFormat.deserialize(
        payload,
        expected_vectorizer_version="tfidf-test-v1",
    )

    query = restored_vectorizer.encode("hello world", "en")
    assert query == vectorizer.encode("hello world", "en")
    assert restored_retriever.search(query, top_k=1)[0]["id"] == "world"
    assert restored_vectorizer.vocabulary == vectorizer.vocabulary


def test_index_format_rejects_vectorizer_version_mismatch():
    vectorizer = TranslationMemoryVectorizer(version="tfidf-v1").fit([("hello", "en")])
    retriever = SparseMipsRetriever()
    retriever.build(documents=[{"id": "hello"}], vectors=[vectorizer.encode("hello", "en")], num_features=vectorizer.num_features)
    payload = TranslationMemoryIndexFormat.serialize(vectorizer, retriever)

    with pytest.raises(ValueError, match="vectorizer version"):
        TranslationMemoryIndexFormat.deserialize(payload, expected_vectorizer_version="tfidf-v2")


def test_index_format_rejects_retriever_dimension_mismatch():
    vectorizer = TranslationMemoryVectorizer().fit([("hello", "en")])
    retriever = SparseMipsRetriever()
    retriever.build(
        documents=[{"id": "hello"}],
        vectors=[[(0, 1.0)]],
        num_features=vectorizer.num_features + 1,
    )

    with pytest.raises(ValueError, match="dimension"):
        TranslationMemoryIndexFormat.serialize(vectorizer, retriever)


def test_index_format_rejects_modified_payload():
    vectorizer = TranslationMemoryVectorizer().fit([("hello", "en")])
    retriever = SparseMipsRetriever()
    retriever.build(documents=[{"id": "hello"}], vectors=[vectorizer.encode("hello", "en")], num_features=vectorizer.num_features)
    payload = bytearray(TranslationMemoryIndexFormat.serialize(vectorizer, retriever))
    payload[-1] ^= 1

    with pytest.raises(ValueError, match="checksum"):
        TranslationMemoryIndexFormat.deserialize(bytes(payload), expected_vectorizer_version=vectorizer.version)
