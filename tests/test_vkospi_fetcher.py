from unittest.mock import Mock

from src.broker.vkospi_fetcher import VkospiFetcher


class _FakeResponse:
    def __init__(self, data=None, text=""):
        self._data = data
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


def test_vkospi_fetcher_reads_naver_ksvkospi():
    session = Mock()
    session.get.return_value = _FakeResponse(
        {
            "result": {
                "areas": [
                    {
                        "datas": [
                            {
                                "cd": "KSVKOSPI",
                                "nv": 2534,
                                "cv": -42,
                                "cr": -1.63,
                                "ms": "OPEN",
                            }
                        ]
                    }
                ]
            }
        }
    )

    quote = VkospiFetcher(session).get_current_vkospi()

    assert quote.source == "naver:KSVKOSPI"
    assert quote.value == 25.34
    assert quote.change == -0.42
    assert quote.change_rate == -1.63
    assert quote.market_status == "OPEN"


def test_vkospi_fetcher_falls_back_to_investing():
    session = Mock()
    session.get.side_effect = [
        _FakeResponse({"result": {"areas": [{"datas": []}]}}),
        _FakeResponse({"result": {"areas": [{"datas": []}]}}),
        _FakeResponse(text='<div data-test="instrument-price-last">88.02</div>'),
    ]

    quote = VkospiFetcher(session).get_current_vkospi()

    assert quote.source == "investing"
    assert quote.value == 88.02


def test_vkospi_fetcher_uses_cache():
    session = Mock()
    session.get.return_value = _FakeResponse(
        {"result": {"areas": [{"datas": [{"cd": "KSVKOSPI", "nv": 2534}]}]}}
    )
    fetcher = VkospiFetcher(session)

    assert fetcher.get_current_vkospi().value == 25.34
    assert fetcher.get_current_vkospi().value == 25.34
    assert session.get.call_count == 1
