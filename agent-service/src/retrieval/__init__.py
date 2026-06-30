from __future__ import annotations

"""Memory retrieval pipeline — semantic + BM25 + entity boost → rank fusion.

Public API:
- RetrievalGateway: orchestrates three-way parallel search
- SemanticSearch: dense vector search via Milvus
- BM25Search: sparse vector search via Milvus
- EntityBoost: Neo4j subgraph traversal
- ScoreNormalizer: per-channel score normalization to [0,1]
- RankFusion: weighted fusion of normalized scores
- PromptBuilder: augments system prompt with retrieved memories
- FeedbackProcessor: quality feedback loop
- ConsistencyChecker: dual-write orphan cleanup
"""

# Imports for modules planned in subsequent tasks. Each is guarded so that
# the package can be imported before all sub-modules are written.

try:
    from src.retrieval.gateway import RetrievalGateway  # noqa: F401
except ModuleNotFoundError:
    RetrievalGateway = None  # type: ignore

try:
    from src.retrieval.fusion import ScoreNormalizer, RankFusion  # noqa: F401
except ModuleNotFoundError:
    ScoreNormalizer = None  # type: ignore
    RankFusion = None  # type: ignore

try:
    from src.retrieval.prompt_builder import PromptBuilder  # noqa: F401
except ModuleNotFoundError:
    PromptBuilder = None  # type: ignore

try:
    from src.retrieval.feedback import FeedbackProcessor  # noqa: F401
except ModuleNotFoundError:
    FeedbackProcessor = None  # type: ignore

try:
    from src.retrieval.consistency import ConsistencyChecker  # noqa: F401
except ModuleNotFoundError:
    ConsistencyChecker = None  # type: ignore

try:
    from src.retrieval.feedback_consumer import FeedbackConsumer  # noqa: F401
except ModuleNotFoundError:
    FeedbackConsumer = None  # type: ignore

try:
    from src.retrieval.semantic_search import SemanticSearch  # noqa: F401
except ModuleNotFoundError:
    SemanticSearch = None  # type: ignore

try:
    from src.retrieval.bm25_search import BM25Search  # noqa: F401
except ModuleNotFoundError:
    BM25Search = None  # type: ignore

try:
    from src.retrieval.entity_boost import EntityBoost  # noqa: F401
except ModuleNotFoundError:
    EntityBoost = None  # type: ignore

__all__ = [
    "RetrievalGateway",
    "SemanticSearch",
    "BM25Search",
    "EntityBoost",
    "ScoreNormalizer",
    "RankFusion",
    "PromptBuilder",
    "FeedbackProcessor",
    "ConsistencyChecker",
    "FeedbackConsumer",
]
