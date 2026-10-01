"""La quota reale arriva dopo l'apertura, e va scritta sulla riga esistente.

Il book pubblica il mercato in-play intorno al minuto 3-10 (mediana 6 su 235
rilevazioni), il bot apre al minuto 1-2. Al momento dell'apertura il prezzo
spesso non esiste ancora: se non lo si cerca piu', OpenOdd resta vuota e il
P/L finisce sulla quota di config, che e' 1.45 contro una mediana reale di 1.36.
"""
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_odds_gate import ol  # noqa: F401  (fixture condivisa)

COLS = ["SignalKey", "Market", "Minute", "OpenOdd", "Status", "Outcome"]


def seed(ol, rows):  # noqa: F811
    pd.DataFrame(rows, columns=COLS).to_csv(ol.LIVE_TRAINING_DATA_PATH, index=False)


def read(ol):  # noqa: F811
    return pd.read_csv(ol.LIVE_TRAINING_DATA_PATH)


def test_scrive_la_quota_sulla_riga_giusta(ol):  # noqa: F811
    seed(ol, [
        ["111:OVER 0.5 HT", "OVER 0.5 HT", 1, None, "pending", ""],
        ["222:OVER 0.5 HT", "OVER 0.5 HT", 2, None, "pending", ""],
    ])
    ol.update_live_training_odd("111:OVER 0.5 HT", 1.36)
    df = read(ol).set_index("SignalKey")
    assert df.loc["111:OVER 0.5 HT", "OpenOdd"] == pytest.approx(1.36)
    assert pd.isna(df.loc["222:OVER 0.5 HT", "OpenOdd"])


def test_chiave_inesistente_non_rompe_niente(ol):  # noqa: F811
    seed(ol, [["111:OVER 0.5 HT", "OVER 0.5 HT", 1, None, "pending", ""]])
    ol.update_live_training_odd("999:NON ESISTE", 2.00)
    assert len(read(ol)) == 1


def test_aggiorna_tutte_le_copie_della_stessa_chiave(ol):  # noqa: F811
    """Lo storico ha ancora 26.748 righe duplicate: la quota va su tutte."""
    seed(ol, [
        ["111:OVER 0.5 HT", "OVER 0.5 HT", 1, None, "pending", ""],
        ["111:OVER 0.5 HT", "OVER 0.5 HT", 4, None, "pending", ""],
    ])
    ol.update_live_training_odd("111:OVER 0.5 HT", 1.50)
    assert (read(ol)["OpenOdd"] == 1.50).all()
