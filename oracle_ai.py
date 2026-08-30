"""Strato di analisi AI per i segnali del bot.

Divisione dei ruoli
-------------------
La selezione resta ai numeri misurati: finestra di 50 partite, ritmo di primo
tempo sulle sole partite a dato noto, soglie 1.10/1.30/1.60 verificate su
357.573 partite con gruppo di controllo. L'AI non sceglie le partite.

L'AI fa due cose che i numeri non sanno fare:

1. **spiega** il segnale in prosa leggibile, partendo dai dati misurati, per il
   canale VIP;
2. **cerca il contesto qualitativo** che il dataset non contiene - infortuni,
   formazioni annunciate, squalifiche, motivazione di classifica, meteo - e puo'
   alzare un avviso o consigliare di saltare.

Il veto e' consultivo e sempre motivato: se l'AI non trova nulla di rilevante,
il segnale resta quello che il filtro ha deciso.

Regola non negoziabile: l'AI non inventa statistiche. Riceve i numeri del bot e
deve ragionare su quelli; per il contesto usa la ricerca web e cita le fonti.

Uso
---
    from oracle_ai import analyze_signal
    result = analyze_signal(signal_context)
    print(result["analysis"])       # testo per il canale
    print(result["verdict"])        # CONFERMA | ATTENZIONE | SALTA
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict

try:
    import anthropic
except ImportError:  # lo strato AI e' opzionale
    anthropic = None

from config import get_setting

MODEL = get_setting("ORACLE_AI_MODEL", "claude-opus-5")
ENABLED = get_setting("ORACLE_AI_ENABLED", "0").lower() in {"1", "true", "yes"}
API_KEY = get_setting("ANTHROPIC_API_KEY")

# Prompt stabile: identico a ogni chiamata, quindi si presta alla cache.
SYSTEM_PROMPT = """Sei l'analista di un bot di segnali calcistici live. Scrivi in italiano.

COSA FA IL BOT
Il bot punta su OVER 0.5 PRIMO TEMPO: vince se viene segnato almeno un gol nei
primi 45 minuti. Entra in diretta fra il minuto 1 e il 5, a partita ancora 0-0.

COME SELEZIONA
Calcola il ritmo di primo tempo delle due squadre sulle ultime 50 partite, usando
solo quelle in cui il dato del primo tempo esiste davvero. La media della coppia
determina il tier:
  - GAMBLING  ritmo >= 1.10  -> win rate misurato 69.9%
  - CAUTION   ritmo >= 1.30  -> win rate misurato 75.0%
  - APPROVED  ritmo >= 1.60  -> win rate misurato 81.4%
Misurato su 357.573 partite dal 2021, con gruppo di controllo: le partite che il
filtro scarta si fermano al 63.8%, sotto il tasso base del 70.2%.

IL TUO COMPITO
1. Spiega il segnale in 3-5 frasi, partendo dai numeri che ricevi. Prosa scorrevole,
   niente elenchi puntati, tono da analista competente e non da venditore.
2. Cerca sul web notizie recenti sulle due squadre: infortuni, formazioni previste,
   squalifiche, situazione di classifica, condizioni del campo. Cita cosa trovi.
3. Dai un verdetto.

REGOLE
- Non inventare MAI statistiche. Se un numero non te l'ho dato e non l'hai trovato
  con una fonte, non scriverlo.
- Se la ricerca non trova nulla di rilevante, dillo e conferma il segnale: l'assenza
  di notizie non e' un motivo per dubitare.
- Alza il verdetto ad ATTENZIONE solo per fatti concreti che riducono i gol attesi:
  assenza di piu' attaccanti titolari, squadra che ha gia' ottenuto il proprio
  obiettivo, campo impraticabile, partita con posta in gioco nulla.
- Usa SALTA solo per fatti gravi e verificati: partita a rischio rinvio, formazioni
  ampiamente rimaneggiate su entrambe le squadre.
- Il quadro statistico e' gia' stato validato. Non rimetterlo in discussione con
  ragionamenti generici sul calcio: aggiungi solo cio' che i numeri non vedono.

FORMATO
Scrivi l'analisi, poi come ULTIMA riga esattamente:
VERDETTO: CONFERMA
oppure VERDETTO: ATTENZIONE - <motivo in poche parole>
oppure VERDETTO: SALTA - <motivo in poche parole>"""


@dataclass(slots=True)
class SignalContext:
    """I numeri misurati dal bot, che l'AI deve usare senza alterarli."""
    home_team: str
    away_team: str
    country: str
    league: str
    market: str
    tier: str
    minute: int
    score: str
    pair_ht_pace: float
    worst_ht_pace: float
    pair_total_pace: float
    known_matches: str
    live_odd: float | None = None
    kickoff_utc: str | None = None


def _build_user_message(ctx: SignalContext) -> str:
    odd = f"{ctx.live_odd:.2f}" if ctx.live_odd else "non disponibile"
    return (
        f"PARTITA: {ctx.home_team} vs {ctx.away_team}\n"
        f"COMPETIZIONE: {ctx.country} - {ctx.league}\n"
        f"STATO: minuto {ctx.minute}, punteggio {ctx.score}\n"
        f"MERCATO: {ctx.market}\n"
        f"TIER ASSEGNATO: {ctx.tier}\n"
        f"RITMO PRIMO TEMPO DELLA COPPIA: {ctx.pair_ht_pace:.2f} "
        f"(la squadra piu' debole delle due: {ctx.worst_ht_pace:.2f})\n"
        f"RITMO GOL TOTALI: {ctx.pair_total_pace:.2f}\n"
        f"PARTITE CON PRIMO TEMPO NOTO: {ctx.known_matches}\n"
        f"QUOTA LIVE: {odd}\n\n"
        "Analizza questo segnale e cerca il contesto recente sulle due squadre."
    )


_VERDICT_RE = re.compile(r"VERDETTO:\s*(CONFERMA|ATTENZIONE|SALTA)\s*(?:-\s*(.*))?",
                         re.IGNORECASE)


def _parse_verdict(text: str) -> tuple[str, str]:
    match = None
    for match in _VERDICT_RE.finditer(text):
        pass  # l'ultima occorrenza e' quella finale richiesta dal formato
    if not match:
        # Nessun verdetto leggibile: non si inventa, si lascia decidere al filtro.
        return "CONFERMA", "verdetto non leggibile nella risposta"
    return match.group(1).upper(), (match.group(2) or "").strip()


def is_available() -> bool:
    return bool(ENABLED and API_KEY and anthropic is not None)


def analyze_signal(ctx: SignalContext, timeout: float = 90.0) -> dict:
    """Analizza un segnale gia' selezionato dal filtro numerico.

    Restituisce sempre un dizionario utilizzabile: se lo strato AI e' spento o
    fallisce, il segnale prosegue confermato, perche' la decisione statistica non
    dipende da questa analisi.
    """
    if not is_available():
        return {"available": False, "analysis": "", "verdict": "CONFERMA",
                "reason": "strato AI non attivo", "context": asdict(ctx)}

    client = anthropic.Anthropic(api_key=API_KEY, timeout=timeout)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                # Il prompt e' identico a ogni segnale: la cache lo rende quasi gratuito.
                "cache_control": {"type": "ephemeral"},
            }],
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 4,
            }],
            messages=[{"role": "user", "content": _build_user_message(ctx)}],
        )
    except Exception as exc:  # rete, quota, rifiuto: il segnale non si blocca
        return {"available": False, "analysis": "", "verdict": "CONFERMA",
                "reason": f"analisi non riuscita: {exc}", "context": asdict(ctx)}

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        return {"available": False, "analysis": "", "verdict": "CONFERMA",
                "reason": f"richiesta declinata ({getattr(detail, 'category', 'n/d')})",
                "context": asdict(ctx)}

    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    verdict, reason = _parse_verdict(text)
    analysis = _VERDICT_RE.sub("", text).strip()
    return {
        "available": True,
        "analysis": analysis,
        "verdict": verdict,
        "reason": reason,
        "model": response.model,
        "usage": {
            "input": response.usage.input_tokens,
            "output": response.usage.output_tokens,
            "cache_read": getattr(response.usage, "cache_read_input_tokens", 0),
        },
        "context": asdict(ctx),
    }


if __name__ == "__main__":
    demo = SignalContext(
        home_team="Vard", away_team="Os", country="Norway",
        league="3. Division - Girone 3", market="OVER 0.5 HT", tier="APPROVED",
        minute=3, score="0-0", pair_ht_pace=2.13, worst_ht_pace=2.00,
        pair_total_pace=3.41, known_matches="37/38", live_odd=1.45,
    )
    out = analyze_signal(demo)
    print(f"disponibile: {out['available']}")
    if out.get("reason"):
        print(f"nota: {out['reason']}")
    print()
    print(out["analysis"])
    print()
    print(f"VERDETTO: {out['verdict']}")
    if out.get("usage"):
        u = out["usage"]
        print(f"\ntoken: {u['input']} in, {u['output']} out, {u['cache_read']} da cache")
