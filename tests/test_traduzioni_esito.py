"""Task C (2026-09-06): ogni evento strutturato deve avere una traduzione nelle tre lingue.

`core/` produce ora `Esito` (codice + parametri + ripiego inglese, vedi `core/events.py`)
invece di frasi già scritte in italiano. La traduzione vera vive sotto la sezione
`"esito"` di `translations/*.json`, applicata da `Omoda9Coordinator._traduci_esito`.

Questo file è lo specchio di `test_traduzioni_complete.py`, ma per la sezione `esito`:
quello confronta le CHIAVI fra `strings.json`/`en.json`/`it.json` (`pl.json` non è
richiesto lì); qui si aggiunge — per le tre lingue, `pl.json` incluso — la garanzia più
specifica che serve a Task C:

1. ogni codice di evento in `core.events.ALL_CODES` ha un modello sotto `esito.messages`;
2. ogni comando del catalogo (`core.commands.COMMANDS`) ha un nome sotto `esito.commands`;
3. ogni codice backend (`core.codes.CODE_MEANING`) ha un significato sotto
   `esito.code_meanings`;
4. ogni modulo di `coordinator.REASON_MODULI` ha un nome sotto `esito.reason_modules`;
5. i placeholder `{nome}` di un modello sono IDENTICI nelle tre lingue — è la stessa
   validazione che farebbe Home Assistant in produzione (`translation._validate_placeholders`),
   qui prima che arrivi a un utente vero;
6. un comando eseguito con `hass.config.language = "pl"` produce davvero un
   `sensor.omoda9_esito_comando` in polacco, non l'inglese di ripiego.
"""
from __future__ import annotations

import json
import pathlib
import string

import pytest

import fixtures as FX

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "omoda9"
LANGS = ("en", "it", "pl")


def _esito(lingua: str) -> dict:
    path = PKG / "translations" / f"{lingua}.json" if lingua != "_strings" else PKG / "strings.json"
    return json.loads(path.read_text(encoding="utf-8")).get("esito", {})


def _placeholders(modello: str) -> set[str]:
    """Nomi dei placeholder `{nome}` o `{nome:formato}` in un modello `str.format`."""
    return {campo for _, campo, _, _ in string.Formatter().parse(modello) if campo}


@pytest.mark.parametrize("lingua", LANGS)
def test_ogni_codice_di_evento_ha_un_modello(lingua):
    from custom_components.omoda9.core import events as EV

    esito = _esito(lingua)
    messaggi = esito.get("messages", {})
    mancanti = sorted(c for c in EV.ALL_CODES if c not in messaggi)
    assert not mancanti, (
        f"{lingua}.json: mancano i modelli per {mancanti} — quell'esito arriverebbe "
        f"all'utente solo nel ripiego inglese di `text_en`"
    )


@pytest.mark.parametrize("lingua", LANGS)
def test_ogni_comando_del_catalogo_ha_un_nome(lingua):
    from custom_components.omoda9.core.commands import COMMANDS

    esito = _esito(lingua)
    nomi = esito.get("commands", {})
    chiavi_comandi = [k for k, _ in COMMANDS]
    mancanti = sorted(k for k in chiavi_comandi if k not in nomi)
    assert not mancanti, f"{lingua}.json: comandi senza nome tradotto: {mancanti}"


@pytest.mark.parametrize("lingua", LANGS)
def test_ogni_codice_backend_ha_un_significato(lingua):
    from custom_components.omoda9.core.codes import CODE_MEANING

    esito = _esito(lingua)
    significati = esito.get("code_meanings", {})
    mancanti = sorted(c for c in CODE_MEANING if c not in significati)
    assert not mancanti, f"{lingua}.json: codici backend senza significato tradotto: {mancanti}"


@pytest.mark.parametrize("lingua", LANGS)
def test_ogni_modulo_reason_ha_un_nome(lingua):
    from custom_components.omoda9.coordinator import REASON_MODULI

    esito = _esito(lingua)
    moduli = esito.get("reason_modules", {})
    mancanti = sorted(m for m in REASON_MODULI if m not in moduli)
    assert not mancanti, f"{lingua}.json: moduli reason senza nome tradotto: {mancanti}"


def test_i_placeholder_sono_identici_nelle_tre_lingue():
    """Stessa garanzia che applicherebbe Home Assistant in produzione: un placeholder che
    esiste in una lingua e non in un'altra farebbe scartare la traduzione (o, qui,
    solleverebbe un KeyError catturato da `_traduci_esito`, che ricade sull'inglese —
    silenziosamente, per chi non legge i log)."""
    cataloghi = {lingua: _esito(lingua).get("messages", {}) for lingua in LANGS}
    tutte_le_chiavi = set()
    for cat in cataloghi.values():
        tutte_le_chiavi |= set(cat)

    disallineati = {}
    for chiave in sorted(tutte_le_chiavi):
        insiemi = {}
        for lingua in LANGS:
            modello = cataloghi[lingua].get(chiave)
            if modello is None:
                continue
            insiemi[lingua] = _placeholders(modello)
        valori = list(insiemi.values())
        if valori and any(v != valori[0] for v in valori):
            disallineati[chiave] = insiemi
    assert not disallineati, f"placeholder disallineati fra le lingue: {disallineati}"


# ───────────────────────── prova viva: un comando in polacco ─────────────────────────

def _coordinator(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


async def _avvia(hass, config_entry, monkeypatch):
    from custom_components.omoda9.coordinator import Omoda9Coordinator

    monkeypatch.setattr(Omoda9Coordinator, "_provision_certs",
                        lambda self: (True, "cert finti (test)"))
    monkeypatch.setattr(Omoda9Coordinator, "_connect_car", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_keepalive", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_telemetry_poll", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_drive_watch", lambda self: None)

    async def _niente_backfill(self) -> None:
        return None

    monkeypatch.setattr(Omoda9Coordinator, "async_ensure_vehicle_identity", _niente_backfill)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_un_comando_in_polacco(hass, config_entry, cloud, monkeypatch):
    """La prova che chiude Task C: con Home Assistant in polacco, l'esito di un comando
    riuscito arriva DAVVERO in polacco — non il ripiego inglese di `text_en`, non
    l'italiano di prima di questa release."""
    hass.config.language = "pl"

    await _avvia(hass, config_entry, monkeypatch)
    coord = _coordinator(hass, config_entry)

    cloud.on("/asc/vehicleControl/lockControl", code="A00079")
    await coord.async_send_command("blocca")
    await hass.async_block_till_done()

    esito = coord.data["cmd_status"]
    assert "Zablokuj drzwi" in esito, f"nome comando non tradotto in polacco: {esito!r}"
    assert "komenda zaakceptowana" in esito, f"significato codice non tradotto in polacco: {esito!r}"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_una_sveglia_in_polacco(hass, config_entry, cloud, monkeypatch):
    """Stessa prova sul canale sveglia (`wake_status`): `core/wake.py` produce anch'esso
    `Esito` strutturati, tradotti allo stesso modo.

    `_auto_e_sveglia` forzato a True: l'auto risulta già sveglia via MQTT, quindi
    `do_wake` chiude subito con `wake_already_awake` senza nemmeno tentare l'SMS — il
    percorso più corto, e quello che isola il canale sveglia dal fallback del coordinator
    (`_send_command("localizza")`), che ha un annuncio ancora non convertito (fuori dallo
    scopo di questa release, vedi PR)."""
    hass.config.language = "pl"
    await _avvia(hass, config_entry, monkeypatch)
    coord = _coordinator(hass, config_entry)
    monkeypatch.setattr(coord, "_auto_e_sveglia", lambda: True)

    await coord.async_wake()
    await hass.async_block_till_done()

    stato = coord.data["wake_status"]
    assert "obudzone" in stato.lower(), f"esito sveglia non tradotto in polacco: {stato!r}"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
