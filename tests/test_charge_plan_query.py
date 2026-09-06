"""Lettura del piano di ricarica programmata dal cloud (`/asd/chargeAppointManage/chargeAppointQuery`).

Contesto: finora `chargeAppointPlans` arrivava SOLO come telemetria push (canale MQTT 5A02).
Se l'utente cambiava l'orario dall'auto o dall'app ufficiale, Home Assistant non lo scopriva
mai — restava sul proprio piano di default (issue #49, "Scheduled Charging moves to Off
although Scheduled Charging is enabled"). L'autore originale aveva già scritto la chiamata
giusta nel docstring di `Omoda9ScheduledChargeSwitch.extra_state_attributes` (switch.py) e
l'aveva deliberatamente NON fatta, perché è traffico in più verso il cloud del costruttore.

Questi test verificano le due metà di quella decisione, resa esplicita da CONF_READ_CHARGE_PLAN:
1. quando l'opzione è attiva (default), il piano letto dal cloud finisce in
   `fields["chargeAppointPlans"]`, lo stesso posto da cui `switch.py` già legge — quindi
   l'interruttore "Ricarica programmata" e i suoi attributi riflettono un piano cambiato
   dall'auto/app, non solo quello arrivato via MQTT;
2. quando l'opzione è disattivata, la richiesta in più verso il cloud non parte MAI.

Risposta reale (VIN mascherato) usata come fixture, letta dal vivo il 2026-09-06 su
un'Omoda 9 SHS, regione EU:

    POST /asd/chargeAppointManage/chargeAppointQuery {"vin": "...021519"}
    → {"code": "000000", "body": {"mainSwitch": 0, "chargeAppointPlans": [
          {"timeConsuming": 360, "cycleData": [1,2,3,4,5,6,7], "startTime": 480,
           "switchStatus": 0, "id": 307092757, ...}]}}
"""
from __future__ import annotations

import pytest

import fixtures as FX

# Piano come lo restituisce DAVVERO chargeAppointQuery: valori NUMERICI (non stringhe come
# nel push MQTT 5A02). switch.py gestisce già entrambe le forme (vedi `_live_on`).
PIANO_DAL_CLOUD = [{
    "timeConsuming": 360,
    "cycleData": [1, 2, 3, 4, 5, 6, 7],
    "startTime": 480,
    "switchStatus": 1,
    "id": 307092757,
    "chargeAppointMainId": 24402,
}]


# ───────────────────────── core/commands.py: query_charge_plan ─────────────────────────

def test_query_charge_plan_legge_il_piano(core, cloud, ctx):
    """La risposta reale del backend (mascherata) produce la lista `chargeAppointPlans`."""
    commands = core["commands"]
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"mainSwitch": 1,
                                                   "chargeAppointPlans": PIANO_DAL_CLOUD}})

    piano = commands.query_charge_plan(ctx)

    assert piano == PIANO_DAL_CLOUD
    chiamata = cloud.calls_to("/asd/chargeAppointManage/chargeAppointQuery")
    assert len(chiamata) == 1
    assert chiamata[0]["body"]["vin"] == FX.VIN


def test_query_charge_plan_e_read_only(core, cloud, ctx):
    """Nessun taskId, nessun PIN: è una query, non un comando (a differenza di
    ricarica_prog_on/off, che passano da CMD.send e dalla coda dei comandi)."""
    commands = core["commands"]
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_DAL_CLOUD}})

    commands.query_charge_plan(ctx)

    assert cloud.count("checkPassword") == 0, "una lettura non deve coniare un taskId"


@pytest.mark.parametrize("risposta", [
    {"code": "000000", "body": {}},                      # nessun piano impostato
    {"code": "000000", "body": {"chargeAppointPlans": None}},
    {"code": "A00000"},                                   # sessione scaduta: niente "body"
    "spazzatura non json",
])
def test_query_charge_plan_nessun_dato_ritorna_none(core, cloud, ctx, risposta):
    """Risposta assente/malformata ⇒ None, mai un'eccezione: il coordinator si limita a
    non aggiornare `fields` (fail open, come query_theft_switch)."""
    commands = core["commands"]
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery", response=risposta)

    assert commands.query_charge_plan(ctx) is None


def test_query_charge_plan_senza_login_ritorna_none(core, cloud, ctx, monkeypatch):
    """Login BFF fallito (sessione morta) ⇒ None, non un'eccezione che risalirebbe fino al
    poll e romperebbe il ciclo di aggiornamento."""
    commands = core["commands"]
    wake = core["wake"]
    monkeypatch.setattr(wake, "_bff_login", lambda _ctx: (None, None))

    assert commands.query_charge_plan(ctx) is None
    assert cloud.count("/asd/chargeAppointManage/chargeAppointQuery") == 0


# ───────────────────────── coordinator: scrittura in fields + opzione ─────────────────────────

def _coordinator(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


async def test_il_piano_letto_finisce_nei_fields_e_nello_switch(hass, integrazione_avviata,
                                                                cloud):
    """Il piano letto dal cloud finisce in `fields["chargeAppointPlans"]`: lo stesso campo da
    cui `switch.py` (Omoda9ScheduledChargeSwitch) già legge stato e attributi. Nessuna entità
    nuova — si aggiorna la fonte che quella esistente guarda."""
    coord = _coordinator(hass, integrazione_avviata)
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_DAL_CLOUD}})

    assert coord.read_charge_plan is True, "l'opzione è ON di default"
    await coord.async_read_charge_plan()
    await hass.async_block_till_done()

    assert coord.data["fields"]["chargeAppointPlans"] == PIANO_DAL_CLOUD

    switch = hass.states.get("switch.omoda9_ricarica_programmata")
    assert switch is not None, "l'interruttore ricarica programmata deve esistere"
    assert switch.state == "on"
    assert switch.attributes.get("orario_sull_auto") == "08:00"
    assert switch.attributes.get("durata_ore_sull_auto") == 6.0


async def test_nessun_piano_non_tocca_i_fields(hass, integrazione_avviata, cloud):
    """Risposta senza piano (es. sessione scaduta) ⇒ `fields` resta come prima: fail open,
    mai uno stato azzerato da una lettura che è semplicemente andata a vuoto."""
    coord = _coordinator(hass, integrazione_avviata)
    coord.data["fields"]["altro_campo"] = "invariato"
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery", response={"code": "A00000"})

    await coord.async_read_charge_plan()

    assert "chargeAppointPlans" not in coord.data["fields"]
    assert coord.data["fields"]["altro_campo"] == "invariato"


async def test_opzione_disattivata_non_chiama_mai_il_cloud(hass, integrazione_avviata, cloud):
    """Con CONF_READ_CHARGE_PLAN spento, `async_read_charge_plan` non deve produrre NEANCHE
    una richiesta verso il backend — è la garanzia che l'opzione dà a chi la spegne."""
    coord = _coordinator(hass, integrazione_avviata)
    coord.read_charge_plan = False
    # l'avvio dell'entry fa già una lettura (task in background): qui interessa solo ciò
    # che succede DOPO aver spento l'opzione, quindi si azzera il contatore.
    cloud.reset_calls()
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_DAL_CLOUD}})

    await coord.async_read_charge_plan()

    assert cloud.count("/asd/chargeAppointManage/chargeAppointQuery") == 0
    assert "chargeAppointPlans" not in coord.data["fields"]


async def test_fine_ciclo_di_poll_rilegge_il_piano(hass, integrazione_avviata, cloud,
                                                   monkeypatch):
    """`_do_poll_cycle` deve chiamare la lettura del piano a fine ciclo (auto online o
    offline: la query non dipende dal realtime appena letto)."""
    coord = _coordinator(hass, integrazione_avviata)

    async def _finto_ok(force: bool = False):
        return None

    monkeypatch.setattr(coord, "async_probe", _finto_ok)
    coord._online = True
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_DAL_CLOUD}})

    await coord._do_poll_cycle()
    await hass.async_block_till_done()

    assert coord.data["fields"]["chargeAppointPlans"] == PIANO_DAL_CLOUD


async def test_ricarica_prog_on_rilegge_il_piano_dopo_un_attimo(hass, integrazione_avviata,
                                                                monkeypatch):
    """Dopo l'invio di ricarica_prog_on/off si rilegge il piano con un breve ritardo (il
    backend impiega qualche secondo a riflettere il cambiamento appena inviato). Qui si
    azzera il ritardo per non rallentare il test: la logica sotto esame è "succede", non
    "quanto ci mette"."""
    import custom_components.omoda9.coordinator as coord_mod

    coord = _coordinator(hass, integrazione_avviata)
    monkeypatch.setattr(coord_mod, "CHARGE_PLAN_READ_DELAY_S", 0)
    monkeypatch.setattr(coord, "_send_command", lambda key, params=None: "inviato (test)")

    letture: list[str] = []

    async def _finta_lettura():
        letture.append("letto")

    monkeypatch.setattr(coord, "async_read_charge_plan", _finta_lettura)

    await coord.async_send_command("ricarica_prog_on", {"mainSwitch": 1})
    for _ in range(20):
        await hass.async_block_till_done()
        if letture:
            break
    assert letture == ["letto"], "ricarica_prog_on deve rileggere il piano dal cloud"


async def test_localizza_non_rilegge_il_piano(hass, integrazione_avviata, monkeypatch):
    """Un comando qualunque non deve far scattare la rilettura: solo ricarica_prog_on/off
    toccano il piano di ricarica."""
    import custom_components.omoda9.coordinator as coord_mod

    coord = _coordinator(hass, integrazione_avviata)
    monkeypatch.setattr(coord_mod, "CHARGE_PLAN_READ_DELAY_S", 0)
    monkeypatch.setattr(coord, "_send_command", lambda key, params=None: "inviato (test)")

    letture: list[str] = []

    async def _finta_lettura():
        letture.append("letto")

    monkeypatch.setattr(coord, "async_read_charge_plan", _finta_lettura)

    await coord.async_send_command("localizza")
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    assert letture == []
