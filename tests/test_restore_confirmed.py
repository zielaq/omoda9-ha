"""Task A/B (2026-09-06): non ripristinare uno stato mai confermato dall'auto.

Incidente reale sull'istanza dell'utente: 18:42:54 premuto "Raffredda tutto" →
interruttore ottimistico ON, budget di sveglia 35 s. 18:43:27 Home Assistant riavviato
(33 s dopo, quindi il comando vero non era MAI partito verso l'auto). 18:44:58, al
riavvio, `RestoreEntity` ha ripristinato l'interruttore su ON — un'azione che l'auto non
aveva mai visto — e ci è rimasto 3 minuti e mezzo, finché la telemetria non l'ha smentito.

Questi test verificano le due metà della correzione (`entity.py`,
`Omoda9OptimisticMixin`/`Omoda9ConfirmedRestoreData`):

* Task A — un valore ottimistico MAI confermato dalla telemetria non sopravvive al
  riavvio: torna "unknown", non l'ultimo valore mostrato.
* Task B — finché un valore non è confermato dalla telemetria (ottimismo in corso, o un
  ripristino rimasto sconosciuto), `assumed_state` è True: Home Assistant lo dice
  onestamente in interfaccia invece di un interruttore che sembra sapere tutto.
"""
from __future__ import annotations

from datetime import timedelta

import fixtures as FX
from homeassistant.core import State
from homeassistant.util import dt as dt_util


def _coordinator(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


async def _avvia(hass, config_entry, monkeypatch):
    """Stesso avvio "leggero" di test_macro_comfort.py: certificati/MQTT/timer/backfill
    neutralizzati, nessun poll che sveglierebbe l'auto durante il test."""
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


# ───────────────────────── Task A: nessuna conferma ⇒ nessun ripristino ─────────────────────────

async def test_interruttore_comfort_ottimistico_torna_sconosciuto(hass, config_entry, cloud,
                                                                  monkeypatch):
    """Un comfort switch (es. riscaldamento volante) il cui ultimo stato salvato NON era
    confermato dalla telemetria deve tornare "unknown" dopo il riavvio, mai "on"."""
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    ent = "switch.omoda9_riscaldamento_volante"
    mock_restore_cache(hass, (State(ent, "on"),))   # nessun extra_data: come una versione vecchia

    await _avvia(hass, config_entry, monkeypatch)

    stato = hass.states.get(ent)
    assert stato.state == "unknown", (
        "un ottimismo mai confermato dalla telemetria non deve sopravvivere al riavvio "
        f"come 'on' (stato={stato.state!r})"
    )

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_interruttore_comfort_confermato_si_ripristina(hass, config_entry, cloud,
                                                             monkeypatch):
    """Lo stesso interruttore, ma con extra_data {"confirmed": True} (l'ultimo valore visto
    PRIMA dello spegnimento veniva dalla telemetria): il comportamento di prima resta —
    si ripristina come sempre."""
    from pytest_homeassistant_custom_component.common import mock_restore_cache_with_extra_data

    ent = "switch.omoda9_riscaldamento_volante"
    mock_restore_cache_with_extra_data(hass, ((State(ent, "on"), {"confirmed": True}),))

    await _avvia(hass, config_entry, monkeypatch)

    assert hass.states.get(ent).state == "on"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_serratura_ottimistica_torna_sconosciuta(hass, config_entry, cloud, monkeypatch):
    """Stesso principio per il lock: un blocco/sblocco mai confermato non deve
    ripresentarsi come "locked"/"unlocked" certi dopo un riavvio."""
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    ent = "lock.omoda9_serratura"
    mock_restore_cache(hass, (State(ent, "locked"),))

    await _avvia(hass, config_entry, monkeypatch)

    assert hass.states.get(ent).state == "unknown"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_cover_ottimistica_torna_sconosciuta(hass, config_entry, cloud, monkeypatch):
    """Stesso principio per una cover (baule): "closed" mai confermato ⇒ sconosciuto."""
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    ent = "cover.omoda9_baule"
    mock_restore_cache(hass, (State(ent, "closed"),))

    await _avvia(hass, config_entry, monkeypatch)

    assert hass.states.get(ent).state == "unknown"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_ricarica_immediata_non_ha_mai_conferma(hass, config_entry, cloud, monkeypatch):
    """`Omoda9ChargeSwitch` (ricarica immediata) non ha ALCUN campo di telemetria: il suo
    stato non è mai "confermabile", quindi anche un vecchio extra_data {"confirmed": True}
    non lo salverebbe (nessuna sottoclasse dichiara `_live_confirm` per lei) — qui si
    verifica il caso comune, senza extra_data, che deve comunque tornare sconosciuto."""
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    ent = "switch.omoda9_ricarica"
    mock_restore_cache(hass, (State(ent, "on"),))

    await _avvia(hass, config_entry, monkeypatch)

    assert hass.states.get(ent).state == "unknown"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_piano_ricarica_programmata_ottimistico_torna_sconosciuto(hass, config_entry,
                                                                        cloud, monkeypatch):
    """Anche l'interruttore del piano di ricarica programmata (che HA uno stato reale via
    `chargeAppointPlans`) non deve ripristinare un "on" mai confermato."""
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    ent = "switch.omoda9_ricarica_programmata"
    mock_restore_cache(hass, (State(ent, "on"),))

    await _avvia(hass, config_entry, monkeypatch)

    assert hass.states.get(ent).state == "unknown"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


# ───────────────────────── Task B: assumed_state ─────────────────────────

async def test_ottimismo_in_volo_e_assumed_state(hass, integrazione_avviata, monkeypatch):
    """Appena l'ottimismo scatta (comando appena premuto, auto non ancora confermata),
    l'entità deve dichiararsi `assumed_state`: HA la disegna diversamente, dicendo
    onestamente che non sa ancora com'è messa davvero l'auto."""
    ent_id = "switch.omoda9_riscaldamento_volante"

    await hass.services.async_call("switch", "turn_on", {"entity_id": ent_id}, blocking=True)

    stato = hass.states.get(ent_id)
    assert stato.state == "on"
    assert stato.attributes.get("assumed_state") is True, (
        "un valore ottimistico non ancora confermato dalla telemetria deve essere "
        "assumed_state=True"
    )


async def test_telemetria_toglie_assumed_state(hass, integrazione_avviata, monkeypatch):
    """Non appena la telemetria conferma il campo, `assumed_state` torna False: il valore
    non è più una supposizione."""
    from custom_components.omoda9.const import DOMAIN

    ent_id = "switch.omoda9_riscaldamento_volante"
    coord = _coordinator(hass, integrazione_avviata)

    await hass.services.async_call("switch", "turn_on", {"entity_id": ent_id}, blocking=True)
    assert hass.states.get(ent_id).attributes.get("assumed_state") is True

    coord._on_car_message(None, None, _Msg(FX.telemetry_5a02(steerWheelHeating="1")))
    await hass.async_block_till_done()

    stato = hass.states.get(ent_id)
    assert stato.state == "on"
    assert stato.attributes.get("assumed_state") is not True, (
        "una volta che la telemetria conferma il campo, l'entità non è più 'assunta'"
    )


class _Msg:
    """Il minimo che `_on_car_message` si aspetta da un messaggio paho (vedi test_telemetry.py)."""

    def __init__(self, payload: dict) -> None:
        import json
        self.payload = json.dumps(payload).encode()
        self.topic = "app/1/test/account/msgCenter/msg"
