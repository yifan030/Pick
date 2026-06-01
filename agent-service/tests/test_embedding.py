from unittest.mock import MagicMock

from ingestion.embedding import embed_texts


class TestEmbedTexts:
    def test_returns_embeddings_from_api(self):
        client = MagicMock()
        client.embeddings.create.return_value = MagicMock(
            data=[
                MagicMock(embedding=[0.1, 0.2]),
                MagicMock(embedding=[0.3, 0.4]),
            ]
        )

        vectors = embed_texts(["标题", "正文"], client=client)

        assert vectors == [[0.1, 0.2], [0.3, 0.4]]
        client.embeddings.create.assert_called_once()
