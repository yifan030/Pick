from unittest.mock import MagicMock, patch

from src.storage.embedding import embed_texts


class TestEmbedTexts:
    def test_returns_embeddings_from_api(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output = {
            "embeddings": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }

        with patch("src.storage.embedding.TextEmbedding.call", return_value=mock_response):
            vectors = embed_texts(["标题", "正文"])

        assert vectors == [[0.1, 0.2], [0.3, 0.4]]

    def test_empty_list_returns_empty_list(self):
        assert embed_texts([]) == []

    def test_single_text(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.output = {
            "embeddings": [
                {"embedding": [0.5, 0.6]},
            ]
        }

        with patch("src.storage.embedding.TextEmbedding.call", return_value=mock_response):
            vectors = embed_texts(["hello"])

        assert vectors == [[0.5, 0.6]]
