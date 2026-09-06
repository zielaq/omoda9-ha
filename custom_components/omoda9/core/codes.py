#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py — Mappa UNICA dei codici di risposta tspconsole/BFF Chery → testo leggibile.

Sorgente di verità per i SOLI testi diagnostici mostrati all'utente (HA/monitor).
Prima della FASE 1 lo stesso codice (es. A07900) aveva 3 significati diversi
sparsi in commands/wake/probe/provision; questa mappa li unifica. NON cambia la
logica dei comandi: i moduli decidono il flusso sui codici, qui c'è solo la
traduzione del codice in una frase.

⚠️ Alcuni codici (in primis A07900) sono CONTESTUALI sul backend Chery: il testo
qui è quello più ricorrente/utile; ogni chiamante può aggiungere contesto.

[Task C, 2026-09-06] Questi testi sono ora il RIPIEGO inglese, non la lingua mostrata
all'utente: `core/` non importa Home Assistant e non sa in che lingua tradurre (vedi
`core/events.py`). La traduzione vera vive sotto `esito.code_meanings.<CODICE>` in
`translations/*.json`, applicata da `coordinator.py`. Il codice stesso (`"A00079"`) è la
chiave — cambiarne il testo qui aggiorna solo il ripiego, non le tre lingue tradotte."""

# Codice → frase leggibile (INGLESE: ripiego per chi non traduce — vedi sopra).
CODE_MEANING = {
    "000000": "ok ✅",
    "A00079": "command accepted ✅",
    # A00082: l'auto è OCCUPATA (processa un comando alla volta) → il comando NON è stato
    # eseguito. Transitorio: riprovare tra qualche secondo (verificato live 2026-06-21).
    "A00082": "car busy ⏳ (another command is in progress) — retry in a few seconds",
    # A00084 (i18n: "No vehicle control command permission"): l'account/veicolo non ha il
    # permesso PER QUEL comando. Sull'Omoda 9 riguarda l'avvio remoto del motore, mentre
    # clima/serratura/GPS funzionano; su una Jaecoo 7 PHEV riguarda sedili, lunotto e le macro
    # (issue #1). ⚠️ Della nostra osservazione su remoteStart (2026-06-21) NON resta traccia
    # strumentale — nessun log, nessuna cattura: sono note in prosa scritte allora. Trattarla
    # come non attestata finché non la si rimisura.
    # Il testo dice esplicitamente «non è il PIN» perché è lì che l'utente va a cercare.
    "A00084": "not authorised on this vehicle 🚫 (this is not your PIN)",
    "A00089": "invalid taskId ❌ (needs a taskId blessed by checkPassword)",
    "A00546": "invalid taskId ❌ (wrong scene in checkPassword)",
    "A00567": "incomplete checkPassword parameters ❌",
    "A00000": "expired/invalid token ❌ (redo the OTP login)",
    "A07312": "wake rate-limit 🚫 (the car is refusing further wake-ups now, try again later)",
    # A07900 è contestuale: in poll/probe = auto a riposo; coi comandi = firma o
    # car_token non validi. Testo neutro che copre il caso più frequente.
    "A07900": "car asleep / unreachable (or invalid signature/car_token) ⌛",
}


def meaning(code, default=None):
    """Ritorna la frase leggibile per `code`. Se sconosciuto ritorna `default`
    (o una stringa generica col codice grezzo). Accetta anche code=None/non-str."""
    if code is None:
        return default if default is not None else "no code"
    key = str(code)
    if key in CODE_MEANING:
        return CODE_MEANING[key]
    return default if default is not None else f"code {key}"


if __name__ == "__main__":
    for c in ("000000", "A00079", "A07900", "A99999", None):
        print(f"{c!s:>8} -> {meaning(c)}")
