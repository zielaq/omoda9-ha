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


# ───────────────────────── piano letto → entità time/number (2026-09-06) ─────────────────────────
# Bug reale: l'auto aveva un piano 22:10/6h, l'interruttore lo leggeva bene nei propri
# attributi, ma `time.omoda9_ricarica_orario_di_inizio` e `number.omoda9_ricarica_durata`
# restavano sul default 08:00/6h. Riaccendere l'interruttore da Home Assistant avrebbe
# rispedito quel default, cancellando il piano vero dell'utente con un solo tap.

PIANO_2210 = [{
    "timeConsuming": 360,
    "cycleData": [1, 2, 3, 4, 5, 6, 7],
    "startTime": 22 * 60 + 10,   # 22:10, in minuti da mezzanotte — come lo manda l'auto
    "switchStatus": 1,
    "id": 307092757,
}]

TIME_ENTITY = "time.omoda9_ricarica_orario_di_inizio"
NUMBER_ENTITY = "number.omoda9_ricarica_durata"


async def test_le_entita_time_number_seguono_il_piano_letto(hass, integrazione_avviata, cloud):
    """Dopo una lettura del piano dal cloud, l'orario e la durata mostrati nelle entità di
    configurazione corrispondono al piano REALE dell'auto, non al default."""
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_2210}})

    coord = _coordinator(hass, integrazione_avviata)
    await coord.async_read_charge_plan()
    await hass.async_block_till_done()

    assert hass.states.get(TIME_ENTITY).state == "22:10:00"
    assert float(hass.states.get(NUMBER_ENTITY).state) == 6.0
    # e il body che l'interruttore spedirebbe accendendosi ORA userebbe lo stesso orario:
    # è la garanzia che chiude il buco di sicurezza (riaccendere non deve più cancellare
    # il piano vero con il vecchio default).
    assert coord.charge_start_minutes == 22 * 60 + 10


async def test_piano_invariato_non_riscrive_le_entita(hass, integrazione_avviata, cloud,
                                                       monkeypatch):
    """A piano IDENTICO fra due letture, le entità non vengono toccate una seconda volta —
    altrimenti ogni poll (anche a piano invariato) sovrascriverebbe silenziosamente un
    valore che l'utente ha appena scelto ma non ancora inviato."""
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_2210}})

    coord = _coordinator(hass, integrazione_avviata)
    await coord.async_read_charge_plan()
    await hass.async_block_till_done()

    chiamate: list[int] = []
    entita_orario = coord._charge_time_entity
    originale = entita_orario.set_from_car

    def _spia(minuti):
        chiamate.append(minuti)
        return originale(minuti)

    monkeypatch.setattr(entita_orario, "set_from_car", _spia)

    # stessa identica risposta: la seconda lettura non deve richiamare set_from_car
    await coord.async_read_charge_plan()
    await hass.async_block_till_done()

    assert chiamate == [], "il piano non è cambiato: le entità non andavano riscritte"

    # ma se ora l'auto riporta DAVVERO un piano diverso, la sincronizzazione riparte
    piano_cambiato = [{**PIANO_2210[0], "startTime": 6 * 60}]  # 06:00
    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": piano_cambiato}})
    await coord.async_read_charge_plan()
    await hass.async_block_till_done()

    assert chiamate == [6 * 60]
    assert hass.states.get(TIME_ENTITY).state == "06:00:00"


async def test_utente_puo_ancora_impostare_a_mano(hass, integrazione_avviata, cloud):
    """L'utente può sempre impostare la propria ora a mano: non è bloccata dalla
    sincronizzazione col cloud, che tocca l'entità solo quando LEGGE un piano diverso."""
    await hass.services.async_call(
        "time", "set_value", {"entity_id": TIME_ENTITY, "time": "23:45:00"}, blocking=True)
    assert hass.states.get(TIME_ENTITY).state == "23:45:00"

    coord = _coordinator(hass, integrazione_avviata)
    assert coord.charge_start_minutes == 23 * 60 + 45


async def test_charge_plan_utc_sposta_lorario_come_la_visualizzazione(hass, integrazione_avviata,
                                                                      cloud):
    """CONF_CHARGE_PLAN_UTC deve spostare l'orario sincronizzato nelle entità nella STESSA
    direzione in cui sposta già `orario_sull_auto` (attributo dell'interruttore) — stesso
    calcolo, un punto solo (`Omoda9Coordinator.minuti_locali_piano`), niente logiche
    divergenti fra le due entità."""
    await hass.config.async_set_time_zone("Europe/Warsaw")   # UTC+1 (o +2 in ora legale)
    coord = _coordinator(hass, integrazione_avviata)
    coord.charge_plan_utc = True

    cloud.on("/asd/chargeAppointManage/chargeAppointQuery",
             response={"code": "000000", "body": {"chargeAppointPlans": PIANO_2210}})
    await coord.async_read_charge_plan()
    await hass.async_block_till_done()

    from homeassistant.util import dt as dt_util
    offset_min = int(dt_util.now().utcoffset().total_seconds() // 60)
    atteso = (PIANO_2210[0]["startTime"] + offset_min) % 1440

    stato_time = hass.states.get(TIME_ENTITY).state
    hh, mm, _ = stato_time.split(":")
    assert int(hh) * 60 + int(mm) == atteso

    # stesso spostamento, stessa direzione dell'attributo che l'interruttore mostra da sempre
    switch = hass.states.get("switch.omoda9_ricarica_programmata")
    attesa_hhmm = f"{atteso // 60:02d}:{atteso % 60:02d}"
    assert switch.attributes.get("orario_sull_auto") == attesa_hhmm
