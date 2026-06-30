from unittest.mock import MagicMock, patch

from src.storage.embedding import embed_texts


class TestEmbedTexts:
    def test_returns_embeddings_from_api(self):
        fake_client = MagicMock()
        fake_client.embeddings.create.return_value = MagicMock(
            data=[
                MagicMock(embedding=[0.1, 0.2], index=0),
                MagicMock(embedding=[0.3, 0.4], index=1),
            ]
        )

        with patch("src.storage.embedding._get_client", return_value=fake_client):
            vectors = embed_texts(["标题", "正文"])

        assert vectors == [[0.1, 0.2], [0.3, 0.4]]
        fake_client.embeddings.create.assert_called_once()

    def test_empty_list_returns_empty_list(self):
        assert embed_texts([]) == []

    def test_single_text(self):
        fake_client = MagicMock()
        fake_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.5, 0.6], index=0)]
        )

        with patch("src.storage.embedding._get_client", return_value=fake_client):
            vectors = embed_texts(["hello"])

        assert vectors == [[0.5, 0.6]]
