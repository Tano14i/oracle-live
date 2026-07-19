# Importa handlers (e quindi l'intero grafo dei moduli) cosi' `import oracle_live`
# produce gli stessi effetti collaterali del vecchio monolite: check config,
# creazione bot, setup logger e registrazione degli handler telebot.
from oracle_live import handlers  # noqa: F401
