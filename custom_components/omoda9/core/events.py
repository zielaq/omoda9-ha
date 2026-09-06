"""Esiti come STRUTTURA, non come frase già scritta.

`core/` non importa Home Assistant (vedi AGENTS.md, "No Home Assistant imports in core/"):
non può quindi sapere in che lingua tradurre nulla. Fino a questa release aggirava il
problema scrivendo le frasi direttamente in italiano (con qualche pezza bilingue qua e là,
vedi `_coda_saltati` in `commands.py`), e la lingua dell'utente finiva ignorata.

Da qui in avanti un punto che deve comunicare qualcosa all'utente costruisce un `Esito`:
un CODICE stabile (`code`), i PARAMETRI per riempirlo (`params`) e un testo INGLESE già
completo (`text_en`) come rete di sicurezza — log, sandbox, sviluppo, o semplicemente una
chiave di traduzione che manca in una lingua. La traduzione vera vive nella sezione
`"esito"` di `translations/*.json` e viene applicata dalla warstwa Home Assistant
(`coordinator.py`, `_traduci_esito`), MAI qui: qui non esiste `hass.config.language`.

`Esito.__str__` ritorna `text_en`, quindi tutto ciò che oggi fa `str(m)` o `f"{m}"` — log,
`CommandError`, troncamento a 255 caratteri — continua a funzionare esattamente come prima
anche per un `Esito` mai tradotto. Fallire in inglese, non fallire silenziosamente: è la
stessa disciplina "fail open" del resto del componente, applicata alla lingua invece che al
comando."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Esito:
    """`code` è la chiave sotto `esito.messages.<code>` nei file di traduzione. `params` sono
    i valori con cui riempire il modello (`str.format`, quindi placeholder `{nome}`) — sia
    quelli finali (numeri, secondi, testo grezzo del backend) sia le CHIAVI da tradurre a loro
    volta (`command_key`, `meaning_key`: vedi `_traduci_esito` in coordinator.py). `text_en` è
    la frase italiana... anzi inglese, già completa, per chi non traduce."""

    code: str
    params: dict[str, Any] = field(default_factory=dict)
    text_en: str = ""

    def __str__(self) -> str:
        return self.text_en or self.code


# ───────────────────────── codici di evento (chiusi, stabili) ─────────────────────────
# Chiave = nome sotto `esito.messages` in translations/*.json. Cambiarli è come rinominare
# una colonna di database: va fatto ovunque insieme (test_traduzioni_esito.py se ne accorge).

UNKNOWN_COMMAND = "unknown_command"
SESSION_EXPIRED = "session_expired"
TASKID_MINTING_DISABLED = "taskid_minting_disabled"
TASKID_RENEWING = "taskid_renewing"
MINTING_TASKID = "minting_taskid"
NETWORK_ERROR = "network_error"
SENDING_COMMAND = "sending_command"
COMMAND_RESULT = "command_result"
COMMAND_CONFIRMED = "command_confirmed"
COMMAND_IN_PROGRESS = "command_in_progress"
COMMAND_CONFIRMED_RAW = "command_confirmed_raw"
PARTIAL_EXECUTION = "partial_execution"
PARTIAL_EXECUTION_CLIMATE_ONLY = "partial_execution_climate_only"

WAKE_BUSY = "wake_busy"
WAKE_ERROR = "wake_error"
WAKE_COOLDOWN = "wake_cooldown"
WAKE_ALREADY_AWAKE = "wake_already_awake"
WAKE_LOGGING_IN = "wake_logging_in"
WAKE_SESSION_EXPIRED = "wake_session_expired"
WAKE_SENT = "wake_sent"
WAKE_RATE_LIMITED = "wake_rate_limited"
WAKE_NOT_ACCEPTED = "wake_not_accepted"
WAKE_TEST_SKIPPED = "wake_test_skipped"
WAKE_ONLINE_MQTT = "wake_online_mqtt"
WAKE_ONLINE_REST = "wake_online_rest"
WAKE_POLLING = "wake_polling"
WAKE_STILL_ASLEEP = "wake_still_asleep"
WAKING_CAR_COUNTDOWN = "waking_car_countdown"

SESSION_OK = "session_active"
SESSION_NETWORK_ERROR = "session_network_error"
SESSION_EXPIRED_LONG = "session_expired_long"
SESSION_RESTORED = "session_restored"
SESSION_TOKEN_MINTED_STILL_KO = "session_token_minted_still_ko"

ALL_CODES = (
    UNKNOWN_COMMAND, SESSION_EXPIRED, TASKID_MINTING_DISABLED, TASKID_RENEWING,
    MINTING_TASKID,
    NETWORK_ERROR, SENDING_COMMAND, COMMAND_RESULT, COMMAND_CONFIRMED,
    COMMAND_IN_PROGRESS, COMMAND_CONFIRMED_RAW, PARTIAL_EXECUTION,
    PARTIAL_EXECUTION_CLIMATE_ONLY,
    WAKE_BUSY, WAKE_ERROR, WAKE_COOLDOWN, WAKE_ALREADY_AWAKE, WAKE_LOGGING_IN,
    WAKE_SESSION_EXPIRED, WAKE_SENT, WAKE_RATE_LIMITED, WAKE_NOT_ACCEPTED,
    WAKE_TEST_SKIPPED, WAKE_ONLINE_MQTT, WAKE_ONLINE_REST, WAKE_POLLING,
    WAKE_STILL_ASLEEP, WAKING_CAR_COUNTDOWN,
    SESSION_OK, SESSION_NETWORK_ERROR, SESSION_EXPIRED_LONG, SESSION_RESTORED,
    SESSION_TOKEN_MINTED_STILL_KO,
)
