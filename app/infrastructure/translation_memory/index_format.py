"""Versioned TM index envelope joining tokenizer metadata and the SDK index."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from collections import Counter

from translate_manager_rag import SparseMipsRetriever

from .sentence_processing import TOKENIZER_VERSION, TranslationMemoryVectorizer, language_family

_MAGIC = b"TMVEC001"
_FORMAT_VERSION = 1
_HEADER = struct.Struct(">8sHQ32s")


class TranslationMemoryIndexFormat:
    @classmethod
    def serialize(
        cls,
        vectorizer: TranslationMemoryVectorizer,
        retriever: SparseMipsRetriever,
    ) -> bytes:
        if vectorizer._document_count is None:
            raise RuntimeError("fit(entries) must be called before serializing the vectorizer")
        if retriever.feature_count != vectorizer.num_features:
            raise ValueError("retriever feature dimension does not match vectorizer")
        vocabulary = [
            [language, token, feature_id, vectorizer._document_frequency[(language, token)]]
            for (language, token), feature_id in sorted(
                vectorizer.vocabulary.items(), key=lambda item: item[1]
            )
        ]
        value = {
            "format_version": _FORMAT_VERSION,
            "tokenizer_version": TOKENIZER_VERSION,
            "vectorizer_version": vectorizer.version,
            "max_features": vectorizer.max_features,
            "document_count": vectorizer._document_count,
            "num_features": vectorizer.num_features,
            "vocabulary": vocabulary,
            "retriever": base64.b64encode(retriever.serialize()).decode("ascii"),
        }
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        header = _HEADER.pack(_MAGIC, _FORMAT_VERSION, len(encoded), hashlib.sha256(encoded).digest())
        return header + encoded

    @classmethod
    def deserialize(
        cls,
        payload: bytes,
        *,
        expected_vectorizer_version: str,
    ) -> tuple[TranslationMemoryVectorizer, SparseMipsRetriever]:
        if not isinstance(payload, bytes) or len(payload) < _HEADER.size:
            raise ValueError("invalid TM index payload")
        magic, format_version, payload_size, checksum = _HEADER.unpack(payload[: _HEADER.size])
        if magic != _MAGIC:
            raise ValueError("invalid TM index magic")
        if format_version != _FORMAT_VERSION:
            raise ValueError("unsupported TM index format version")
        encoded = payload[_HEADER.size :]
        if len(encoded) != payload_size:
            raise ValueError("invalid TM index payload length")
        if hashlib.sha256(encoded).digest() != checksum:
            raise ValueError("TM index checksum mismatch")
        try:
            value = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid TM index metadata") from exc
        if not isinstance(value, dict) or value.get("format_version") != _FORMAT_VERSION:
            raise ValueError("invalid TM index metadata version")
        if value.get("tokenizer_version") != TOKENIZER_VERSION:
            raise ValueError("incompatible tokenizer version")
        vectorizer_version = value.get("vectorizer_version")
        if vectorizer_version != expected_vectorizer_version:
            raise ValueError("incompatible vectorizer version")

        max_features = value.get("max_features")
        document_count = value.get("document_count")
        num_features = value.get("num_features")
        vocabulary_rows = value.get("vocabulary")
        if type(max_features) is not int or max_features < 1:
            raise ValueError("invalid vectorizer feature limit")
        if type(document_count) is not int or document_count < 0:
            raise ValueError("invalid vectorizer document count")
        if type(num_features) is not int or not isinstance(vocabulary_rows, list):
            raise ValueError("invalid vectorizer dimensions")

        vocabulary: dict[tuple[str, str], int] = {}
        document_frequency: Counter[tuple[str, str]] = Counter()
        for expected_id, row in enumerate(vocabulary_rows):
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError("invalid vectorizer vocabulary row")
            language, token, feature_id, frequency = row
            if not isinstance(language, str) or language_family(language) != language:
                raise ValueError("invalid vectorizer vocabulary language")
            if not isinstance(token, str) or not token or type(feature_id) is not int or feature_id != expected_id:
                raise ValueError("invalid vectorizer vocabulary feature")
            if type(frequency) is not int or frequency < 1 or frequency > document_count:
                raise ValueError("invalid vectorizer document frequency")
            key = (language, token)
            if key in vocabulary:
                raise ValueError("duplicate vectorizer vocabulary feature")
            vocabulary[key] = feature_id
            document_frequency[key] = frequency
        if num_features != max(1, len(vocabulary)):
            raise ValueError("vectorizer feature count does not match vocabulary")
        if len(vocabulary) > max_features:
            raise ValueError("vectorizer vocabulary exceeds configured feature limit")

        retriever_value = value.get("retriever")
        if not isinstance(retriever_value, str):
            raise ValueError("missing serialized retriever")
        try:
            retriever_payload = base64.b64decode(retriever_value, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("invalid serialized retriever") from exc
        retriever = SparseMipsRetriever.deserialize(retriever_payload)
        if retriever.feature_count != num_features:
            raise ValueError("retriever feature dimension does not match vectorizer")

        vectorizer = TranslationMemoryVectorizer(
            version=vectorizer_version,
            max_features=max_features,
        )
        vectorizer.vocabulary = vocabulary
        vectorizer._document_frequency = document_frequency
        vectorizer._document_count = document_count
        return vectorizer, retriever
