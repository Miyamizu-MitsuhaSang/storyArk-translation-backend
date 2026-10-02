"""TM sentence tokenization and sparse vectorization.

Semantic models are optional. Install them with ``uv sync --extra semantic``, then
download only the models whose language switches are enabled:

    uv run hf download BAAI/bge-small-zh-v1.5 --local-dir models/semantic/bge-small-zh-v1.5
    uv run hf download BAAI/bge-small-en-v1.5 --local-dir models/semantic/bge-small-en-v1.5
    uv run hf download cl-nagoya/ruri-base --local-dir models/semantic/ruri-base

Set TM_SEMANTIC_MODEL_ZH_ENABLED, TM_SEMANTIC_MODEL_EN_ENABLED, or
TM_SEMANTIC_MODEL_JA_ENABLED to ``true`` to use that language's local model.
With all switches off, this module uses only its built-in tokenizer and TF-IDF.
"""

from __future__ import annotations

import importlib
import math
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable

from ...core.config import AppSettings, app_settings

SparseVector = list[tuple[int, float]]

SEMANTIC_MODEL_IDS = {
    "zh": "BAAI/bge-small-zh-v1.5",
    "en": "BAAI/bge-small-en-v1.5",
    "ja": "cl-nagoya/ruri-base",
}

TOKENIZER_VERSION = "unicode-ngram-v1"
TFIDF_VERSION = "tfidf-cosine-v1"
SEMANTIC_PROJECTION_VERSION = "random-hyperplane-v1"

_ENGLISH_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_ZH_TOKEN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[a-z0-9]+")
_JA_TOKEN_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]+|[a-z0-9]+"
)


def language_family(language: str) -> str:
    family = language.strip().replace("_", "-").split("-", 1)[0].lower()
    if family not in SEMANTIC_MODEL_IDS:
        raise ValueError(f"Unsupported language: {language}")
    return family


class SentenceTokenizer:
    """Small, deterministic tokenizer that needs no model or network access."""

    def tokenize(self, text: str, language: str) -> list[str]:
        family = language_family(language)
        normalized = unicodedata.normalize("NFKC", text).casefold()
        if family == "en":
            return _ENGLISH_TOKEN_RE.findall(normalized)

        pattern = _ZH_TOKEN_RE if family == "zh" else _JA_TOKEN_RE
        tokens: list[str] = []
        for match in pattern.finditer(normalized):
            part = match.group()
            if part[0].isascii():
                tokens.append(part)
                continue
            tokens.extend(part)
            tokens.extend(part[index:index + 2] for index in range(len(part) - 1))
        return tokens


class TranslationMemoryVectorizer:
    """Fit a stable vocabulary and encode language-aware TF-IDF sparse vectors."""

    def __init__(
        self,
        version: str = TFIDF_VERSION,
        max_features: int = 50_000,
        tokenizer: SentenceTokenizer | None = None,
    ) -> None:
        if not version.strip():
            raise ValueError("version must not be empty")
        if max_features < 1:
            raise ValueError("max_features must be greater than 0")
        self.version = version
        self.max_features = max_features
        self.tokenizer = tokenizer or SentenceTokenizer()
        self.vocabulary: dict[tuple[str, str], int] = {}
        self._document_frequency: Counter[tuple[str, str]] = Counter()
        self._document_count: int | None = None

    def fit(self, entries: Iterable[tuple[str, str]]) -> TranslationMemoryVectorizer:
        document_frequency: Counter[tuple[str, str]] = Counter()
        document_count = 0
        for text, language in entries:
            family = language_family(language)
            tokens = set(self.tokenizer.tokenize(text, family))
            document_frequency.update((family, token) for token in tokens)
            document_count += 1

        selected = sorted(
            document_frequency,
            key=lambda feature: (-document_frequency[feature], feature[0], feature[1]),
        )[: self.max_features]
        self.vocabulary = {feature: index for index, feature in enumerate(selected)}
        self._document_frequency = document_frequency
        self._document_count = document_count
        return self

    @property
    def num_features(self) -> int:
        # The SDK requires a positive dimension, including for an empty corpus.
        return max(1, len(self.vocabulary))

    def encode(self, text: str, language: str) -> SparseVector:
        if self._document_count is None:
            raise RuntimeError("fit(entries) must be called before encode(text, language)")
        family = language_family(language)
        counts = Counter(self.tokenizer.tokenize(text, family))
        weighted: list[tuple[int, float]] = []
        for token, term_count in counts.items():
            feature = (family, token)
            feature_id = self.vocabulary.get(feature)
            if feature_id is None:
                continue
            document_frequency = self._document_frequency[feature]
            inverse_document_frequency = math.log(
                (self._document_count + 1) / (document_frequency + 1)
            ) + 1.0
            term_frequency = 1.0 + math.log(term_count)
            weighted.append((feature_id, term_frequency * inverse_document_frequency))

        norm = math.sqrt(sum(weight * weight for _, weight in weighted))
        if norm == 0.0:
            return []
        return sorted((feature_id, weight / norm) for feature_id, weight in weighted)


class SemanticSparseProjector:
    """Map normalized dense embeddings to stable non-negative angular hash features."""

    def __init__(self, seed: int = 1729, projection_count: int = 256) -> None:
        if projection_count < 1:
            raise ValueError("projection_count must be greater than 0")
        self.seed = seed
        self.projection_count = projection_count
        self._projections: list[list[float]] | None = None
        self._embedding_dimension: int | None = None

    @property
    def num_features(self) -> int:
        return self.projection_count * 2

    def encode(self, embedding: Iterable[float]) -> SparseVector:
        values = [float(value) for value in embedding]
        if not values:
            raise ValueError("embedding must not be empty")
        if any(not math.isfinite(value) for value in values):
            raise ValueError("embedding values must be finite")
        if self._embedding_dimension is not None and len(values) != self._embedding_dimension:
            raise ValueError("embedding dimension changed for this projector")

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            raise ValueError("embedding norm must be greater than 0")
        normalized = [value / norm for value in values]
        if self._projections is None:
            self._embedding_dimension = len(values)
            generator = random.Random(self.seed)
            self._projections = [
                [generator.gauss(0.0, 1.0) for _ in normalized]
                for _ in range(self.projection_count)
            ]

        sparse: SparseVector = []
        for index, projection in enumerate(self._projections):
            dot_product = sum(value * weight for value, weight in zip(normalized, projection))
            sparse.append((2 * index if dot_product >= 0.0 else 2 * index + 1, 1.0))
        return sparse


class HuggingFaceSemanticEncoder:
    """Lazily load a sentence-transformers model from a previously downloaded directory."""

    def __init__(self, model_id: str, model_path: Path) -> None:
        self.model_id = model_id
        self.model_path = Path(model_path)
        self._model = None

    def encode(self, text: str) -> list[float]:
        if self._model is None:
            if not self.model_path.is_dir():
                raise FileNotFoundError(
                    f"Model {self.model_id} is not downloaded at {self.model_path}; "
                    "see the TM semantic model download instructions in README.md"
                )
            try:
                sentence_transformers = importlib.import_module("sentence_transformers")
            except ImportError as exc:
                raise RuntimeError(
                    "Semantic models require the optional dependencies; run `uv sync --extra semantic`"
                ) from exc
            self._model = sentence_transformers.SentenceTransformer(str(self.model_path))

        embedding = self._model.encode(text, normalize_embeddings=True, convert_to_numpy=True)
        return [float(value) for value in embedding.tolist()]


class SentenceProcessor:
    """Select per-language semantic or built-in sparse vector processing."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        tokenizer: SentenceTokenizer | None = None,
        vectorizer: TranslationMemoryVectorizer | None = None,
        semantic_encoder_factory=HuggingFaceSemanticEncoder,
    ) -> None:
        self.settings = settings or app_settings
        self.tokenizer = tokenizer or SentenceTokenizer()
        self.vectorizer = vectorizer or TranslationMemoryVectorizer(tokenizer=self.tokenizer)
        self.semantic_encoder_factory = semantic_encoder_factory
        self._semantic_encoders: dict[str, HuggingFaceSemanticEncoder] = {}
        self._semantic_projectors: dict[str, SemanticSparseProjector] = {}

    def fit(self, entries: Iterable[tuple[str, str]]) -> None:
        self.vectorizer.fit(entries)

    def encode(self, text: str, language: str) -> SparseVector:
        family = language_family(language)
        if not getattr(self.settings, f"tm_semantic_model_{family}_enabled"):
            return self.vectorizer.encode(text, family)

        encoder = self._semantic_encoders.get(family)
        if encoder is None:
            model_path = getattr(self.settings, f"tm_semantic_model_{family}_path")
            encoder = self.semantic_encoder_factory(SEMANTIC_MODEL_IDS[family], model_path)
            self._semantic_encoders[family] = encoder
        projector = self._semantic_projectors.setdefault(family, SemanticSparseProjector())
        return projector.encode(encoder.encode(text))
