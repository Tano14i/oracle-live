"""Gli strumenti per capire se il bot guadagna, non solo se indovina.

Un segnale e' redditizio solo quando il suo win rate supera la probabilita'
implicita nella quota. Misurato su 106 segnali prezzati, oggi non lo e': OVER
0.5 HT fa -11%, NEXT GOAL -3.9%. Questi test proteggono i tre pezzi che
servono per cambiare quel numero senza raccontarsi storie.
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_odds_gate import ol  # noqa: F401  (fixture condivisa)

import trainer_v2


# --- campionamento delle quote lunghe -------------------------------------

def sample(ol, odd, minute=12, total_goals=0, market=None, budget=0):  # noqa: F811
    """Chiama il campionatore con una quota finta, senza toccare la rete."""
    market = market or ol.MARKET_OVER05_HT
    original = ol.fetch_live_market_odd
    ol.fetch_live_market_odd = lambda *a, **k: odd
    try:
        debug = {"long_odds_sampled": budget}
        got = ol.evaluate_long_odds_sample(market, minute, total_goals, 0.55, 1, {}, debug)
        return got, debug
    finally:
        ol.fetch_live_market_odd = original


def test_quota_lunga_apre_uno_shadow(ol):  # noqa: F811
    """La fascia 1.60-2.50 e' l'unica con margine positivo misurato (+11.3)."""
    got, _ = sample(ol, 1.85)
    assert got is not None
    assert got["tier"] == ol.TIER_LEARNING      # mai pubblicato: compra dati, non rischia
    assert "1.85" in got["reason"]


def test_quota_corta_non_viene_campionata(ol):  # noqa: F811
    got, _ = sample(ol, 1.30)
    assert got is None


def test_quota_troppo_lunga_non_viene_campionata(ol):  # noqa: F811
    got, _ = sample(ol, 4.00)
    assert got is None


def test_quota_ignota_non_apre_niente(ol):  # noqa: F811
    got, _ = sample(ol, None)
    assert got is None


def test_tetto_per_scansione_rispettato(ol):  # noqa: F811
    """Senza tetto il campionamento brucerebbe la quota API."""
    got, _ = sample(ol, 1.85, budget=ol.LONG_ODDS_PER_SCAN)
    assert got is None


def test_niente_chiamata_quote_fuori_finestra(ol):  # noqa: F811
    """I filtri gratuiti vengono prima della chiamata a pagamento."""
    got, debug = sample(ol, 1.85, minute=2)
    assert got is None
    assert debug["long_odds_sampled"] == 0      # la quota non e' stata chiesta


def test_niente_campionamento_se_il_punteggio_non_e_zero_zero(ol):  # noqa: F811
    got, debug = sample(ol, 1.85, total_goals=1)
    assert got is None
    assert debug["long_odds_sampled"] == 0


# --- calibrazione ----------------------------------------------------------

def test_sotto_le_300_righe_si_usa_sigmoid():
    """Isotonic su pochi dati sovradatta la curva di calibrazione."""
    model = trainer_v2.build_calibrated_model(150, min_class_count=50)
    assert getattr(model, "method", None) == "sigmoid"


def test_sopra_le_300_righe_si_usa_isotonic():
    model = trainer_v2.build_calibrated_model(1089, min_class_count=200)
    assert getattr(model, "method", None) == "isotonic"


def test_classe_minoritaria_troppo_piccola_torna_alla_foresta_nuda():
    """Meglio un modello non calibrato che un retrain che fallisce."""
    model = trainer_v2.build_calibrated_model(1000, min_class_count=1)
    assert not hasattr(model, "method")


def test_tabella_di_affidabilita_misura_lo_scarto():
    probs = np.array([0.9, 0.9, 0.9, 0.9, 0.3, 0.3])
    truth = np.array([1, 1, 0, 0, 0, 0])
    rows = trainer_v2.reliability_table(probs, truth, bins=5)
    alta = [r for r in rows if r["mean_prob"] > 0.8][0]
    assert alta["n"] == 4
    assert alta["real_wr"] == pytest.approx(0.5)   # predetto 0.9, reale 0.5


# --- quote di fallback -----------------------------------------------------

MEDIANE_MISURATE = {"OVER 0.5 HT": 1.50, "NEXT GOAL LIVE": 1.04, "OVER 1.5 HT": 2.10}


def test_nessun_fallback_sopra_la_mediana_misurata(ol):  # noqa: F811
    """Un fallback generoso non rende redditizio il bot, rende falso il report.

    QUOTA_NEXT_GOAL valeva 1.75 contro una mediana reale di 1.04: il report per
    market annunciava +59.9% di ROI su un market che misura -3.9%.
    """
    for market, mediana in MEDIANE_MISURATE.items():
        fallback = ol.get_market_quota(market)
        assert fallback <= mediana + 1e-9, (
            f"{market}: fallback {fallback} sopra la mediana misurata {mediana}"
        )
