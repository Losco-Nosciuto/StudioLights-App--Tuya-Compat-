# Piano tecnico — Screen Sync (luci reattive allo schermo)

**Progetto:** Studio Lights
**Versione di partenza:** 1.1.0
**Versione target:** 1.2.0
**Data:** 6 novembre 2026
**Stato:** piano da approvare, nessuna implementazione avviata

---

## 1. Obiettivo

Aggiungere a Studio Lights una modalità **Screen Sync**: le lampadine seguono in tempo
reale i colori e la luminosità dello schermo del gioco, con transizioni morbide.

Esempi d'uso:

- città sotto la pioggia → luci grigio-azzurre, fredde, poco sature;
- stanza buia con torce → luci arancio/ambra, con luminosità pulsante ma filtrata;
- bosco estivo → verdi profondi, con variazioni lente.

L'effetto non richiede di "capire" semanticamente la scena: i colori dominanti e la
luminanza dello schermo contengono già l'informazione necessaria. Il riconoscimento
semantico è un'estensione opzionale, non parte dell'MVP.

> Nota terminologica: non è uno screen reader per accessibilità, ma un sistema di
> **ambient lighting reattivo** (simile a Philips Hue Sync/Ambilight) pilotato via LAN
> sulle lampadine Tuya.

### Non obiettivi (MVP)

- Riconoscimento di oggetti, meteo o biomi tramite AI.
- Sincronizzazione beat-perfect o frame-perfect con la musica.
- Supporto a contenuti DRM/protetti.
- Cattura su macOS/Linux (prima release Windows-only; il core resta cross-platform).
- Registrazione o salvataggio di screenshot/frame.

---

## 2. Esperienza utente

1. L'utente apre il nuovo pannello **Screen Sync**.
2. Sceglie il monitor del gioco e associa ogni luce a una zona:
   - Luce SX → sinistra
   - Luce DX → destra
   - Luce Sfondo → centro/globale
3. Regola:
   - intensità della reazione (0–100%);
   - saturazione (0.8–1.6);
   - luminosità massima (10–90%);
   - velocità di inseguimento (0.5–3 s);
   - preset **Realistico / Cinema / Neon / Naturale**;
   - comportamento su menu/pausa: mantieni ultimo colore / spegni / colore fisso.
4. Premi **AVVIA SYNC** (o usa una hotkey globale).
5. Le luci seguono lo schermo con fade continuo; **STOP SYNC** è disponibile nella barra
   di stato e tramite hotkey globale, perché in fullscreen la finestra dell'app non è
   raggiungibile.

Vincoli UX:

- Screen Sync e Flow palette sono **mutuamente esclusivi**.
- Qualsiasi comando manuale, cambio dispositivo, refresh o scena statica ferma il sync.
- Il pulsante di stop globale è sempre visibile nella barra di stato dell'app.
- Hotkey globale configurabile, default `Ctrl+Alt+S`, registrata con
  `RegisterHotKey` di Windows (nessuna dipendenza esterna, nessun privilegio admin).

---

## 3. Architettura

```
Windows screen / game window
        │
        ▼
ScreenCaptureBackend (Pillow ImageGrab → mss / DXGI/WGC)
        │  frame RGB a 10–15 fps, solo monitor selezionato
        ▼
FrameDownscaler + ZoneAnalyzer
        │  96×54 o 64×36, maschere HUD/letterbox
        ▼
ColourSmoother + SceneChangeDetector
        │  EMA 0.8–3 s, isteresi, crossfade
        ▼
LightMapper
        │  zone → luce, saturazione, luminosità, gamma
        ▼
FrameStreamer (refactor di FlowRunner)
        │  un frame in volo per luce, ACK per frame
        ▼
LightController → BulbDevice → Tuya LAN
```

Componenti nuovi:

```
studiolights/
  screen/
    __init__.py
    capture.py       backend cattura, enumerazione monitor, frame nero
    analysis.py      downscale, maschere, zone, statistiche colore
    smoothing.py     EMA, rilevamento cambio scena, mapping
    settings.py      ScreenSyncConfig, persistenza
  screen_sync.py     orchestratore capture → analysis → streamer
  ui/screen_sync.py  pannello/dialogo UI (oppure tab dedicato)
```

Refactor consigliato: estrarre da `flow.py` la logica di stream (thread, pending future,
stop) in `FrameStreamer`, usata da:
- `FlowRunner` con `PaletteProvider` (comportamento attuale invariato);
- `ScreenSyncRunner` con `ScreenProvider`.

In questo modo il fix "un frame in volo per luce" e lo stop restano unici e testati.

---

## 4. Pipeline e timing

| Stadio | Frequenza target | Costo atteso |
|---|---|---|
| Cattura schermo | 10–15 fps | 3–15 ms/frame (dipende da risoluzione/backend) |
| Downscale a 96×54 | per frame | <2 ms |
| Analisi zone | 10–15 fps | 1–4 ms |
| Smoothing/mapping | per frame | <1 ms |
| Invio frame alle luci | 8–10 fps | 20–80 ms RTT, in parallelo |

Latenza percepita target: **150–300 ms**. Per l'ambient lighting va bene; non è un sistema
per sincronizzare effetti a tempo di musica.

Regole:

- Code **bounded** tra capture e analysis: se l'analisi è in ritardo, si scarta il frame
  vecchio e si usa l'ultimo (drop-frame, nessun accumulo).
- Un solo frame in volo per lampadina (già implementato nel Flow).
- Il capture gira in un thread separato; l'analisi in un altro; nessuna chiamata Tk da
  thread di lavoro.
- Il risultato viene pubblicato in una dataclass immutabile (`ZoneFrame`) e letto dallo
  streamer.

---

## 5. Backend di cattura

### MVP (nessuna nuova dipendenza)

- `PIL.ImageGrab.grab(bbox=<monitor bbox>)` — Pillow è già richiesto.
- Funziona bene in **borderless/windowed**; può dare frame neri in fullscreen exclusive.
- A 1080p e 10 fps è probabilmente sufficiente; a 1440p/4K va misurato.
- Vantaggio: zero dipendenze, si integra subito, consente un PoC in poche ore.

### Backend opzionali, in ordine di preferenza

1. **`mss`** — cattura GDI veloce, matura, Windows/macOS/Linux, piccola dipendenza.
2. **`dxcam`** — DXGI Desktop Duplication, GPU-friendly, buona per fullscreen;
   verificare supporto Python 3.12 e manutenzione.
3. **Windows Graphics Capture** (`windows-capture` o binding WinRT) — API moderna,
   supporta window capture e monitor; richiede test di compatibilità e gestione HDR.

Decisione: implementare un'interfaccia `ScreenCaptureBackend` con
`available_backends()` e fallback automatico. Il backend scelto è visibile nelle
impostazioni e nei log. L'utente può forzare un backend in caso di problemi.

### Casi critici

- **Fullscreen exclusive**: se il frame è nero per N frame consecutivi, mostrare
  "Passa a borderless windowed" e fermare il sync (non inviare nero alle luci).
- **DRM/protected content**: cattura nera; nessun workaround, documentato.
- **HDR**: la MVP lavora in SDR. Se il frame è HDR, avvisare e chiedere di disattivare HDR
  nel gioco; tone mapping in una fase successiva.
- **Multi-monitor**: enumerare i monitor con nome/risoluzione/coordinate; catturare solo
  quello scelto. Gestire DPI scaling e monitor negativi a sinistra.
- **Finestra non in focus**: la cattura continua; opzione "pausa se il gioco non è in
  foreground" per evitare di reagire al desktop o ad altre app.

---

## 6. Analisi e mapping colori

### 6.1 Zone

- Griglia di analisi ridotta (es. 96×54).
- Maschere predefinite:
  - top 12%: HUD/minimappa;
  - bottom 15%: HUD/barre;
  - centro 8%: crosshair;
  - bande nere rilevate automaticamente (letterbox).
- Zone per 3 luci:
  - sinistra: 0–35%;
  - centro/globale: 25–75% (o media pesata);
  - destra: 65–100%.
- Le zone laterali usano i bordi dello schermo, più rappresentativi dell'ambiente;
  il centro è più soggetto a HUD e protagonisti.

### 6.2 Statistiche

- Media in **linear RGB** (undo sRGB) o mediana/percentile per evitare che un flash
  sovrascriva la scena.
- Luminanza media e 90° percentile per la luminosità.
- Saturazione media, hue dominante.
- Esclusione dei pixel quasi neri delle bande nere.
- Filtro anti-flash: se un frame è molto più luminoso del precedente per <200 ms, non
  seguirlo subito.

### 6.3 Smoothing

- EMA con `alpha = 1 - exp(-dt / tau)`, `tau` configurabile 0.8–3.0 s.
- Isteresi sul cambio scena: distanza colore sostenuta per ≥0.5 s → transizione più
  rapida (0.6–1.0 s); altrimenti il cambio è ignorato o rallentato.
- Clamp della velocità di variazione della luminosità (es. max 25%/s) per evitare
  lampeggi aggressivi.
- Menu/pausa: se lo schermo è quasi statico per >2 s o viene rilevato un menu, applicare
  la politica scelta (hold/spegni/colore fisso).

### 6.4 Mapping alle lampadine

- RGB schermo → HSV.
- Saturazione: moltiplicatore utente 0.8–1.6; evita colori spenti.
- Luminosità: curva gamma + cap utente; minimo 8–10% per non far sembrare le luci spente.
- Clamp di gamut: i bulb A60 non coprono tutto lo spazio sRGB; i colori molto saturi
  possono risultare diversi. Prevedere un piccolo "colour gain" per luce in una fase
  successiva.
- Blackout: se la zona è quasi nera, abbassare la luce al minimo o spegnerla, in base
  alla preferenza.
- Preset:
  - **Realistico**: saturazione 1.0, luminosità contenuta, smoothing lento;
  - **Cinema**: contrasto e saturazione 1.15, luminosità massima 65%;
  - **Neon**: saturazione 1.5, luminosità 80%, risposta più rapida;
  - **Naturale**: desatura i grigi e privilegia verdi/blu.

---

## 7. Integrazione con Studio Lights

### Nuovi concetti

- `ScreenSyncConfig`: monitor, zone map, tau, saturazione, cap luminosità, preset,
  hotkey, comportamento menu, backend.
- `ScreenSyncRunner`: orchestratore; espone `start()`, `stop()`, `is_running`,
  `last_colors`, `stats`.
- `ZoneFrame`: colori/luminanze per zona + timestamp + flag `black_frame`.

### Mutua esclusione

- Avvio Screen Sync: se il Flow palette è attivo, chiederlo/fermarlo.
- Avvio Flow palette o comando manuale: ferma Screen Sync.
- `power_selected`, `_on_light_power`, `apply_scene`, `refresh_states` (?) e
  `_after_config_change` fermano il sync.
- Refresh stato: può essere utile per health, ma durante il sync restituirebbe colori
  intermedi; meglio non fermarlo, ma non usare il report per aggiornare i colori.
- Chiusura app: stop del runner prima di chiudere le socket.

### Stato e persistenza

- `screen_sync.json` nella root, creato al primo avvio; **ignorato da Git** (nessun
  segreto, ma preferenze personali). Esempio `screen_sync.example.json` tracciato.
- Salvataggio delle preferenze alla chiusura o su modifica.
- Nessun frame o screenshot salvato.

### Barra di stato

- Indicatore `SYNC · 10 fps · 42 ms` e pulsante `■ STOP SYNC`.
- Se il capture fallisce: pallino rosso e messaggio con suggerimento borderless/HDR.

---

## 8. UI

Due opzioni, da scegliere in base allo spazio:

### Opzione A (consigliata): pannello dedicato

- Pulsante **Screen Sync** nell'header apre una finestra non modale 720×640.
- Contiene monitor, zone, slider, preset, anteprima live delle 3 zone (quando la finestra
  è visibile), start/stop, statistiche.
- Vantaggio: non comprime il tab control già a 4 voci; l'anteprima è utile per tarare.
- Svantaggio: una finestra in più.

### Opzione B: quinto tab

- Aggiungere "Screen" al segmented control.
- A 430 px di larghezza, 5 tab sono stretti; servirebbe una UI molto compatta o un
  `CTkOptionMenu` al posto del segmented.
- Meno spazio per l'anteprima.

Decisione consigliata: **Opzione A**, con hotkey globale e stop nella barra di stato.

### Anteprima

- Quando la finestra Screen Sync è aperta, mostrare 3 rettangoli con il colore target e
  la luminanza; aggiornamento a 5 fps via coda thread-safe.
- Non mostrare il frame intero (privacy e costo).

---

## 9. Dipendenze

MVP:

- Nessuna nuova dipendenza obbligatoria: Pillow `ImageGrab` + `colorsys`.
- `numpy` non è installato e non è necessario per 96×54; valutarlo solo se il profiling
  mostra un collo di bottiglia. In tal caso aggiungerlo come extra opzionale.

Fase 2:

- `mss` (MIT) per cattura più veloce; oppure `dxcam` / `windows-capture` per fullscreen.
- Le dipendenze di cattura vanno in un extra opzionale (`requirements-screen.txt`) per non
  appesantire l'installazione base; l'app deve degradare con un messaggio chiaro se
  mancano.

Hotkey: `ctypes` + `RegisterHotKey` (Windows), nessuna dipendenza.

---

## 10. Test

### Unitari (senza schermo/hardware)

- Zone rosse/blu/verdi sintetiche → colori corretti.
- Letterbox detection e maschera HUD.
- Smoothing: convergenza, nessun overshoot, cambio scena con isteresi.
- Mapping: saturazione, cap luminosità, gamma, blackout.
- `ScreenSyncConfig` round-trip.
- `FrameStreamer` con controller fake: frame, stop, un frame in volo, phase.
- Rilevamento frame nero e fallback.

### Integrazione GUI

- Avvio/stop con capture provider fake e controller fake.
- Mutua esclusione Flow ↔ Screen Sync.
- Hotkey simulata (dove possibile).
- Anteprima zone con frame sintetici.
- Nessuna eccezione Tk.

### Manuale su hardware reale

1. Crimson Desert in **borderless**, HDR off.
2. Tre luci: SX/DX/Sfondo; verificare la corrispondenza zone.
3. Città pioggia, torce, bosco: valutare colore e stabilità.
4. Menu/pausa: verificare hold/spegni.
5. 6/10/15 fps e 0.8/1.5/2.5 s: trovare il compromesso.
6. Misurare CPU/GPU e latenza; controllare che il gioco non cali di fps.
7. Spegnere una luce: le altre devono continuare; health coerente.
8. STOP via hotkey mentre il gioco è in fullscreen/borderless.

### Criteri di accettazione

- 3 luci seguono le zone con latenza percepita ≤300 ms.
- Nessun lampeggio aggressivo; cambio scena fluido.
- CPU aggiuntiva ≤5–10% su un PC da gioco moderno (da misurare).
- Start/stop affidabile, anche con hotkey e game in foreground.
- Frame neri/fullscreen/HDR gestiti con messaggi chiari, senza inviare nero alle luci.
- Test unitari e smoke GUI verdi.
- Nessun frame lasciato su disco o inviato in rete oltre ai comandi Tuya.

---

## 11. Rischi e mitigazioni

| Rischio | Impatto | Mitigazione |
|---|---|---|
| Fullscreen exclusive dà frame neri | sync inutilizzabile | borderless; rilevamento e messaggio; backend DXGI/WGC |
| HDR slavato | colori sbagliati | SDR per MVP; tone mapping in fase 2 |
| Anti-cheat | dubbio/blocco | sola cattura OS esterna, nessuna iniezione; disclaimer; test |
| Wi-Fi debole (-85 dBm) | frame persi, scatti | 6–8 fps, transizioni lente, migliorare Wi-Fi |
| Firmware lento | fade a gradini | frame rate adattivo, un frame in volo, cap fps |
| HUD/flash | colori impazziti | maschere, mediana, isteresi, anti-flash |
| Cattura costosa a 4K | calo fps nel gioco | downscale, GPU capture, 10 fps, backend opzionale |
| Latenza alta | effetto ritardato | target 150–300 ms, metriche visibili |
| Privacy | timore di registrazione | nessun salvataggio, solo RAM, opt-in |
| Troppe luci | traffico eccessivo | limite consigliato 6–8 luci a 10 fps |
| Hotkey occupata | stop non funziona | hotkey configurabile, stop anche nella UI |

---

## 12. Milestone e stime

| Fase | Contenuto | Stima |
|---|---|---|
| M0 | Spike cattura: ImageGrab vs mss vs DXGI; borderless/fullscreen/HDR | 0.5–1 giorno |
| M1 | Analisi zone + maschere + smoothing, test sintetici | 1–1.5 giorni |
| M2 | Refactor FrameStreamer + ScreenSyncRunner + controller fake | 1–1.5 giorni |
| M3 | UI Screen Sync, config, hotkey, stop/status | 1–1.5 giorni |
| M4 | Taratura su Crimson Desert, performance, docs | 1–2 giorni |
| **MVP** | | **4–6 giorni** |
| Fase 2 | Classificatore semantico/AI, HDR tone mapping, backend WGC | 1–2 settimane |

Le stime escludono imprevisti legati a fullscreen/anti-cheat/HDR del gioco specifico.

---

## 13. Domande aperte

1. Crimson Desert gira in **fullscreen exclusive** o **borderless**? HDR attivo?
2. Le tre luci sono **SX / DX / sfondo** rispetto allo schermo?
3. Preferisci una resa **realistica** o **cinematografica/neon** come default?
4. Qual è la luminosità massima accettabile per gli occhi (es. 70%)?
5. Va bene una finestra dedicata **Screen Sync** (consigliata) o preferisci un quinto tab?
6. Sei disponibile ad aggiungere `mss`/`dxcam` come dipendenze opzionali se ImageGrab non
   basta?
7. Hotkey preferita per start/stop (default `Ctrl+Alt+S`)?

---

## 14. Fuori scope / rimandato

- Riconoscimento semantico "pioggia/foresta/torcia" con AI.
- Sync audio/musica beat-perfect.
- Supporto macOS/Linux per la cattura.
- Contenuti DRM.
- Salvataggio/registrazione di frame.
- Controllo di luci non Tuya (Hue, WLED) — architettura futura possibile.

---

## 15. Ordine di implementazione consigliato

1. Backend di cattura astratto + probe monitor + frame nero.
2. Analisi zone su frame sintetici (senza GUI).
3. Refactor `FrameStreamer` mantenendo i test Flow esistenti.
4. `ScreenSyncRunner` con controller fake.
5. UI minima (start/stop, monitor, 3 zone, 3 slider) + hotkey.
6. Taratura su gioco reale e documentazione.

Il primo passo concreto è **M0**: verificare la cattura di Crimson Desert in borderless e
fullscreen e misurare il costo di ImageGrab a 1080p/1440p. Da quel risultato dipendono
backend e fps definitivi.
