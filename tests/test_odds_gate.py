"""Quota minima per market e tier.

Le soglie vengono dal breakeven sul limite inferiore dell'IC 95% del win rate
misurato, dopo la deduplicazione del dataset e la riparazione delle 591
etichette NEXT GOAL sbagliate. Questi test fissano il comportamento, non i
numeri: se un giorno i numeri cambiano si cambiano qui in un posto solo.
"""
import os
import sys
import types as pytypes

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def ol(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ol")
    for k, v in {
        "TOKEN_LIVE": "123:abc", "CHAT_ID": "1", "CHANNEL_ID": "@c", "API_KEY": "k",
        "VIP_CHANNEL_ID": "@v", "ODDS_GATE_STRICT": "0",
        "WEB_DATA_PATH": str(tmp / "web.json"), "MEMBERS_DB_PATH": str(tmp / "m.db"),
        "LOG_FILE_PATH": str(tmp / "log.txt"), "LIVE_TRAINING_DATA_PATH": str(tmp / "live.csv"),
        "MISSING_TEAMS_QUEUE_PATH": str(tmp / "q.json"), "MODEL_PATH": str(tmp / "brain.pkl"),
        "CSV_PATH": str(tmp / "Matches.csv"),
    }.items():
        os.environ[k] = v

    import telebot

    class FakeBot:
        def __init__(self, *a, **k):
            self.sent = []

        def message_handler(self, *a, **k):
            return lambda f: f

        def callback_query_handler(self, *a, **k):
            return lambda f: f

        def __getattr__(self, name):
            if name.endswith("_handler"):
                return lambda *a, **k: (lambda f: f)
            return lambda *a, **k: None

    telebot.TeleBot = FakeBot
    import importlib
    import config
    importlib.reload(config)
    import oracle_live
    importlib.reload(oracle_live)
    return oracle_live


def test_minimo_dipende_da_market_e_tier(ol):
    """Lo stesso tier chiede quote diverse su market diversi: e' il punto."""
    assert ol.get_min_live_odd(ol.MARKET_OVER05_HT, ol.TIER_GAMBLING) == 1.60
    assert ol.get_min_live_odd(ol.MARKET_NEXT_GOAL, ol.TIER_GAMBLING) == 1.20


def test_approved_su_over05_chiede_piu_di_gambling(ol):
    """APPROVED vince il 49.7% su questo market, GAMBLING il 71.7%.

    Il tier non ordina il win rate: la soglia deve seguire il dato, non il nome.
    """
    approved = ol.get_min_live_odd(ol.MARKET_OVER05_HT, ol.TIER_APPROVED)
    gambling = ol.get_min_live_odd(ol.MARKET_OVER05_HT, ol.TIER_GAMBLING)
    assert approved > gambling


def test_tier_sconosciuto_ricade_sul_minimo_di_market(ol):
    assert ol.get_min_live_odd(ol.MARKET_OVER05_HT, ol.TIER_LEARNING) == ol.MARKET_MIN_ODDS[ol.MARKET_OVER05_HT]


def test_quota_sotto_il_minimo_viene_fermata(ol):
    skip, reason = ol.should_skip_by_odds(ol.MARKET_OVER05_HT, 1.40, ol.TIER_GAMBLING)
    assert skip is True
    assert "1.40" in reason and "1.60" in reason


def test_quota_sopra_il_minimo_passa(ol):
    skip, _ = ol.should_skip_by_odds(ol.MARKET_OVER05_HT, 1.75, ol.TIER_GAMBLING)
    assert skip is False


def test_quota_esattamente_al_minimo_passa(ol):
    skip, _ = ol.should_skip_by_odds(ol.MARKET_OVER05_HT, 1.60, ol.TIER_GAMBLING)
    assert skip is False


def test_quota_ignota_non_ferma_il_segnale(ol):
    """Con gate non strict la quota mancante non e' un motivo per scartare.

    Con ODDS_GATE_STRICT=1 erano 58 segnali su 275 buttati per cecita', non
    per economia, e senza lasciare una riga da cui imparare.
    """
    skip, reason = ol.should_skip_by_odds(ol.MARKET_OVER05_HT, None, ol.TIER_GAMBLING)
    assert skip is False


def test_quota_illeggibile_non_ferma_il_segnale(ol):
    skip, _ = ol.should_skip_by_odds(ol.MARKET_OVER05_HT, "n/d", ol.TIER_GAMBLING)
    assert skip is False


def test_market_senza_minimo_non_filtra(ol):
    skip, reason = ol.should_skip_by_odds("MARKET INESISTENTE", 1.01, ol.TIER_GAMBLING)
    assert skip is False
    assert reason == ""


def test_stato_radar_si_ricorda(ol):
    """Il radar deve tornare acceso dopo un riavvio se era acceso prima.

    Il supervisore rimetteva in piedi il processo lasciando il radar spento: il
    bot risultava vivo e non guardava una partita. E' cosi' che si perdono
    giornate senza accorgersene.
    """
    ol.set_radar_state(True)
    assert ol.stats["radar_running"] is True

    ol.stop_radar()
    assert ol.stats["radar_running"] is False
    assert ol.running is False


def test_stato_radar_sopravvive_al_salvataggio(ol):
    """Non basta ricordarlo in memoria: deve finire su disco."""
    import json

    ol.set_radar_state(True)
    with open(ol.WEB_DATA_PATH, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["radar_running"] is True
