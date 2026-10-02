from __future__ import annotations

from pathlib import Path

import pytest
from translate_manager_rag import SparseMipsRetriever

from translation_backend.app.core.config import AppSettings
from translation_backend.app.infrastructure.translation_memory.sentence_processing import (
    SEMANTIC_MODEL_IDS,
    SemanticSparseProjector,
    SentenceProcessor,
    SentenceTokenizer,
    TranslationMemoryVectorizer,
)


def test_tokenizer_normalizes_english_language_alias_and_punctuation() -> None:
    assert SentenceTokenizer().tokenize(" Hello, WORLD! ", "en-US") == ["hello", "world"]


def test_tokenizer_emits_chinese_unigrams_and_bigrams() -> None:
    tokens = SentenceTokenizer().tokenize("你好世界", "zh-CN")

    assert "你" in tokens
    assert "你好" in tokens
    assert "好世" in tokens


def test_tokenizer_emits_japanese_character_ngrams() -> None:
    tokens = SentenceTokenizer().tokenize("日本語ゲーム", "ja-JP")

    assert "日" in tokens
    assert "日本" in tokens
    assert "語ゲ" in tokens


def test_tokenizer_rejects_unsupported_languages() -> None:
    with pytest.raises(ValueError, match="Unsupported language"):
        SentenceTokenizer().tokenize("hola", "es")


def test_vectorizer_is_order_independent_and_outputs_normalized_sparse_weights() -> None:
    entries = [("hello world", "en"), ("hello again", "en"), ("你好世界", "zh")]
    first = TranslationMemoryVectorizer(version="test-v1").fit(entries)
    second = TranslationMemoryVectorizer(version="test-v1").fit(list(reversed(entries)))

    encoded = first.encode("hello world", "en-US")
    assert encoded == second.encode("hello world", "en")
    assert [feature for feature, _ in encoded] == sorted(feature for feature, _ in encoded)
    assert len({feature for feature, _ in encoded}) == len(encoded)
    assert all(weight > 0 for _, weight in encoded)
    assert sum(weight * weight for _, weight in encoded) == pytest.approx(1.0)
    assert first.version == "test-v1"
    assert first.num_features > 0


def test_vectorizer_ignores_tokens_absent_from_fitted_vocabulary() -> None:
    vectorizer = TranslationMemoryVectorizer().fit([("hello", "en")])

    assert vectorizer.encode("unknown", "en") == []


def test_language_models_are_registered_for_supported_languages() -> None:
    assert SEMANTIC_MODEL_IDS == {
        "zh": "BAAI/bge-small-zh-v1.5",
        "en": "BAAI/bge-small-en-v1.5",
        "ja": "cl-nagoya/ruri-base",
    }


def test_semantic_sparse_projection_is_stable_nonnegative_and_fixed_width() -> None:
    projector = SemanticSparseProjector(seed=17, projection_count=48)
    embedding = [0.25, -0.5, 0.75, -0.25]

    encoded = projector.encode(embedding)

    assert encoded == projector.encode(embedding)
    assert encoded == sorted(encoded)
    assert len({feature for feature, _ in encoded}) == len(encoded)
    assert all(weight == 1.0 for _, weight in encoded)
    assert projector.num_features == 96
    assert all(0 <= feature < projector.num_features for feature, _ in encoded)


def test_processor_does_not_create_semantic_encoder_when_language_switch_is_off() -> None:
    def fail_if_created(*args, **kwargs):
        raise AssertionError("semantic encoder must remain unloaded")

    settings = AppSettings(_env_file=None)
    processor = SentenceProcessor(settings=settings, semantic_encoder_factory=fail_if_created)
    processor.fit([("hello world", "en")])

    assert processor.encode("hello", "en")


def test_processor_creates_only_the_enabled_language_encoder(tmp_path: Path) -> None:
    class FakeEncoder:
        def __init__(self, model_id: str, model_path: Path) -> None:
            calls.append((model_id, model_path))

        def encode(self, text: str) -> list[float]:
            return [0.25, -0.5, 0.75, -0.25]

    calls = []
    settings = AppSettings(
        _env_file=None,
        tm_semantic_model_zh_enabled=True,
        tm_semantic_model_zh_path=tmp_path / "zh-model",
    )
    processor = SentenceProcessor(settings=settings, semantic_encoder_factory=FakeEncoder)

    encoded = processor.encode("你好", "zh-CN")

    assert calls == [(SEMANTIC_MODEL_IDS["zh"], tmp_path / "zh-model")]
    assert encoded
    assert all(weight >= 0 for _, weight in encoded)


def test_builtin_vectorizer_output_is_accepted_by_sparse_mips_sdk() -> None:
    vectorizer = TranslationMemoryVectorizer().fit(
        [("hello world", "en"), ("hello there", "en")]
    )
    rows = [
        vectorizer.encode("hello world", "en"),
        vectorizer.encode("hello there", "en"),
    ]
    retriever = SparseMipsRetriever(candidate_threshold=0.0)
    retriever.build(
        documents=[{"id": "world"}, {"id": "there"}],
        vectors=rows,
        num_features=vectorizer.num_features,
    )

    results = retriever.search(vectorizer.encode("hello world", "en"), top_k=1)

    assert results[0]["id"] == "world"
