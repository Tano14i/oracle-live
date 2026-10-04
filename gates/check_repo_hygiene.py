"""Nessun segreto e nessun dato personale tracciato.

Il repo e' pubblico e ha gia' pubblicato per 124 giorni il token Telegram e la
chiave API-FOOTBALL in oracle_prematch/.env.prematch. Le credenziali sono state
ruotate, ma il modo di riaprire la falla e' sempre lo stesso: un file nuovo che
nessuno ha pensato a ignorare. E' appena successo con book_comparison.csv, che
contiene quali segnali sono stati giocati e a che prezzo.

La verifica controlla tre cose: che i file sensibili non siano tracciati, che
siano effettivamente ignorati (non solo assenti per caso), e che l'albero di
lavoro non abbia derive oltre l'unica eccezione dichiarata.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SENSIBILI = [
    ".env",
    "oracle_prematch/.env.prematch",
    "web_stats.json",
    "live_training_data.csv",
    "odds_history.csv",
    "book_comparison.csv",
    "vip_members.db",
]
# oracle_brain.pkl resta modificato per scelta: 56 MB su LFS per un modello di
# solo fallback. E' il cancello G7, in attesa di decisione dell'owner.
DERIVE_AMMESSE = {"oracle_brain.pkl"}

FAIL = []


def git(*args) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return out.stdout


def check(condition: bool, message: str) -> None:
    if not condition:
        FAIL.append(message)


def main() -> int:
    tracciati = set(git("ls-files").splitlines())
    for percorso in SENSIBILI:
        check(percorso not in tracciati, f"{percorso} risulta TRACCIATO")
        if (ROOT / percorso).exists():
            ignorato = subprocess.run(["git", "check-ignore", "-q", percorso],
                                      cwd=ROOT, capture_output=True)
            check(ignorato.returncode == 0,
                  f"{percorso} esiste ma non e' ignorato: il prossimo add lo porta dentro")

    # Nessun file di env tracciato oltre i template .example.
    env_tracciati = [p for p in tracciati if "/.env" in p or p.startswith(".env")]
    non_example = [p for p in env_tracciati if not p.endswith(".example")]
    check(not non_example, f"file di env tracciati oltre i template: {non_example}")

    derive = set()
    for riga in git("status", "--porcelain").splitlines():
        if len(riga) > 3:
            derive.add(riga[3:].strip().strip('"'))
    impreviste = derive - DERIVE_AMMESSE
    check(not impreviste, f"derive impreviste nell'albero: {sorted(impreviste)}")

    if FAIL:
        for message in FAIL:
            print("FALLITO:", message)
        return 1
    print(f"{len(SENSIBILI)} percorsi sensibili non tracciati e ignorati; "
          f"derive ammesse: {sorted(DERIVE_AMMESSE)}")
    print("repo hygiene verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
