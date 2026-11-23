# Copione della demo · Wave 0, AS-IS e TO-BE

Durata: circa 20 minuti. Un solo schermo con il browser su **http://localhost:3000** e un terminale
nella cartella `poc/`. La demo ha quattro parti:

1. **AS-IS**: Luca lavora a mano, l'audit attribuisce l'azione a Luca.
2. **TO-BE delegato**: l'assistente AI lavora *per* Luca. L'audit attribuisce sempre a Luca, tramite l'agente.
3. **TO-BE autonomo**: un agente lavora da solo. L'audit attribuisce l'azione all'agente.
4. **Controlli**: cosa succede quando un agente prova a fare ciò che non deve.

Per ogni passo: cosa fare, cosa vede il pubblico, cosa dire e la prova che resta. Le immagini sono in
[`evidence/sample-2026-11-23/screens/`](evidence/sample-2026-11-23/screens/).

## Prima di iniziare (5 minuti prima)

```bash
cd poc
docker compose down -v && docker compose up -d --build     # parte pulito
docker compose --profile check run --rm check               # deve finire con "Audit: 13/13 checks passed"
docker compose down -v && docker compose up -d              # di nuovo pulito: i controlli hanno scritto dati e audit
```

- `/etc/hosts` contiene `127.0.0.1 sso.demo.local`.
- Con un modello: in `.env` `LLM_MODEL=gpt` e `OPENAI_API_KEY` (oppure `claude-sonnet` e `ANTHROPIC_API_KEY`).
  Senza, l'assistente lavora in *modalità scripted*: i flussi di identità, permessi e audit sono identici.
- Schede aperte: la UI su `localhost:3000`; la UI admin di LiteLLM su `localhost:4000/ui` (`admin` / master key)
  per l'atto finale.

## Il messaggio in una frase

Ogni azione nell'app porta un JWT emesso da Keycloak che dice *chi è la persona* e, se c'è, *quale agente
agisce*. L'audit mostra quel token così com'è arrivato: con l'AI non si perde chi ha fatto cosa, anzi si vede meglio.

---

## Parte 1 · AS-IS: Luca lavora a mano

### 1. Login
**Fai:** *Sign in* con `luca` / `luca`. Keycloak chiede *"Allow agent-crm-assistant to act on your behalf?"*:
clicca **Yes** (servirà nella parte 2). Si vedono solo i clienti NORTH; in alto *area-manager, rep*.

**Da dire:** ruoli e territorio arrivano dal token di Keycloak, non da tabelle dell'app.

**Prova:** `0-consent.png`, `1-login-territory.png`.

### 2. Nota scritta a mano
**Fai:** apri il primo cliente, scrivi una nota nel campo *Visit note, written by you*, **Save note**.

**Il pubblico vede:** la nota a destra con il badge *by luca* e lo stato **final**.

**Prova:** `2-as-is-manual-note.png`.

### 3. Audit: chi l'ha fatto
**Fai:** tab **Audit** in alto. Clicca la riga *luca (by hand) · POST /notes*.

**Il pubblico vede:** a sinistra il **JWT arrivato all'API**: `sub` = Luca, `azp` = demo-crm, **nessun `act`**,
ruoli *area-manager, rep*, firma verificata. Provenienza *demo-crm UI*. A destra: *questa chiamata non è passata
dal gateway*.

**Da dire:** questo è il mondo di oggi. Una persona, un token, un'azione.

**Prova:** `3-as-is-audit-luca-by-hand.png`.

---

## Parte 2 · TO-BE delegato: l'assistente lavora per Luca

### 4. L'assistente prepara la visita
**Fai:** tab **CRM**, stesso cliente, **Assistant: prepare visit and draft a note**.

**Il pubblico vede:** la traccia *Delegated token: sub = luca, act = agent-crm-assistant, roles = rep*; la nota
*proposed by agent-crm-assistant for luca* in stato **draft**. Luca può cliccare **Confirm**.

**Da dire:** l'agente ha scambiato il token di Luca con uno nuovo (token exchange): la persona resta il soggetto,
l'agente è l'attore, i ruoli scendono a `rep`. Solo Luca rende definitiva la nota.

**Prova:** `4-to-be-assistant-draft-note.png`.

### 5. Audit: Luca, tramite l'agente
**Fai:** tab **Audit**, clicca la riga *luca through agent-crm-assistant · POST /notes · MCP server, via LiteLLM*.

**Il pubblico vede:** tre JWT, con lo stesso id di correlazione:
- **all'API**: `sub` = Luca, `act` = agent-crm-assistant, ruoli solo `rep`;
- **a LiteLLM, token di ammissione**: quello dell'agente (`azp` = agent-crm-assistant, nessun `act`);
- **a LiteLLM, token girato al server MCP**: è lo stesso arrivato all'API (stesso `jti`).

**Da dire:** l'azione è di Luca, fatta attraverso un agente, ed è scritto nel token, non in un log applicativo.
Il gateway ha controllato che il token delegato appartenga proprio a quell'agente. Tutto con LiteLLM open source:
la verifica dei JWT è un nostro hook, non serve la licenza Enterprise.

**Prova:** `5-to-be-audit-luca-through-agent-jwts.png`; `audit-demo-crm.json` e `audit-gateway-jwts.json`.

### 6. Il report del team: Luca può, l'assistente no
**Fai:** tab **CRM**, **Assistant: team report**. Con un modello puoi chiederlo in chat.

**Il pubblico vede:** `get_team_report` **refused by demo-crm**. Nell'Audit, con *Refused only*, la riga rossa
con il motivo *role area-manager required*.

**Da dire:** Luca è area manager, ma il suo assistente riceve solo `rep`. Il privilegio minimo lo decide Keycloak.

**Prova:** `6-to-be-team-report-refused.png`.

---

## Parte 3 · TO-BE autonomo: l'agente lavora da solo

### 7. Lo scheduler avvia agent-dq
**Fai:** **Run agent-dq now** (fa le veci dello scheduler notturno).

**Il pubblico vede:** promemoria con il badge **agent-dq (autonomous)** per le visite senza esito.

**Prova:** `7-to-be-agent-dq-reminders.png`.

### 8. Audit: l'agente, nessuna persona
**Fai:** tab **Audit**, filtro *Autonomous agents*, clicca una riga *POST /reminders*.

**Il pubblico vede:** `sub` = *service-account-agent-dq*, `azp` = agent-dq, ruolo `dq-agent`, **nessun `act`** e
nessuna persona.

**Da dire:** quando non c'è una persona, l'audit non ne inventa una: l'azione è dell'agente, con la sua
identità. Si autentica con una chiave privata, senza segreti condivisi.

**Prova:** `8-to-be-audit-agent-dq-autonomous.png`.

**Riassunto per il pubblico** (filtro *Everyone*): tre righe, tre forme di identità.

| Chi | JWT all'API |
| --- | --- |
| luca (by hand) | `sub` luca, `azp` demo-crm, nessun `act` |
| luca through agent-crm-assistant | `sub` luca, `act` agent-crm-assistant, ruoli ridotti |
| agent-dq (autonomous) | `sub` service account, `azp` agent-dq, nessun `act` |

---

## Parte 4 · Controlli

### 9. Il gateway ferma ciò che l'agente non deve fare
**Fai:** **Assistant: try a tool it doesn't have**, poi **Assistant: try a final note**.

**Il pubblico vede:** `create_reminder` **refused by gateway**; `draft_visit_note` **refused by gateway** con
*Violated guardrail policy*. Queste richieste non arrivano all'app, quindi non sono nel suo audit: sono nel log di LiteLLM.

**Prova:** `9a-control-tool-not-allowed.png`, `9b-control-final-note-guardrail.png`.

### 10. E se l'agente aggira il gateway?
**Fai:** **Assistant: bypass the gateway**. Poi tab **Audit**, riga con provenienza **crm-assistant, direct**.

**Il pubblico vede:** la nota salvata solo come **draft**. Nell'audit il JWT all'API dice ancora Luca tramite
l'agente, ma a destra: *il gateway non ha visto nessun token con questo id*. La provenienza è ricavata dalla rete,
non da quello che dichiara il chiamante.

**Da dire:** due livelli indipendenti. Anche fuori dal gateway l'app riconosce l'agente e salva solo bozze, e
l'audit rende visibile il bypass.

**Prova:** `10-control-direct-call-stored-as-draft.png`, `11-control-audit-direct-call-no-gateway-jwt.png`.

### 11. Kill switch e log del gateway
**Fai:** nel terminale

```bash
./scripts/kill-switch.sh block
```

poi un pulsante dell'assistente: *gateway refused agent-crm-assistant*. Ripristina con

```bash
./scripts/kill-switch.sh unblock
```

Infine UI admin di LiteLLM, **Logs**: ogni chiamata dell'agente ha l'utente (il `sub` di Luca) e il team (l'agente).

**Limite da dichiarare:** il kill switch agisce sul gateway; la chiamata diretta del passo 10 passerebbe ancora,
come bozza. In produzione le app vanno rese raggiungibili solo tramite gateway/MCP, oppure si disabilita anche il
client dell'agente in Keycloak.

---

## Domande probabili

- **Serve LiteLLM Enterprise?** No. La verifica dei JWT e il loro log lato gateway sono un hook `custom_auth`
  della versione open source (`litellm/keycloak_auth.py`).
- **Il token è salvato?** No: solo header e claim decodificati. Il token intero è una credenziale finché non scade.
- **L'audit si può modificare?** No: la tabella è di sola aggiunta, un trigger del database rifiuta modifiche e
  cancellazioni.
- **Chi vede l'audit?** Gli area manager, di persona. Gli agenti no, nemmeno a nome di un area manager.
- **Dove sono i dati?** Tutto sintetico, generato all'avvio (`demo-crm/api/app/seed.py`).

## Rigenerare le evidenze

```bash
docker compose --profile check run --rm evidence             # scrive evidence/run-<data>/
node scripts/capture-screens.js evidence/run-<data>/screens   # facoltativo, serve Playwright
```

`SUMMARY.md` elenca i controlli per atto, l'audit di demo-crm con il JWT di ogni chiamata e il log LiteLLM di
Luca. Le cartelle `run-*` non vengono committate; quella di esempio sì.
