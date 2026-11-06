# Audit tecnico — Studio Lights 1.1.0

**Data:** 6 novembre 2026
**Ambiente di sviluppo:** Windows 11, Python 3.12.10, Tk 8.6
**Librerie verificate:** tinytuya **1.20.0**, customtkinter **6.0.0**, Pillow **13.0.0**
**Stato:** implementazione completa, test automatici e smoke test GUI superati.
**Hardware:** test automatici e GUI senza lampadine; durante il collaudo reale l'utente ha
collegato tre lampadine A60 RGB+CW e importato le Local Key. Il comportamento del Flow
sul firmware reale (fluidità e fps sostenibili) resta da tarare.

---

## 1. Obiettivo e perimetro

Applicazione desktop per controllare in LAN lampadine Tuya / Smart Life, con:

- selezione multipla tramite checkbox;
- bianco (luminosità + temperatura), colore RGB, scene hardware;
- fade infinito **Flow** tra 8 colori, con velocità e sfasamento;
- invio parallelo e atomico per luce;
- scene globali, snapshot multi-luce e scene Flow salvabili da GUI;
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
| Flow 8 colori, fade infinito, 0.5–5 s | `flow.py`, `FlowRunner`, tab Flow | 2 test motore + test GUI start/stop |
| Scena Flow salvabile | `Scene(type="flow")` + `FlowConfig` | round-trip + GUI |
| Elimina / sovrascrivi scena | menu card + `delete_scene` / `overwrite_scene` | codice + dialogo conferma |
| Timeout 1.5 s, retry 1 | `LightController.__init__`, `_get_bulb` | ispezione + test offline (~1.5 s) |
| Barra stato / offline | `_finish_report`, `_update_online_chip` | smoke test con 3 luci offline |
| Scene demo 5–6 | `defaults.demo_scenes` (7, inclusa Flow) | test su seed |
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
       ├─ flow.py         FlowRunner (thread, un frame in volo per luce)
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

### Flow: fade generato lato host

Tuya non espone un comando "fade tra N secondi". Il Flow quindi:

- interpola la palette sul **monotonic clock** (non sul numero di frame), così la velocità
  resta corretta anche se un frame salta;
- usa HSV con percorso di hue più breve per colori saturi, RGB lineare per bianchi/grigi;
- invia solo i DP **colore + luminosità** per frame; switch e mode vengono impostati una
  volta dal comando iniziale atomico;
- mantiene **un solo frame in volo per lampadina**: se una luce è lenta/offline, le altre
  continuano e la luce lenta viene rimossa dal flow dopo un errore definitivo;
- aspetta l'ACK di ogni frame (`set_multiple_values`), evitando risposte non lette che
  desincronizzerebbero la socket persistente;
- applica uno **sfasamento** opzionale `i / n` alla posizione della palette, per avere
  colori diversi simultanei sulle luci dello studio;
- si ferma con l'evento di stop, con il pulsante nella barra di stato o quando si applica
  un comando manuale; l'ultima tinta viene mantenuta e salvata nello stato noto;
- è disponibile a 3/6/10/15 fps (default 10) e 0.5–5 s per transizione (default 2.5 s).

Il costo è traffico TCP proporzionale a `luci × fps`. Con 3 luci a 10 fps sono ~30
comandi/s, gestibili con socket persistenti; non è pensato per 20+ luci a 15 fps su Wi-Fi
affollato. Il limite è documentato in README e nella UI.

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
  mancanti vengono saltate al richiamo. Le scene Flow salvano palette, durata, fps,
  sfasamento e luminosità, non stati per singola luce.
- I file runtime (`lights_config.json`, `scenes.json`, `devices.json`, `tinytuya.json`,
  `tuya-raw.json`, `snapshot.json`) sono esclusi da Git perché possono contenere Local Key;
  nel repository restano solo `lights_config.example.json` e `scenes.example.json`.

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
| Flow software | palette e velocità libere, nessun limite firmware | traffico TCP e fluidità dipendenti dal modello |
| Un frame in volo per luce | una luce offline non blocca le altre | fps effettivi più bassi su firmware lento |
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

8. **File runtime con Local Key reali tracciati da Git.**
   Dopo il primo import reale `lights_config.json` conteneva le chiavi, mentre
   `tinytuya.json`/`tuya-raw.json`/`snapshot.json` erano non tracciati ma non ignorati.
   *Fix:* tutti i file runtime sono ora in `.gitignore`, rimossi dall'indice e sostituiti
   dai modelli sicuri `lights_config.example.json` / `scenes.example.json`. Verificato che
   la cronologia non contenga il Device ID reale.

9. **Dialogo della palette Flow.**
   Il wrapper del color picker è stato dimensionato e verificato con screenshot; il
   ridisegno titlebar di CTk è gestito dal fix già descritto al punto 1.

---

## 7. Verifiche eseguite

### Automatiche

```
python -m compileall studiolights main.py tests      → OK
python -m unittest discover -s tests -v               → 18 test, OK
ruff check . --exclude .venv --select F,E9            → OK
```

I 18 test coprono: normalizzazione versioni, clamp/serializzazione stato, validazione
device, conversioni Kelvin, round-trip scene global/snapshot/flow, FlowConfig e
interpolazione colori, import wizard (lista e dict), creazione template, persistenza luci
e scene, payload atomico colore/bianco/off, decodifica stato, classificazione errori,
matching IP e motore Flow (frame stream, stop, sfasamento).

### GUI

Smoke test reali su finestra Tk (1360×860), con screenshot verificati:

- layout principale, tab Bianco/Colore/Flow;
- selezione tramite checkbox e "seleziona tutte";
- apertura impostazioni, editor luce, dialogo scena e picker palette Flow;
- salvataggio snapshot (3 luci) e scena Flow con persistenza su `scenes.json`;
- comando verso 3 luci demo irraggiungibili: 3 errori `Device Unreachable` in parallelo,
  stato "✕ Colore applicato · …", burst disabilitato e poi riabilitato, health a `False`;
- Flow con controller fake: 18 frame in ~0.6 s, STOP visibile, 30 frame totali, stop
  immediato senza nuovi frame, colori finali diversi per sfasamento, nessun errore Tk;
- chiusura pulita, nessuna eccezione Python nei callback.

### Non eseguite

- Comunicazione con lampadine Tuya fisiche durante lo sviluppo iniziale. Dopo il linking
  dell'account reale l'utente ha importato le tre luci A60 e l'app è partita; la resa del
  Flow sul firmware reale resta da valutare e tarare.
- Test su reti con VLAN / firewall restrittivi.
- Test di scene hardware su firmware reali (Type A e Type B).
- Test su macOS/Linux (la GUI è stata verificata solo su Windows).
- Flow con 20+ luci o su Wi-Fi molto affollato.

---

## 8. Rischi residui

| Rischio | Impatto | Probabilità | Mitigazione |
|---|---|---|---|
| Mapping DP diverso da A/B standard | comandi errati o rifiutati | media | fallback su DP osservati, "Test connessione", log |
| Direzione temperatura invertita | caldo/freddo scambiati | media | documentato; toggle per-device in roadmap |
| Scena hardware non supportata | errore firmware | alta | messaggio chiaro, indice/payload modificabili |
| Firmware lento/throttling durante Flow | fade a scatti | media | fps 3/6/10/15, durata regolabile, un frame in volo |
| Wi-Fi debole (-85 dBm) | timeout e frame persi | media | avvicinare AP, abbassare fps, health/stop |
| Socket persistente stale dopo sleep/router | primo comando fallito | media | retry manuale, drop socket e ricreazione |
| Local key in chiaro su disco | accesso locale alle luci | insita nel protocollo | `.gitignore`, esempi sicuri, avviso in UI/README |
| `deviceScan` bloccato da firewall | IP non aggiornati | media | inserimento manuale, log |
| Differenze CTk su altre versioni | errori layout | bassa | requirements con upper bound `<7`; test su 6.0 |
| Loop di eventi Tk su chiusura | warning "invalid command name" in console | bassa | innocui; `pythonw` non mostra console |

---

## 9. Sicurezza e privacy

- Nessuna chiamata cloud a runtime: solo TCP 6668 verso gli IP configurati.
- Il wizard `tinytuya` è l'unico momento in cui vengono usate credenziali cloud; è uno
  strumento esterno, non parte dell'app.
- Le Local Key sono salvate in chiaro in `lights_config.json` / `devices.json` (formato
  imposto dal protocollo locale Tuya). Consiglio: disco cifrato e permessi NTFS ristretti.
- `.gitignore` esclude tutti i file runtime con segreti (`devices.json`,
  `lights_config.json`, `scenes.json`, `tinytuya.json`, `tuya-raw.json`, `snapshot.json`,
  log e backup). Il repository traccia solo `lights_config.example.json` e
  `scenes.example.json`, privi di dati reali. Verificato che la cronologia Git non
  contenga il Device ID reale importato durante il collaudo.
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
10. Apri **Flow**, seleziona 3 luci, 2.5 s e 10 fps: verifica la fluidità; se a scatti prova
    6 fps e 4 s. Controlla che **STOP FLOW** fermi tutto e che i comandi manuali fermino il flow.
11. Salva una scena Flow, richiamala e verifica palette/velocità.
12. Riavvia l'app: lo stato noto e le scene devono essere coerenti.

---

## 11. Roadmap

- Toggle "inverti temperatura" per singola luce e calibrazione Kelvin per modello.
- Cache delle capability per device (evita il primo `status()` dopo ogni avvio).
- Editor visuale dello snapshot con preview dei colori per luce.
- Flow con palette riordinabile via drag&drop e preview animata nella card scena.
- Sperimentare la modalità music/music-colour nativa per fade più fluidi su modelli compatibili.
- Ordinamento/duplicazione scene e import/export.
- Watchdog opzionale per refresh periodico e riconnessione automatica.
- Packaging PyInstaller con icona e file di configurazione accanto all'eseguibile.
- Test con hardware reale e matrice modelli (A/B/C, 3.3/3.4/3.5) e tuning fps.

---

## 12. Changelog

### 1.1.0 — 2026-11-06

- **Flow**: fade infinito tra 8 colori, 0.5–5 s per transizione, 3/6/10/15 fps, palette
  modificabile, preset, sfasamento tra luci, STOP globale e scene Flow salvabili.
- Fix di sicurezza: file runtime con Local Key rimossi dal tracking Git, esempi sicuri.
- 18 test unitari (incluso il motore Flow); smoke test GUI del Flow con controller fake.
- Screenshot aggiornati e documentazione Flow in README.

### 1.0.0 — 2026-11-06

- Prima release completa: GUI dark, controllo bianco/colore/HW, scene globali e snapshot,
  gestione dispositivi, scansione LAN, import wizard, persistenza atomica, test e docs.
- 14 test unitari; smoke test GUI; nessuna verifica su hardware fisico.
