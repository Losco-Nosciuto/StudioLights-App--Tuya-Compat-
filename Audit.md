# Audit tecnico — Studio Lights 1.3.3

**Data:** 7 novembre 2026
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
- **Screen Sync** reattivo al monitor, con zone e punti di campionamento;
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
| Screen Sync: sensori 16:9, fps, colore | `screen_sync.py`, `ui/screen_sync.py` | 20 test unitari + GUI live |
| Cattura monitor con mss | `ScreenCapture`, `list_monitors` | cattura reale desktop, 42 frame |
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
       ├─ screen_sync.py  ScreenCapture / ScreenAnalyzer / ScreenSyncRunner
       ├─ ui/screen_sync.py finestra configurazione Screen Sync
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
- è disponibile a 3/6/10/15/30 fps (default 10) e 0.5–5 s per transizione (default 2.5 s).

Il costo è traffico TCP proporzionale a `luci × fps`. Con 3 luci a 10 fps sono ~30
comandi/s, gestibili con socket persistenti; non è pensato per 20+ luci a 15 fps su Wi-Fi
affollato. Il limite è documentato in README e nella UI.

### Screen Sync: cattura, zone e smoothing

Screen Sync è separato dal Flow palette ma riusa `submit_colour_frame`:

- **Cattura**: `mss` cattura solo il monitor scelto; `PIL` crea il frame RGB e lo riduce
  a 96×54. Una sola cattura intera per frame: le zone sono crop nell'analisi, non grab
  separati. Misurato su 2560×1440: frame intero ~28 ms, 4 patch 320×180 ~41 ms, quindi
  dividere la cattura in più grab peggiora la latenza.
- **Sensori**: 1–8 rettangoli normalizzati (0..1) sull'anteprima 16:9, trascinabili e
  ridimensionabili; in alternativa 3/5/7 fasce automatiche. Le zone libere scelgono
  *cosa* campionare (ed escludere HUD), non accelerano `mss`.
- **Campionamento**: 1/4/9 punti per zona (griglia 1×1, 2×2, 3×3).
- **Maschere**: con le fasce automatiche si rileva il letterbox sulle righe nere e si
  taglia l'HUD superiore 12% / inferiore 15% (opzionale). Con i sensori liberi la
  maschera è la zona scelta dall'utente.
- **Colore**: media RGB per zona → HSV; la saturazione usa una curva morbida
  (`s ** 0.85 * moltiplicatore`) che rinforza soprattutto i toni chiari/pastello.
  Il valore viene normalizzato a 1 e la luminosità del bulbo è pilotata dalla luminanza.
- **Bianco dedicato**: se la saturazione è sotto la soglia (default 0.08) il target
  non viene inviato in RGB — dove una traccia di blu diventa un cast bluastro — ma in
  `mode="white"` con temperatura calda/fredda dedotta dalla tinta. Il bianco usa così
  i LED bianchi dedicati del bulbo.
- **Luminosità**: curva percettiva con toe sul nero. Lo slider **Curva buio**
  (0.6–1.8) controlla l’ampiezza del toe (`0.01–0.10`), non un gamma globale: gli scuri
  diventano cupi senza spegnere anche i toni medi/bassi. `Luminosità minima` resta il
  pavimento effettivo.
- **Testo chiaro su sfondo scuro**: oltre alla media si calcola la luminanza mediana del
  frame (a risoluzione piena). La correzione `median / mean` (clamp 0.4–1.0) si applica
  **solo se mediana < 0.22 e mediana/media < 0.45**, cioè quando il testo/HUD gonfia la
  media. Una scena cinematografica scura ma uniforme mantiene la luminosità.
- **Anteprima**: mostra il campione RGB grezzo (ciò che vede il sensore) e l’etichetta
  `raw → output`, es. `Z2 · 28% → 14%` o `Z1 · 16% → OFF`. La riga di stato mostra
  media/mediana, saturazione e fattore di correzione buio.
- **Nero = spento**: sotto `dark_off_threshold` (default 5%) o su frame nero il runner
  invia lo switch-off reale (`power=False`) invece di un 1–2% che molte lampadine
  rendono comunque luminoso. Isteresi: riaccensione sopra soglia+2. Lo stato off viene
  riportato alla UI allo stop.
- **Smoothing**: EMA con `alpha = 1 - exp(-dt / tau)`; `tau` 0.1–3 s.
- **Frame rate**: richiesta 5–60 fps, ma il loop attende il completamento della cattura;
  `effective_fps` misura il rate reale e la UI lo mostra. Con `mss` a 1440p il tetto è
  ~30 fps; 60 fps richiederebbero DXGI/WGC.
- **Turbo music**: opzione sperimentale che entra in music mode e invia DP28
  `control_data` con `nowait=True`, senza ACK per frame; al primo errore
  protocollo/unsupported la luce torna automaticamente a `submit_colour_frame`.
- **Mapping**: ogni luce è associata a un sensore o a “Globale”; il runner invia i frame
  con lo stesso payload completo delle scene statiche (switch → brightness → colour →
  mode), un frame in volo per luce.
- **Stop**: il pulsante nella barra di stato e la chiusura della finestra fermano il
  runner; i comandi manuali e il Flow fermano Screen Sync. Il pallino health viene
  aggiornato se una luce cade durante il sync.

Limiti: `mss` usa GDI; fullscreen exclusive può dare frame neri, HDR non è tone-mappato,
DRM non è supportato. La cattura è locale e i frame non vengono salvati.

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
- `screen_sync.json` salva monitor, modalità, sensori, punti, smoothing, saturazione,
  limiti di luminosità, fps, turbo, preset e mappa luci → zone. È un file runtime
  ignorato da Git; esempio in `screen_sync.example.json`.
- I file runtime (`lights_config.json`, `scenes.json`, `screen_sync.json`, `devices.json`,
  `tinytuya.json`, `tuya-raw.json`, `snapshot.json`) sono esclusi da Git perché possono
  contenere Local Key; nel repository restano solo i modelli `*.example.json`.

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
| Screen Sync software | reagisce a colori/luminanza reali senza AI | dipende da mss/borderless/HDR; non è semanticamente “pioggia” |
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
python -m unittest discover -s tests -v               → 41 test, OK
ruff check . --exclude .venv --select F,E9            → OK
```

I 41 test coprono: normalizzazione versioni, clamp/serializzazione stato, validazione
device, conversioni Kelvin, round-trip scene global/snapshot/flow, FlowConfig e
interpolazione colori, import wizard (lista e dict), creazione template, persistenza luci
e scene, payload atomico colore/bianco/off, decodifica stato, classificazione errori,
matching IP, motore Flow e Screen Sync (config, profilo default, preset store, sensori
liberi, fasce, HUD/letterbox, smoothing, bianco dedicato, saturazione, curva buio, testo
su sfondo scuro, scene luminose con bordi scuri, spegnimento su nero e riaccensione,
runner con capture finta, turbo con fallback).

### GUI

Smoke test reali su finestra Tk (1360×860), con screenshot verificati:

- layout principale, tab Bianco/Colore/Flow e header Screen Sync;
- selezione tramite checkbox e "seleziona tutte";
- apertura impostazioni, editor luce, dialogo scena, picker palette Flow e finestra Screen Sync;
- salvataggio snapshot (3 luci) e scena Flow con persistenza su `scenes.json`;
- comando verso 3 luci demo irraggiungibili: 3 errori `Device Unreachable` in parallelo,
  stato "✕ Colore applicato · …", burst disabilitato e poi riabilitato, health a `False`;
- Flow con controller fake: 18 frame in ~0.6 s, STOP visibile, 30 frame totali, stop
  immediato senza nuovi frame, colori finali diversi per sfasamento, nessun errore Tk;
- Screen Sync con cattura reale del desktop e controller fake: 42 frame in ~1.8 s,
  preview zone, STOP SYNC visibile, stati finali aggiornati, nessun errore Tk;
- chiusura pulita, nessuna eccezione Python nei callback.

### Non eseguite

- Comunicazione con lampadine Tuya fisiche durante lo sviluppo iniziale. Dopo il linking
  dell'account reale l'utente ha importato le tre luci A60 e l'app è partita; la resa del
  Flow sul firmware reale resta da valutare e tarare.
- Test su reti con VLAN / firewall restrittivi.
- Test di scene hardware su firmware reali (Type A e Type B).
- Test su macOS/Linux (la GUI è stata verificata solo su Windows).
- Flow con 20+ luci o su Wi-Fi molto affollato.
- Screen Sync su Crimson Desert/fullscreen exclusive/HDR e con contenuti DRM.
- Screen Sync con più di 3 luci o su un PC con GPU/CPU limitate.

---

## 8. Rischi residui

| Rischio | Impatto | Probabilità | Mitigazione |
|---|---|---|---|
| Mapping DP diverso da A/B standard | comandi errati o rifiutati | media | fallback su DP osservati, "Test connessione", log |
| Direzione temperatura invertita | caldo/freddo scambiati | media | documentato; toggle per-device in roadmap |
| Scena hardware non supportata | errore firmware | alta | messaggio chiaro, indice/payload modificabili |
| Firmware lento/throttling durante Flow | fade a scatti | media | fps 3/6/10/15/30, durata regolabile, un frame in volo |
| Wi-Fi debole (-85 dBm) | timeout e frame persi | media | avvicinare AP, abbassare fps, health/stop |
| Fullscreen exclusive/HDR in Screen Sync | frame neri o colori slavati | media | borderless, HDR off, messaggio in UI |
| Cattura schermo costosa a 4K | calo fps nel gioco | media | downscale 96×54, 5–15 fps, mss |
| Anti-cheat/DRM | cattura bloccata o dubbio | bassa | solo cattura OS esterna, nessuna iniezione |
| Colori schermo poco fedeli sui bulbi | resa piatta | media | preset, saturazione, cap luminosità |
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
  `lights_config.json`, `scenes.json`, `screen_sync.json`, `tinytuya.json`,
  `tuya-raw.json`, `snapshot.json`, log e backup). Il repository traccia solo i modelli
  `*.example.json`, privi di dati reali. Verificato che la cronologia Git non contenga il
  Device ID reale importato durante il collaudo.
- Screen Sync cattura lo schermo **solo in RAM** e non salva né invia frame; nessuna
  registrazione. La cattura è opt-in tramite il pulsante Avvia.
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
12. Apri **Screen Sync**, scegli il monitor secondario/principale corretto, 3 zone e
    4 punti/zona; avvia e verifica che Studio SX/DX/Sfondo seguano le zone.
13. Prova il gioco prima in borderless e poi in fullscreen/HDR: documenta eventuali frame neri.
14. Chiudi/ferma Screen Sync e verifica che i comandi manuali e il Flow lo fermino.
15. Riavvia l'app: stato noto, scene e configurazione Screen Sync devono essere coerenti.

---

## 11. Roadmap

- Toggle "inverti temperatura" per singola luce e calibrazione Kelvin per modello.
- Cache delle capability per device (evita il primo `status()` dopo ogni avvio).
- Editor visuale dello snapshot con preview dei colori per luce.
- Flow con palette riordinabile via drag&drop e preview animata nella card scena.
- Screen Sync: backend Windows Graphics Capture, tone mapping HDR, multi-monitor avanzato.
- Screen Sync: classificatore semantico leggero (pioggia/bosco/torcia) e preset automatici.
- Screen Sync: più di 7 zone e mappa visuale drag&drop delle luci sullo schermo.
- Sperimentare la modalità music/music-colour nativa per fade più fluidi su modelli compatibili.
- Ordinamento/duplicazione scene e import/export.
- Watchdog opzionale per refresh periodico e riconnessione automatica.
- Packaging PyInstaller con icona e file di configurazione accanto all'eseguibile.
- Test con hardware reale e matrice modelli (A/B/C, 3.3/3.4/3.5) e tuning fps.

---

## 12. Changelog

### 1.3.3 - 2026-11-07

- **Flicker colore/bianco persistente**: rimosso del tutto il caso speciale
  `boosted = 0.0` per saturazioni sotto 0.005. Ora la saturazione è una funzione
  continua da 0 a 1, quindi nessuna soglia binaria da attraversare. Una zona
  quasi neutra resta leggermente colorata e non flipa a bianco.
- Consiglio: muovere la finestra Screen Sync su un altro monitor, perché la cattura
  include anche l’app stessa; in alternativa mappare Studio 1 su una zona specifica
  invece di **Globale** (che è la media di tutte le zone e può essere grigiastra su
  schermi multicolore).

### 1.3.2 - 2026-11-07

- **Flicker colore/bianco**: la soglia per produrre bianco puro è passata da 0.03 a
  0.005, così una zona quasi neutra non oscilla tra colore e bianco per il rumore.
- Consiglio: muovere la finestra Screen Sync su un altro monitor, perché la cattura
  include anche l’app stessa.

### 1.3.1 — 2026-11-07

- **Etichette raw → output** e soglia di correzione buio più selettiva.

### 1.3.0 — 2026-11-07

- **Mappa luci sotto l’anteprima**: ogni zona ha un pulsante con le luci assegnate;
  il menu permette di spuntare più lampadine o passare a **Globale**. Rimossa la card
  separata.
- **Preset in alto**: menu `Default / preset` + **+ Preset** accanto a Salva; rimossi i
  pulsanti preset da Analisi e Reazione. I preset utente sono in
  `screen_sync_presets.json` (runtime) e non includono monitor/mappa luci.
- **Profilo Default shippato**: i default di `ScreenSyncConfig` e
  `screen_sync.example.json` sono il profilo tuning attuale (3 fasce, 9 punti, 60 fps,
  saturazione 1.8, max 80, curva 1.8, minimo 0, Nero = spento).
- **Sensori più compatti**: anteprima 16:9 in una riga bassa, pulsanti spostati a fianco.
- **Rotella**: slider e menu non cambiano più valore con la rotella; la rotella scorre
  solo la pagina.
- Test: **39** (20 Screen Sync), inclusi profilo default e preset store.

### 1.2.8 — 2026-11-07

- **Correzione buio più selettiva**: si applica solo se la mediana è molto più bassa
  della media (testo/HUD su fondo scuro), non alle scene cinematografiche scure ma
  uniformi. Una scena scura colorata non finisce più tutta a OFF.
- **Anteprima trasparente**: etichetta `raw → output` (es. `28% → 14%`, `16% → OFF`)
  e riga di stato con saturazione, media/mediana e fattore.
- Test: **37** (18 Screen Sync), inclusa una scena scura colorata che non deve essere
  scurita ulteriormente.

### 1.2.7 — 2026-11-07

- **Curva buio = toe, non gamma globale**: alzare lo slider non scurisce più le zone
  luminose; agisce solo sulla soglia degli scuri. Risolve i valori 0/7/0 su wallpaper
  luminosi con Curva buio alta.
- **Anteprima fedele**: i riquadri mostrano il colore grezzo campionato, non l’output
  scalato; l’etichetta continua a mostrare `%`/`OFF`.
- **Diagnostica** nella riga di stato: `scena media/mediana · ×fattore`, per capire se
  la cattura vede davvero scuro.
- Test: **36** (17 Screen Sync).

### 1.2.6 — 2026-11-07

- **Nessuna scuritura sulle scene luminose**: la correzione mediana/media si applica
  solo sotto media 0,32 e con clamp 0,4; un desktop/game luminoso con bordi scuri non
  finisce più a 7% o OFF.
- **Anteprima più fedele**: scalatura morbida della luminosità (0,2–1,0) invece del
  fattore lineare che rendeva neri i riquadri già a pochi punti percentuali.
- Test: **36** (17 Screen Sync), inclusa una scena blu luminosa con taskbar scura.

### 1.2.5 — 2026-11-07

- **Nero = spento**: sotto il 5% di luminosità (o su schermo nero) le luci ricevono un
  vero switch-off invece di restare accese al minimo. Isteresi a soglia+2 per evitare
  lampeggi; lo stato spento viene riportato nella UI allo stop.
- L’anteprima mostra **OFF** sulle zone sotto soglia.
- Test: **35** (16 Screen Sync), incluso spegnimento su schermo scuro e riaccensione.

### 1.2.4 — 2026-11-07

- **Schermate scure con testo**: la luminosità usa anche la mediana del frame, così una
  finestra piena di testo bianco su sfondo nero resta quasi spenta invece di accendere
  le luci al 9–18%.
- L’anteprima dei sensori è scalata per la luminosità target: niente più riquadri
  bianchi su schermate nere.
- Test: **34** (15 Screen Sync), incluso testo chiaro su desktop scuro.

### 1.2.3 — 2026-11-07

- **Luminosità Screen Sync**: nuova curva percettiva con toe sul nero e slider
  **Curva buio** (0.6–1.8, default 1.15). Le schermate quasi nere (editor, desktop,
  scene notturne) portano le luci a 0–2% con minimo 0, invece di restare accese.
- Documentata l'interazione con **Mantieni colore su schermo nero**: se attivo, il
  runner continua a tenere l'ultimo colore e non spegne.
- Test: **33** (14 Screen Sync), incluso il caso schermata scura → luminosità quasi zero.

### 1.2.2 — 2026-11-07

- **Gestione colore Screen Sync**: i colori quasi neutri passano ai LED bianchi dedicati
  con temperatura dedotta dalla tinta, eliminando il cast blu/viola del bianco RGB
  sintetizzato; i toni chiari ricevono una curva di saturazione più aggressiva.
- Nuovo switch **Bianco dedicato per colori neutri** e nota sulla luminosità massima
  (>85% il bulbo mescola i LED bianchi e desatura i colori).
- Il runner usa il frame bianco anche con turbo attivo (il music mode resta solo per i
  colori), con lo stesso fallback automatico.
- Test: **32** (13 Screen Sync), inclusi bianco dedicato e saturazione dei toni pastello.

### 1.2.1 — 2026-11-07

- **Screen Sync**: sensori 16:9 liberi (1–8) trascinabili/ridimensionabili con anteprima
  interattiva, in alternativa alle fasce automatiche 3/5/7; `Rigenera fasce`.
- **FPS** fino a 60, preset **Bassa latenza**, smoothing minimo 0.1 s e lettura degli
  **fps reali** accanto ai tempi di cattura/analisi.
- **Turbo music** sperimentale su DP28 `control_data` con `nowait=True` e fallback
  automatico al frame normale.
- Benchmark `mss`: frame intero 2560×1440 ~28 ms vs 4 patch piccole ~41 ms; documentato
  che le zone non accelerano la cattura e che 60 fps richiedono DXGI/WGC.
- Test: **29** (10 Screen Sync), inclusi clamp dei sensori e turbo con fallback.

### 1.2.0 — 2026-11-06

- **Screen Sync**: cattura monitor con mss, 3/5/7 zone, 1/4/9 punti/zona, maschere
  HUD/letterbox, smoothing, saturazione, limiti di luminosità, preset e mappa luci.
- Finestra di configurazione dedicata con monitor, anteprima live, avvio/stop e stop
  nella barra di stato.
- Screen Sync e Flow mutuamente esclusivi; i comandi manuali fermano il sync.
- `mss` aggiunto alle dipendenze; `screen_sync.json` runtime ignorato da Git.
- Test: **26** (inclusi 7 Screen Sync); smoke GUI con cattura reale e controller fake.

### 1.1.0 — 2026-11-06

- **Flow**: fade infinito tra 8 colori, 0.5–5 s per transizione, 3/6/10/15/30 fps, palette
  modificabile, preset, sfasamento tra luci, STOP globale e scene Flow salvabili.
- Fix di sicurezza: file runtime con Local Key rimossi dal tracking Git, esempi sicuri.
- 18 test unitari (incluso il motore Flow); smoke test GUI del Flow con controller fake.
- Screenshot aggiornati e documentazione Flow in README.

### 1.0.0 — 2026-11-06

- Prima release completa: GUI dark, controllo bianco/colore/HW, scene globali e snapshot,
  gestione dispositivi, scansione LAN, import wizard, persistenza atomica, test e docs.
- 14 test unitari; smoke test GUI; nessuna verifica su hardware fisico.
