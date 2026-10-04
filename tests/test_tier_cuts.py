"""Il tier deve dipendere dal modello, non solo dal ritmo della coppia.

Dopo la calibrazione i segnali pubblicati stavano fra 0.861 e 0.918, e le soglie
fisse 0.60/0.56/0.50 - tarate su un modello con media 0.52 - venivano superate
dal 100% dei casi. Il tier finiva deciso dal solo ritmo HT, GAMBLING diventava
irraggiungibile (la sua fascia 1.10-1.30 e' esclusa dal pre-filtro) e un segnale
di cui il modello non era convinto poteva uscire APPROVED perche' la coppia
segna molto.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_odds_gate import ol  # noqa: F401  (fixture condivisa)


def metrics(pace):
    return {
        "matches": 40,
        "avg_total_goals": max(2.40, pace + 0.9),
        "avg_ht_goals": pace,
        "home_avg_ht_goals": 0.90,
        "away_avg_ht_goals": 0.90,
        "home_avg_total_goals": 2.60,
        "away_avg_total_goals": 2.60,
    }


def tier(ol, prob, pace):  # noqa: F811
    got = ol.evaluate_signal_candidate(ol.MARKET_OVER05_HT, 10, 0, prob, metrics(pace))
    return got["tier"] if got else None


@pytest.fixture
def cuts(ol, monkeypatch):  # noqa: F811
    """Soglie note, per non dipendere dal file scritto dall'ultimo retrain."""
    monkeypatch.setattr(ol, "tier_prob_cuts", (0.87, 0.93))
    return 0.87, 0.93


def test_ritmo_alto_non_basta_per_approved(ol, cuts):  # noqa: F811
    """Era il caso reale: prob 0.916 e ritmo 1.88 uscivano APPROVED."""
    assert tier(ol, 0.91, 1.90) == ol.TIER_CAUTION


def test_servono_entrambi_per_approved(ol, cuts):  # noqa: F811
    assert tier(ol, 0.95, 1.90) == ol.TIER_APPROVED


def test_probabilita_bassa_declassa_anche_con_ritmo_alto(ol, cuts):  # noqa: F811
    assert tier(ol, 0.86, 1.90) == ol.TIER_GAMBLING


def test_gambling_e_di_nuovo_raggiungibile(ol, cuts):  # noqa: F811
    """Con le soglie fisse non usciva piu' nemmeno un GAMBLING."""
    assert tier(ol, 0.86, 1.45) == ol.TIER_GAMBLING


def test_il_tier_non_sale_mai_sopra_il_ritmo(ol, cuts):  # noqa: F811
    """Modello convintissimo ma coppia che non segna: resta GAMBLING."""
    assert tier(ol, 0.99, 1.15) == ol.TIER_GAMBLING


def test_sotto_la_soglia_minima_niente_segnale(ol, cuts):  # noqa: F811
    assert tier(ol, 0.40, 1.90) is None


def test_file_soglie_mancante_torna_ai_valori_di_partenza(ol, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(ol, "V2_TIERS_PATH", str(tmp_path / "non-esiste.txt"))
    ol.load_tier_prob_cuts()
    assert ol.get_tier_prob_cuts() == ol.TIER_PROB_CUTS_DEFAULT


def test_file_soglie_malformato_non_rompe_niente(ol, monkeypatch, tmp_path):  # noqa: F811
    bad = tmp_path / "tiers.txt"
    bad.write_text("questo non e' un numero")
    monkeypatch.setattr(ol, "V2_TIERS_PATH", str(bad))
    ol.load_tier_prob_cuts()
    assert ol.get_tier_prob_cuts() == ol.TIER_PROB_CUTS_DEFAULT


def test_file_soglie_valido_viene_letto(ol, monkeypatch, tmp_path):  # noqa: F811
    good = tmp_path / "tiers.txt"
    good.write_text("0.8120 0.9010")
    monkeypatch.setattr(ol, "V2_TIERS_PATH", str(good))
    ol.load_tier_prob_cuts()
    assert ol.get_tier_prob_cuts() == (0.8120, 0.9010)


def test_soglie_invertite_vengono_rifiutate(ol, monkeypatch, tmp_path):  # noqa: F811
    """CAUTION sopra APPROVED renderebbe un tier irraggiungibile."""
    bad = tmp_path / "tiers.txt"
    bad.write_text("0.95 0.80")
    monkeypatch.setattr(ol, "V2_TIERS_PATH", str(bad))
    ol.load_tier_prob_cuts()
    assert ol.get_tier_prob_cuts() == ol.TIER_PROB_CUTS_DEFAULT
