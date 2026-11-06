# Audit tecnico — Studio Lights 1.0.0

**Data:** 6 novembre 2026
**Ambiente di sviluppo:** Windows 11, Python 3.12.10, Tk 8.6
**Librerie verificate:** tinytuya **1.20.0**, customtkinter **6.0.0**, Pillow **13.0.0**
**Stato:** implementazione completa, test automatici e smoke test GUI superati.
**Hardware:** nessuna lampadina Tuya fisica disponibile durante lo sviluppo; vedi
"Rischi residui" e "Test sul campo".

---

## 1. Obiettivo e perimetro

Applicazione desktop per controllare in LAN lampadine Tuya / Smart Life, con:

- selezione multipla tramite checkbox;
- bianco (luminosità + temperatura), colore RGB, scene hardware;
- invio parallelo e atomico per luce;
- scene globali e snapshot multi-luce salvabili da GUI;
- gestione dispositivi e riallineamento IP;
- robustezza contro luci offline;
- persistenza locale e avvio rapido.

Sono esclusi dal perimetro: cloud Tuya a runtime, account utente, multi-utente,
sincronizzazione tra PC, scenari fuori dalla LAN, supporto a prese/termostati.

---

## 2. Requisiti → implementazione

| Requisito | Implementazione | Verifica |
|---|---|---|
| Python 3.12+, tinytuya, customtkinter | `requirements.txt`, `.venv` | import + avvio GUI |
| `ThreadPoolExecutor`, nessun blocco GUI | `controller.py`, `ui/app.py::submit` | comando simulato offline |
| Lettura `devices.json` del wizard | `config.py::import_devices_json` | test unitario lista + dict |
| `devices_template.json` se manca | `config.py::ensure_template` | test unitario |
| Inserimento/modifica manuale | `ui/dialogs.py::SettingsWindow`, `LightEditorDialog` | test GUI + screenshot |
| Scansione IP LAN | `controller.scan_lan`, `match_scan_ips` | test matching + scansione reale |
| Checkbox + seleziona tutte/nessuna | `LightRow`, `app.select_all/select_none` | test GUI |
| Switch ON/OFF per luce | `LightRow` → `app._on_light_power` | smoke test |
| Master accendi/spegni | `power_selected` | codice + GUI |
| Bianco 1–100% + temp 0–100% | `_build_white_tab`, `build_dps` | test payload |
| RGB picker + preset + slider | `ui/colorpicker.py`, `_build_colour_tab` | screenshot + test payload |
| Scene hardware Tuya | `set_scene`, tab `Scena HW` | revisione API + unit test indiretto |
| Scene globali | `Scene(type="global")` + `_store_scene` | test GUI/persistenza |
| Snapshot multi-luce | `Scene(type="snapshot")` + `lights` | test GUI + persistenza |
| Elimina / sovrascrivi scena | menu card + `delete_scene` / `overwrite_scene` | codice + dialogo conferma |
| Timeout 1.5 s, retry 1 | `LightController.__init__`, `_get_bulb` | ispezione + test offline (~1.5 s) |
| Barra stato / offline | `_finish_report`, `_update_online_chip` | smoke test con 3 luci offline |
| Scene demo 5–6 | `defaults.demo_scenes` (6) | test su seed |
| README / Audit / launcher | questo file, `README.md`, `run.bat`, `run.sh` | revisione |
| Versioning Git | repository con commit incrementali | log Git |

---

## 3. Architettura

```
main.py
  └─ ui/app.py  (Tk main thread)
       ├─ ui/widgets.py   LightRow / SceneCard
       ├─ ui/colorpicker.py
       ├─ ui/dialogs.py   Settings / editor / scene / conferme
       ├─ config.py       LightStore / SceneStore (JSON atomico)
       └─ controller.py   LightController
             ├─ ThreadPoolExecutor (32)
             ├─ una Lock per device
             └─ una socket persistente per BulbDevice
```

### Flusso di un comando

1. La GUI raccoglie le luci spuntate e costruisce un `LightState` (percentuali UI).
2. `app._bulk_apply` esegue il controller in un thread "ui-task"; la GUI resta reattiva.
3. `controller.apply_states` invia **un future per lampadina** al pool Tuya.
4. Ogni worker prende la lock della luce, converte lo stato in DPS grezzi e invia un
   unico payload con `set_multiple_values` (o `set_scene` per l'hardware).
5. I risultati tornano al thread Tk tramite polling di `Future.done()`: nessuna chiamata
   Tk da thread di lavoro.
6. La GUI aggiorna stato noto, health, barra di stato, latenza e salva su disco.

### Perché un payload grezzo

`tinytuya` 1.20 offre `set_white_percentage`, `set_colour`, `set_hsv`, ecc. Sono validi,
ma alcuni eseguono una lettura di stato/capability o mandano più comandi. Per garantire
"un comando per luce" e nessun effetto popcorn, il controller costruisce direttamente i
DPS dopo il rilevamento:

- `dpset` viene popolato dal primo `status()` e da `detect_bulb()`;
- se il firmware non espone abbastanza DP per il auto-detect, si applica un profilo
  fallback A/B basato sui DP osservati (`fallback_configure`);
- luminosità: percentuale → `value_min..value_max` (tipicamente 10–1000);
- bianco: DP `mode = "white"` + `brightness` + `colourtemp`;
- colore: DP `mode = "colour"` + `brightness` + colore nel formato `rgb8`/`hsv16`
  rilevato (`value_hexformat`);
- spegnimento: **solo** il DP switch, payload minimo.

Questa scelta è documentata nel codice (`build_dps`) ed è coperta da test.

### Rete e concorrenza

- `set_socketTimeout(1.5)` e `set_socketRetryLimit(1)` su ogni bulb;
- `set_socketPersistent(True)` per evitare handshake a ogni clic;
- lock per device: un solo comando alla volta sulla stessa socket;
- pool condiviso: luci diverse procedono in parallelo;
- su errore di rete/auth/protocollo la socket viene chiusa e ricreata al comando successivo;
- `shutdown()` chiude tutte le socket.

### Persistenza

- Scritture atomiche (`tempfile` + `os.replace`) con backup `.bak`.
- File corrotto → copia `.corrupt-<timestamp>` e ripristino dei default demo, senza crash.
- `lights_config.json` contiene l'ultimo stato noto per ogni luce, così la GUI riparte
  coerente e gli snapshot hanno un fallback sensato.
- `scenes.json` è indipendente dalle luci: le scene snapshot conservano gli ID e le luci
  mancanti vengono saltate al richiamo.

---

## 4. Decisioni e compromessi

| Decisione | Motivo | Compromesso |
|---|---|---|
| CustomTkinter | UI dark moderna, widget pronti | dipendenza in più; gestione titlebar Windows |
| Pillow per il color picker | rendering fluido della matrice SV e della barra hue | dipendenza in più (già richiesta da CTk) |
| Payload DPS grezzi | atomicità e latenza minima | dipende dal mapping DP del firmware |
| Socket persistenti | comandi in ~20–80 ms invece di handshake | sessioni 3.4/3.5 possono scadere; reconnect gestito |
| Un thread pool da 32 | scuole/studio con molte luci | picco di connessioni; configurabile in futuro |
| Scene demo con fallback | provare subito l'app senza hardware | comportamento speciale solo per `demo: true` |
| `demo` a livello root | evita di cancellare luci reali | editing manuale azzera il flag (scelta intenzionale) |
| Nessun polling continuo | zero traffico quando inattivo | lo stato può essere vecchio finché non premi Aggiorna |

---

## 5. Compatibilità tinytuya 1.20

Verifiche effettuate leggendo il sorgente installato e con test:

- `BulbDevice(dev_id, address, local_key, version=..., connection_timeout=...)`
- `set_socketTimeout`, `set_socketRetryLimit`, `set_socketPersistent`
- `status()` → `dps` + auto `detect_bulb()` (tipi A/B/C)
- `state()` → dict normalizzato (`switch`, `mode`, `brightness`, `colourtemp`, `colour`)
- `set_multiple_values(dict)` → invio atomico, con fallback interno per device che
  accettano un solo DP alla volta
- `set_scene(scene, scene_data=...)` → Type A `mode="scene_N"`, Type B prefisso indice
- `set_colour` / `rgb_to_hexvalue` / `hexvalue_to_rgb` per la codifica HSV
- `deviceScan(verbose=False, maxretry=2, color=False, poll=False)` per gli IP

Nota: in tinytuya 1.20 `set_white()` e `set_brightness()` usano **valori assoluti**, non
percentuali; le varianti `*_percentage()` esistono ma eseguono detection/stato extra.
Per questo il progetto converte esplicitamente le percentuali.

---

## 6. Problemi trovati e corretti durante lo sviluppo

1. **Dialoghi invisibili (CustomTkinter 6 / Windows).**
   `CTkToplevel.resizable(False, False)` nel costruttore, insieme a `withdraw()`, fa
   partire un timer di ridisegno della titlebar che può lasciare la finestra nascosta.
   *Fix:* niente `resizable()` prima del mapping; viene chiamato dentro `_present()`
   dopo `deiconify()`. Verificato con screenshot.

2. **Card scena vuote.**
   Il frame di accento aveva l'altezza di default 200 px e, con `rowspan`, spingeva le
   label fuori dalla card ad altezza fissa. *Fix:* accento alto 1 px, `rowspan=3`,
   rimossa l'altezza fissa; le card si adattano al contenuto.

3. **Testo della riga luce troncato.**
   IP + stato su una sola riga non entravano accanto allo switch. *Fix:* due righe
   (IP, stato) con font 9 e wrap.

4. **Spegnimento di una luce in scena hardware.**
   `set_scene()` accende sempre la lampadina: un master OFF con `hw_scene` valorizzato
   l'avrebbe riaccesa. *Fix:* se `power == False` si invia sempre il payload switch-off.

5. **Import automatico disatteso dalla config demo.**
   Con `lights_config.json` demo presente, `devices.json` non veniva letto al primo avvio.
   *Fix:* se la configurazione è ancora demo, `devices.json` viene importato
   automaticamente. Se l'utente ha già modificato/importato qualcosa, l'import resta
   manuale per non sovrascrivere IP e key.

6. **`test_connection` non usava il fallback capability.**
   Chiamata con un solo argomento mentre la funzione ne richiede due. Corretto e coperto
   dal percorso di test GUI.

7. **Footer del dialogo scena tagliato.**
   L'aggiunta dell'anteprima superava l'altezza. *Fix:* altezza 550 px e contenuto
   verificato con screenshot.

---

## 7. Verifiche eseguite

### Automatiche

```
python -m compileall studiolights main.py tests      → OK
python -m unittest discover -s tests -v               → 14 test, OK
ruff check . --exclude .venv                         → solo warning intenzionali
                                                        (except ampi, S110, RUF046)
```

I 14 test coprono: normalizzazione versioni, clamp/serializzazione stato, validazione
device, conversioni Kelvin, round-trip scene, import wizard (lista e dict), creazione
template, persistenza luci e scene, payload atomico colore/bianco/off, decodifica stato,
classificazione errori e matching IP della scansione.

### GUI

Smoke test reali su finestra Tk (1360×860), con screenshot verificati:

- layout principale, tab Bianco/Colore;
- selezione tramite checkbox e "seleziona tutte";
- apertura impostazioni, editor luce, dialogo scena;
- salvataggio snapshot (3 luci) e persistenza su `scenes.json`;
- comando verso 3 luci demo irraggiungibili: 3 errori `Device Unreachable` in parallelo,
  stato "✕ Colore applicato · …", burst disabilitato e poi riabilitato, health a `False`;
- chiusura pulita, nessuna eccezione Python nei callback.

### Non eseguite

- Comunicazione con lampadine Tuya fisiche (assenza hardware).
- Test su reti con VLAN / firewall restrittivi.
- Test di scene hardware su firmware reali (Type A e Type B).
- Test su macOS/Linux (la GUI è stata verificata solo su Windows).

---

## 8. Rischi residui

| Rischio | Impatto | Probabilità | Mitigazione |
|---|---|---|---|
| Mapping DP diverso da A/B standard | comandi errati o rifiutati | media | fallback su DP osservati, "Test connessione", log |
| Direzione temperatura invertita | caldo/freddo scambiati | media | documentato; toggle per-device in roadmap |
| Scena hardware non supportata | errore firmware | alta | messaggio chiaro, indice/payload modificabili |
| Socket persistente stale dopo sleep/router | primo comando fallito | media | retry manuale, drop socket e ricreazione |
| Local key in chiaro su disco | accesso locale alle luci | insita nel protocollo | `.gitignore`, avviso in UI/README |
| `deviceScan` bloccato da firewall | IP non aggiornati | media | inserimento manuale, log |
| Differenze CTk su altre versioni | errori layout | bassa | requirements con upper bound `<7`; test su 6.0 |
| Loop di eventi Tk su chiusura | warning "invalid command name" in console | bassa | innocui; `pythonw` non mostra console |

---

## 9. Sicurezza e privacy

- Nessuna chiamata cloud a runtime: solo TCP 6668 verso gli IP configurati.
- Il wizard `tinytuya` è l'unico momento in cui vengono usate credenziali cloud; è uno
  strumento esterno, non parte dell'app.
- Le Local Key sono salvate in chiaro in `lights_config.json` / `devices.json` (formato
  imposto dal protocollo locale Tuya). Consiglio: disco cifrato, permessi NTFS ristretti,
  repository privato e `.gitignore`.
- La configurazione demo inclusa non contiene segreti reali.
- Non c'è esecuzione di codice remoto, telemetria o auto-update.

---

## 10. Test sul campo consigliato

1. `python -m tinytuya wizard` e import in **Impostazioni**.
2. **Test connessione** su una luce: deve riportare protocollo, tipo (A/B/C) e numero DP.
3. Prova **Bianco** al 50% con temperatura 0 e 100: verifica la direzione del caldo.
4. Prova **Colore** con un preset e controlla che lo slider luminosità non spenga la luce.
5. Seleziona 3+ luci e applica un colore: verifica l'assenza di popcorn e la latenza
   riportata in basso.
6. Crea uno **Snapshot Studio** con colori diversi; cambia tutto; richiama e confronta.
7. Spegni una luce dall'interruttore a muro e invia un comando: l'app deve restare
   reattiva e segnalare offline entro ~1,5 s.
8. Cambia IP a una luce (o riavvia il router), poi **Scansiona IP LAN**.
9. Prova una **Scena HW** (indice 1–4); se il modello è Type B, prova un payload.
10. Riavvia l'app: lo stato noto e le scene devono essere coerenti.

---

## 11. Roadmap

- Toggle "inverti temperatura" per singola luce e calibrazione Kelvin per modello.
- Cache delle capability per device (evita il primo `status()` dopo ogni avvio).
- Editor visuale dello snapshot con preview dei colori per luce.
- Ordinamento/duplicazione scene e import/export.
- Watchdog opzionale per refresh periodico e riconnessione automatica.
- Packaging PyInstaller con icona e file di configurazione accanto all'eseguibile.
- Test con hardware reale e matrice modelli (A/B/C, 3.3/3.4/3.5).

---

## 12. Changelog

### 1.0.0 — 2026-11-06

- Prima release completa: GUI dark, controllo bianco/colore/HW, scene globali e snapshot,
  gestione dispositivi, scansione LAN, import wizard, persistenza atomica, test e docs.
- 14 test unitari; smoke test GUI; nessuna verifica su hardware fisico.
