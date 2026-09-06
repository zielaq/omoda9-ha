"""Base entity Omoda 9: aggancio al coordinator + device_info comune.

Continuità entity_id (FASE 3d): per non perdere storico recorder/dashboard al
cutover dal bridge, ogni entità FORZA il proprio `entity_id` invece di lasciarlo
derivare implicitamente. L'object_id di default = slugify(nome) — che riproduce
ESATTAMENTE gli id `omoda9_*` già generati dal bridge (has_entity_name=False →
HA slugifica il solo nome). Dove il bridge usa un id non derivabile dal nome
(es. i pulsanti comando = `omoda9_<key>`) si passa `object_id` esplicito.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DEFAULT_VEHICLE_NAME, DOMAIN, OPT_MAX_S
from .coordinator import Omoda9Coordinator


def _flt(v):
    """float() oppure None (non solleva mai)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def car_zone(hass, position: dict | None) -> str | None:
    """`"home"` / `"away"` / `None` (ignoto), con la semantica del DEVICE_TRACKER.

    Usa `async_active_zone`, cioe' la stessa funzione che mette il device_tracker dell'auto
    su `home`/`not_home`. `None` quando non c'e' un fix utilizzabile, cosi' chi chiama puo'
    astenersi invece di tirare a indovinare.

    ⚠️ **`async_active_zone` restituisce la zona piu' PICCOLA che contiene il punto**, non
    `zone.home`. Una zona non passiva disegnata dentro casa — un garage, un vialetto, cioe'
    esattamente il posto dove sta una wallbox — vince su `zone.home`, e questa funzione
    risponde `"away"` per un'auto che e' a casa. Misurato da @Caslinovich: con una
    `zone.garage` da 20 m sulle stesse coordinate, una ricarica domestica finiva nel
    contatore "fuori".

    Per una entita' di PRESENZA quel comportamento e' la convenzione di Home Assistant e
    resta. Per un CONTATORE DI ENERGIA e' sbagliato: la domanda li' non e' "in che zona
    sei" ma "sei dentro casa", e la risposta e' `in_zona_casa()`.
    """
    # import locale: nessuna dipendenza dal componente zone al momento dell'import del modulo
    from homeassistant.components.zone import async_active_zone

    pos = position or {}
    lat = _flt(pos.get("lat") or pos.get("latitude"))
    lon = _flt(pos.get("lon") or pos.get("longitude"))
    if lat is None or lon is None:
        return None
    zone = async_active_zone(hass, lat, lon)
    if zone is None:
        return "away"
    return "home" if zone.entity_id == "zone.home" else "away"


def in_zona_casa(hass, position: dict | None) -> bool | None:
    """L'auto e' DENTRO `zone.home`? `None` se non c'e' un fix utilizzabile.

    Domanda diversa da `car_zone()`, e va tenuta diversa. Quella chiede *in che zona sei* e
    risponde con la piu' piccola che ti contiene — corretto per una presenza, sbagliato per
    l'energia: chi carica nel proprio garage sta caricando a casa, qualunque zona piu'
    stretta ci sia disegnata sopra.

    Qui si chiede il CONTENIMENTO in `zone.home` e basta. Nessuna zona piu' piccola puo'
    cambiare la risposta, e nessuna zona che l'utente aggiunge domani puo' spostare in
    silenzio l'energia da un contatore all'altro.

    `None` se `zone.home` non esiste: senza il riferimento non si indovina, e i contatori si
    astengono invece di attribuire.
    """
    from homeassistant.components.zone import in_zone

    pos = position or {}
    lat = _flt(pos.get("lat") or pos.get("latitude"))
    lon = _flt(pos.get("lon") or pos.get("longitude"))
    if lat is None or lon is None:
        return None
    casa = hass.states.get("zone.home")
    if casa is None:
        return None
    return bool(in_zone(casa, lat, lon))


def field_on(v) -> bool | None:
    """Interpreta un campo 5A02 come acceso/aperto (True), spento/chiuso (False)
    o ASSENTE (None).

    `None` / `"None"` / `""` = campo assente → ritorna `None`, così a livello entità
    emerge il valore ripristinato (o `unknown`) invece di un falso `False`. Altrimenti
    vero se diverso da zero, con confronto NUMERICO quando possibile (`"0.0"` = spento,
    allineato fra binary_sensor/lock/switch/cover); fallback testuale per i booleani."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "None"):
        return None
    try:
        return float(s) != 0.0
    except (TypeError, ValueError):
        return s.lower() not in ("false", "off", "no")


class Omoda9Entity(CoordinatorEntity[Omoda9Coordinator]):
    """Entità base: device unico 'Omoda 9' identificato dal VIN."""

    # has_entity_name=True + translation_key → il NOME dell'entità è TRADOTTO (it/en) e HA lo
    # antepone al device → "Omoda 9 Battery" / "Jaecoo 7 Battery". L'entity_id resta lo stile
    # bridge "omoda9_*" (impostato esplicito sotto, da `name`/`object_id`) → storico intatto.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Omoda9Coordinator,
        name: str,
        unique_suffix: str,
        *,
        object_id: str | None = None,
        entity_id_format: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        # `name` NON è più il friendly name (lo dà translation_key): lo teniamo solo per
        # calcolare l'object_id dell'entity_id e per i log. NON impostare _attr_name, altrimenti
        # vincerebbe sul translation_key.
        self._raw_name = name
        self._attr_unique_id = f"{coordinator.vin}_{unique_suffix}"
        oid = object_id or slugify(name)          # es. "omoda9_batteria"
        # translation_key = object_id senza il prefisso dominio → chiave in translations/*.json
        self._attr_translation_key = oid[len(DOMAIN) + 1:] if oid.startswith(f"{DOMAIN}_") else oid
        # entity_id ESPLICITO = continuità col bridge (default = slugify(name)).
        if entity_id_format:
            self.entity_id = entity_id_format.format(oid)
        # device dinamico: il nome riflette il veicolo reale (Omoda 9, Jaecoo 7…), letto
        # dal coordinator (nickname/modello da queryList, o override manuale). Il device è
        # identificato dal VIN → rinominarlo NON tocca entity_id né storico.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
            name=coordinator.vehicle_name or DEFAULT_VEHICLE_NAME,
            manufacturer=coordinator.vehicle_brand or "Omoda",
            model=coordinator.vehicle_model or None,
        )


@dataclass
class Omoda9ConfirmedRestoreData(ExtraStoredData):
    """Accompagna lo stato salvato di un attuatore ottimistico: dice se quel valore, nel
    momento in cui è stato scritto su disco, era CONFERMATO dalla telemetria (o da una
    lettura equivalente della verità sull'auto — es. `querySwitch` per l'antifurto) oppure
    era ancora solo l'intenzione dell'utente, mai arrivata all'auto o mai confermata da
    essa.

    Nato da un incidente reale (2026-09-06, istanza dell'utente): premuto "Raffredda
    tutto" alle 18:42:54, Home Assistant riavviato alle 18:43:27 — 33 secondi dopo, mentre
    l'interruttore stava ancora aspettando che l'auto si svegliasse (`MACRO_WAKE_WAIT`),
    quindi il comando vero non era MAI partito. Al riavvio (18:44:58) `RestoreEntity` ha
    rimesso l'interruttore su ON, e ci è rimasto 3 minuti e mezzo, finché la telemetria non
    l'ha smentito. Senza questo flag, `RestoreEntity` non ha modo di sapere se il valore che
    sta salvando è un fatto o solo una speranza — vedi `Omoda9OptimisticMixin._is_confirmed`."""

    confirmed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"confirmed": self.confirmed}


class Omoda9OptimisticMixin:
    """Stato ottimistico per gli attuatori (lock/switch/cover).

    Un comando ATTUA subito sull'auto, ma lo stato reale torna SOLO via MQTT a
    auto sveglia: l'ultimo valore "live" può restare fermo per ore. Dopo un'azione
    mostriamo immediatamente lo stato target (ottimistico) e lo teniamo finché non
    arriva la verità sul CAMPO di questa entità.
    Da usare come PRIMA classe base (precede Omoda9Entity nell'MRO).

    ⚠️ **Il campo, non un messaggio qualsiasi.** L'ottimismo si annullava al primo
    aggiornamento che facesse avanzare `last_seen`, cioè a QUALUNQUE messaggio dell'auto.
    Ma molti messaggi non portano un solo campo di stato: le conferme dei comandi sedile
    (`110F`) e i push di posizione (`1301`) contengono soltanto `result`/`seq`/`hasAsy`,
    che sono meta e vengono scartati. Effetto misurato: si accendeva il sedile ventilato,
    ~10 secondi dopo arrivava la conferma del comando stesso — vuota di stato — e
    l'interruttore tornava OFF, perché `fields` conserva ancora il valore PRECEDENTE al
    comando. L'entità mostrava il contrario di ciò che aveva appena fatto, e se l'auto si
    riaddormentava senza ripubblicare quel campo ci restava.
    La domanda giusta è «è arrivato un valore nuovo per il MIO campo?», e la risposta sta
    in `data["msg_fields"]` — i soli campi del messaggio appena arrivato.

    ⚠️ **E un tetto temporale, senza il quale si scambia un difetto con uno peggiore.**
    Se il proprio campo non arrivasse mai più — auto che si riaddormenta, preset riuscito a
    metà, campo che quel modello non pubblica — l'entità resterebbe sul valore comandato
    **per sempre**, e in silenzio: una bugia senza scadenza è più difficile da diagnosticare
    di una che torna sull'ultimo valore misurato. Il tetto è `OPT_MAX_S`.

    ⚠️ Resta scoperto un caso, ed è di proposito: un messaggio che porta il mio campo ma
    che l'auto ha pubblicato PRIMA di eseguire il comando (un 5A02 già in volo) annulla
    l'ottimismo con il valore vecchio. Chiuderlo richiede di correlare la conferma col
    `seq` del comando spedito, che oggi non è dimostrato che l'auto rimandi indietro. Fino
    ad allora questa resta comunque una finestra molto più stretta di «qualunque
    messaggio»."""

    _opt_value = None
    _opt_anchor = None
    _opt_at: float | None = None
    # Campi di telemetria che questa entità legge come stato reale. Vuoto = l'entità non ha
    # uno stato reale da attendere (ricarica, antifurto): lì l'ottimismo lo chiude solo il
    # tetto temporale. Va valorizzato da chi eredita il mixin.
    _opt_keys: tuple[str, ...] = ()

    def _set_optimistic(self, value) -> None:
        self._opt_value = value
        self._opt_anchor = self.coordinator.data.get("last_seen")
        self._opt_at = time.monotonic()
        self.async_write_ha_state()

    def _clear_optimistic(self) -> None:
        self._opt_value = None
        self._opt_anchor = None
        self._opt_at = None

    async def _run_command(self, key: str, target, params: dict | None = None) -> None:
        """Attua un comando mostrando subito lo stato target (ottimistico).

        `params` = override parametrico del body (clima: temperatura/durata; ricarica
        programmata: piano). Su eccezione del comando (rete/auth/backend) ANNULLA
        l'ottimismo — così la card torna allo stato reale invece di restare bloccata
        su un target mai attuato — e propaga un errore leggibile (toast in UI).

        [coda] L'auto esegue UN comando alla volta: un secondo comando (o un doppio-tap) non
        viene rifiutato ma ASPETTA il suo turno nella coda del coordinator, che lo invia appena
        l'auto ha confermato il precedente."""
        self._set_optimistic(target)
        # La bandiera + `finally` copre anche la CANCELLAZIONE del task (`CancelledError`
        # deriva da `BaseException` e non passa da `except Exception`): senza, un'automazione
        # in `mode: restart` che si ri-attivi mentre il comando è in volo lasciava l'entità
        # appesa allo stato ottimistico, cioè a mostrare un'azione che nessuno può più
        # confermare. Stesso motivo per cui il lucchetto della coda si rilascia in `finally`.
        inviato = False
        try:
            await self.coordinator.async_send_command(key, params)
            inviato = True
        except Exception as err:  # noqa: BLE001 — qualunque fallimento del comando
            # [Task C] `translation_key`: il meccanismo NATIVO di Home Assistant per
            # tradurre il messaggio di un'eccezione (frontend e servizi lo risolvono da
            # `exceptions.command_failed.message` in translations/*.json). `str(err)`
            # resta in inglese (o non tradotto, per ciò che questa release non ha ancora
            # convertito): è un dettaglio tecnico incorporato come placeholder, non il
            # testo da tradurre.
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed",
                translation_placeholders={"command": key, "error": str(err)},
            ) from err
        finally:
            if not inviato:
                self._clear_optimistic()
                self.async_write_ha_state()

    def _verita_arrivata(self) -> bool:
        """Vero se il messaggio appena arrivato porta un valore per il MIO campo.

        Si guarda `msg_fields` (solo questo messaggio) e non `fields`, che è cumulativo:
        lì il campo c'è sempre, anche se l'ultima volta che l'auto l'ha detto era ieri."""
        if not self._opt_keys:
            return False
        if self.coordinator.data.get("last_seen") == self._opt_anchor:
            return False                    # nessun messaggio nuovo da quando ho comandato
        msg = self.coordinator.data.get("msg_fields") or {}
        return any(k in msg for k in self._opt_keys)

    def _ottimismo_scaduto(self) -> bool:
        """Vero se l'ottimismo dura da troppo: la verità non è mai arrivata."""
        return self._opt_at is not None and (time.monotonic() - self._opt_at) > OPT_MAX_S

    def _handle_coordinator_update(self) -> None:
        if self._opt_value is not None and (self._verita_arrivata() or self._ottimismo_scaduto()):
            self._clear_optimistic()
        super()._handle_coordinator_update()

    # ───────────────── Task A/B: stato confermato vs. solo ottimismo ─────────────────
    # Un valore "confermato" è appoggiato alla telemetria (o a una lettura equivalente
    # della verità sull'auto, come querySwitch per l'antifurto), non al solo ottimismo
    # dell'utente. Serve a due cose: (A) decidere cosa sopravvive a un riavvio di Home
    # Assistant (vedi `extra_restore_state_data`/`_restore_confirmed_value`), e (B)
    # `assumed_state`, che dice onestamente all'interfaccia "non so come sta messa
    # davvero l'auto" finché la telemetria non parla.

    def _live_confirm(self) -> bool | None:
        """Il valore "live" di QUESTA entità, se ne ha uno (telemetria/lettura reale).

        Default: nessuno (entità come Omoda9ChargeSwitch, che non ha alcun campo di stato
        e vive SOLO di ottimismo + ripristino — quindi non può mai essere "confermata").
        Le sottoclassi con un campo reale la sovrascrivono per restituirlo (es. `_live_on`,
        `_live_locked`, `_live_closed`, `_real`)."""
        return None

    def _is_confirmed(self) -> bool:
        """Vero se il valore che `is_on`/`is_locked`/`is_closed` riporterebbe ORA viene
        dalla telemetria, non dall'ottimismo in corso. Un ottimismo ancora attivo non è
        MAI confermato per definizione, anche se il campo live esiste: è proprio il
        periodo in cui non sappiamo ancora se l'auto ha eseguito.

        `Omoda9ClimaMacroSwitch` sovrascrive questo metodo (non `_live_confirm`): il suo
        stato non ha MAI un campo live diretto — solo una correzione a senso unico dalla
        telemetria — quindi tiene un proprio flag `_confirmed` invece di ricalcolarlo qui."""
        if self._opt_value is not None:
            return False
        return self._live_confirm() is not None

    @property
    def assumed_state(self) -> bool:
        """Task B: quando il valore mostrato non è confermato (ottimismo in corso, o un
        ripristino che Task A ha lasciato sconosciuto), lo si dice onestamente. Home
        Assistant disegna allora due pulsanti separati invece di un interruttore unico —
        il modo nativo di HA di dire "non so come sta messa davvero l'auto" — e torna al
        controllo normale non appena la telemetria conferma."""
        return not self._is_confirmed()

    @property
    def extra_restore_state_data(self) -> Omoda9ConfirmedRestoreData:
        """Task A: il valore che RestoreEntity scrive su disco porta con sé se ERA
        confermato in quel momento. Senza questo, un riavvio durante un ottimismo mai
        confermato (l'incidente del 2026-09-06: comando mai partito verso l'auto) restituiva
        "acceso" per un'azione che l'auto non aveva mai visto — vedi `Omoda9ConfirmedRestoreData`."""
        return Omoda9ConfirmedRestoreData(confirmed=self._is_confirmed())

    async def _restore_confirmed_value(self, value: bool) -> bool | None:
        """`value` è lo stato salvato, già tradotto in bool dal chiamante (il significato di
        "on"/"locked"/"closed" cambia da piattaforma a piattaforma). Ritorna quel valore
        SOLO se era confermato al momento del salvataggio; altrimenti None (sconosciuto:
        `is_on` eccetera cadranno su `_restored is None` → stato "unknown" in HA, mai un
        "acceso" inventato).

        Nessun dato extra salvato (entità mai aggiornata a questa versione, o prima
        installazione) → tratta come NON confermato: fail-safe nella direzione sicura, non
        un errore — non sapere se un valore vecchio era confermato non deve valere come
        "sì"."""
        try:
            extra = await self.async_get_last_extra_data()
        except Exception:  # noqa: BLE001 — un dato extra illeggibile non deve rompere l'avvio
            return None
        if extra is None:
            return None
        try:
            confermato = bool(extra.as_dict().get("confirmed"))
        except Exception:  # noqa: BLE001
            confermato = False
        return value if confermato else None
