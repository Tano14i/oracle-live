"""Il tier deve ordinare la confidenza, non contraddirla.

Storia di questi test: su OVER 0.5 HT il tier era invertito. APPROVED vinceva
il 49,7% e GAMBLING il 71,7%, perche' 172 dei 174 APPROVED erano promozioni
Titan con probabilita' media 0,55 (minimi a 0,05) contro 0,79 di CAUTION. Le
promozioni ora annotano e non alzano piu' il tier.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_odds_gate import ol  # noqa: F401  (fixture condivisa)


def pace(**over):
    """Coppia con ritmo alto: passa i pre-filtri, lascia decidere la probabilita'."""
    base = {
        "matches": 40,
        "avg_total_goals": 2.60,
        "avg_ht_goals": 1.70,
        "home_avg_ht_goals": 0.90,
        "away_avg_ht_goals": 0.90,
        "home_avg_total_goals": 2.60,
        "away_avg_total_goals": 2.60,
    }
    base.update(over)
    return base


def tier_at(ol, prob, **over):  # noqa: F811
    got = ol.evaluate_signal_candidate(ol.MARKET_OVER05_HT, 3, 0, prob, pace(**over))
    return got["tier"] if got else None


def test_tier_cresce_con_la_probabilita(ol):  # noqa: F811
    """A ritmo costante, alzare la probabilita' non puo' abbassare il tier."""
    ordine = {None: 0, ol.TIER_GAMBLING: 1, ol.TIER_CAUTION: 2, ol.TIER_APPROVED: 3}
    precedente = 0
    for prob in [0.30, 0.45, 0.52, 0.58, 0.65, 0.80, 0.95]:
        rango = ordine[tier_at(ol, prob)]
        assert rango >= precedente, f"prob {prob} ha abbassato il tier"
        precedente = rango


def test_i_tre_tier_sono_raggiungibili(ol):  # noqa: F811
    assert tier_at(ol, 0.95) == ol.TIER_APPROVED
    assert tier_at(ol, 0.58, avg_ht_goals=1.40) == ol.TIER_CAUTION
    assert tier_at(ol, 0.52, avg_ht_goals=1.15, avg_total_goals=2.10) == ol.TIER_GAMBLING


def test_sotto_la_soglia_minima_nessun_segnale(ol):  # noqa: F811
    assert tier_at(ol, 0.30) is None


def test_titan_non_alza_il_tier(ol):  # noqa: F811
    """Titan resta informativo: riporta punteggio ed etichetta, e nient'altro.

    Le regole guardano tiri, angoli e tiri in porta: informazione che il
    modello gia' vede e a cui assegna peso 0,006-0,025. Usarla per scavalcare
    il modello costava fra 5 e 16 punti di win rate in ogni banda.
    """
    payload = {"shots_on_goal": 4, "total_shots": 9, "corners": 3, "red_cards": 0}
    titan = ol.evaluate_titan_soft_layer(payload, ol.MARKET_OVER05_HT, 10, 0)
    assert titan["promote"] is True      # il livello continua a dire la sua...
    assert titan["score"] >= 3
    assert titan["label"]

    # ...ma nel radar loop non esiste piu' un evento che cambia il tier.
    assert "SIGNAL_PROMOTED" not in _source()


def test_regole_a_mano_non_aprono_da_sole():
    """Aprivano un CAUTION scavalcando il modello: 43 segnali, 27,9% di win rate.

    La condizione sul punteggio soft resta viva nella diagnostica, dove produce
    solo un'annotazione: quello che non deve tornare e' l'assegnazione di un
    motivo di allerta da cui nasce un segnale.
    """
    assert 'pressure_alert_reason = titan_soft.get("label"' not in _source()


def _source():
    with open(os.path.join(ROOT, "oracle_live.py"), encoding="utf-8") as handle:
        return handle.read()
