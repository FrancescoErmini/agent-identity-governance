# Copione della demo · Wave 0, AS-IS e TO-BE

Durata: circa 20 minuti. Un terminale nella cartella `poc/` e tre schede del browser, una per app:

| App | Indirizzo | Cos'è |
| --- | --- | --- |
| **demo-crm** (barra blu) | http://localhost:3000 | Il CRM di tutti i giorni. Nessuna AI. |
| **AI assistant** (barra viola) | http://localhost:3001 | L'assistente, un'app a parte accanto al CRM. |
| **Audit console** (barra grigia) | http://localhost:3002 | Chi ha fatto cosa, con quale JWT. Per area manager. |

La demo ha quattro parti:

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
- Schede pronte: le tre app (non ancora loggate) e la UI admin di LiteLLM su `localhost:4000/ui`
  (`admin` / master key) per l'atto finale. Apri l'assistente **solo** nella parte 2.

## Il messaggio in una frase

Ogni azione nell'app porta un JWT emesso da Keycloak che dice *chi è la persona* e, se c'è, *quale agente
agisce*. L'audit mostra quel token così com'è arrivato: con l'AI non si perde chi ha fatto cosa, anzi si vede meglio.

---

## Parte 1 · AS-IS: Luca lavora a mano

### 1. Login al CRM
**Fai:** scheda **demo-crm** (:3000), *Sign in* con `luca` / `luca`. Nessuna domanda sull'AI: è il login di sempre.
Si vedono solo i clienti NORTH; in alto *area-manager, rep*.

**Da dire:** ruoli e territorio arrivano dal token di Keycloak, non da tabelle dell'app.

**Prova:** `1-as-is-crm.png`.

### 2. Nota scritta a mano
**Fai:** apri il primo cliente, scrivi una nota in *New visit note*, **Save note**.

**Il pubblico vede:** la nota a destra con il badge *by luca* e lo stato **final**.

**Prova:** `2-as-is-manual-note.png`.

### 3. Audit: chi l'ha fatto
**Fai:** scheda **Audit console** (:3002), *Sign in* (entra subito: stessa sessione Keycloak). Clicca la riga
*luca (by hand) · POST /notes*.

**Il pubblico vede:** a sinistra il **JWT arrivato all'API**: `sub` = Luca, `azp` = crm-web (il CRM), **nessun `act`**,
ruoli *area-manager, rep*, firma verificata. Provenienza *demo-crm UI*. A destra: *questa chiamata non è passata
dal gateway*.

**Da dire:** questo è il mondo di oggi. Una persona, un token, un'azione.

**Prova:** `3-as-is-audit-luca-by-hand.png`.

---

## Parte 2 · TO-BE delegato: l'assistente lavora per Luca

### 4. Luca apre l'assistente e dà il consenso
**Fai:** scheda **AI assistant** (:3001), *Sign in*. Keycloak chiede *"Allow agent-crm-assistant to act on your
behalf?"*: **Yes**. In alto compare il badge **assistant allowed**.

**Da dire:** è il primo momento in cui l'AI entra in scena, e lo fa con un consenso esplicito e registrato.
Il token di Luca ora contiene `may_act`: solo quell'agente può agire per lui, e solo per lui.

**Prova:** `4-to-be-consent.png`.

### 5. L'assistente prepara la visita
**Fai:** scegli il cliente, **Prepare the visit and draft a note**.

**Il pubblico vede:** la traccia *Delegated token: sub = luca, act = agent-crm-assistant, roles = rep* e i tool
chiamati. Poi, nella scheda **demo-crm**, la nota *proposed by agent-crm-assistant for luca* in stato **draft**,
con **Confirm**.

**Da dire:** l'agente ha scambiato il token di Luca con uno nuovo (token exchange): la persona resta il soggetto,
l'agente è l'attore, i ruoli scendono a `rep`. Il CRM non è cambiato: la bozza arriva lì e solo Luca la conferma.

**Prova:** `5-to-be-assistant-draft-note.png`, `6-to-be-draft-waiting-in-crm.png`.

### 6. Audit: Luca, tramite l'agente
**Fai:** scheda **Audit console**, **Refresh**, clicca la riga *luca through agent-crm-assistant · POST /notes · MCP server, via LiteLLM*.

**Il pubblico vede:** tre JWT, con lo stesso id di correlazione:
- **all'API**: `sub` = Luca, `act` = agent-crm-assistant, ruoli solo `rep`;
- **a LiteLLM, token di ammissione**: quello dell'agente (`azp` = agent-crm-assistant, nessun `act`);
- **a LiteLLM, token girato al server MCP**: è lo stesso arrivato all'API (stesso `jti`).

**Da dire:** l'azione è di Luca, fatta attraverso un agente, ed è scritto nel token, non in un log applicativo.
Il gateway ha controllato che il token delegato appartenga proprio a quell'agente. Tutto con LiteLLM open source:
la verifica dei JWT è un nostro hook, non serve la licenza Enterprise.

**Prova:** `7-to-be-audit-luca-through-agent-jwts.png`; `audit-demo-crm.json` e `audit-gateway-jwts.json`.

### 7. Il report del team: Luca può, l'assistente no
**Fai:** scheda **AI assistant**, **Team report**. Con un modello puoi chiederlo nella chat.

**Il pubblico vede:** `get_team_report` **refused by demo-crm**. Nell'Audit console, con *Refused only*, la riga rossa
con il motivo *role area-manager required*.

**Da dire:** Luca è area manager, ma il suo assistente riceve solo `rep`. Il privilegio minimo lo decide Keycloak.

**Prova:** `8-to-be-team-report-refused.png`.

---

## Parte 3 · TO-BE autonomo: l'agente lavora da solo

### 8. Lo scheduler avvia agent-dq
**Fai:** nell'**AI assistant**, **Run agent-dq now** (fa le veci dello scheduler notturno).

**Il pubblico vede:** i promemoria creati, con il badge **agent-dq (autonomous)**. I rep li ritrovano nel loro CRM.

**Prova:** `9-to-be-agent-dq-run.png`.

### 9. Audit: l'agente, nessuna persona
**Fai:** **Audit console**, filtro *Autonomous agents*, clicca una riga *POST /reminders*.

**Il pubblico vede:** `sub` = *service-account-agent-dq*, `azp` = agent-dq, ruolo `dq-agent`, **nessun `act`** e
nessuna persona.

**Da dire:** quando non c'è una persona, l'audit non ne inventa una: l'azione è dell'agente, con la sua
identità. Si autentica con una chiave privata, senza segreti condivisi.

**Prova:** `10-to-be-audit-agent-dq-autonomous.png`.

**Riassunto per il pubblico** (filtro *Everyone*): tre righe, tre forme di identità.

| Chi | JWT all'API |
| --- | --- |
| luca (by hand) | `sub` luca, `azp` crm-web (il CRM), nessun `act` |
| luca through agent-crm-assistant | `sub` luca, `act` agent-crm-assistant, ruoli ridotti |
| agent-dq (autonomous) | `sub` service account, `azp` agent-dq, nessun `act` |

---

## Parte 4 · Controlli

### 10. Il gateway ferma ciò che l'agente non deve fare
**Fai:** nell'**AI assistant**, **Use a tool it doesn't have**, poi **Write a final note**.

**Il pubblico vede:** `create_reminder` **refused by gateway**; `draft_visit_note` **refused by gateway** con
*Violated guardrail policy*. Queste richieste non arrivano all'app, quindi non sono nel suo audit: sono nel log di LiteLLM.

**Prova:** `11a-control-tool-not-allowed.png`, `11b-control-final-note-guardrail.png`.

### 11. E se l'agente aggira il gateway?
**Fai:** **Bypass the gateway**. Poi **Audit console**, riga con provenienza **crm-assistant, direct**.

**Il pubblico vede:** la nota salvata solo come **draft**. Nell'audit il JWT all'API dice ancora Luca tramite
l'agente, ma a destra: *il gateway non ha visto nessun token con questo id*. La provenienza è ricavata dalla rete,
non da quello che dichiara il chiamante.

**Da dire:** due livelli indipendenti. Anche fuori dal gateway l'app riconosce l'agente e salva solo bozze, e
l'audit rende visibile il bypass.

**Prova:** `12-control-direct-call.png`, `13-control-audit-direct-call-no-gateway-jwt.png`.

### 12. Kill switch e log del gateway
**Fai:** nel terminale

```bash
./scripts/kill-switch.sh block
```

poi un pulsante dell'assistente: *gateway refused agent-crm-assistant*. Ripristina con

```bash
./scripts/kill-switch.sh unblock
```

Infine UI admin di LiteLLM, **Logs**: ogni chiamata dell'agente ha l'utente (il `sub` di Luca) e il team (l'agente).

**Limite da dichiarare:** il kill switch agisce sul gateway; la chiamata diretta del passo 11 passerebbe ancora,
come bozza. In produzione le app vanno rese raggiungibili solo tramite gateway/MCP, oppure si disabilita anche il
client dell'agente in Keycloak.

---

## Domande probabili

- **Serve LiteLLM Enterprise?** No. La verifica dei JWT e il loro log lato gateway sono un hook `custom_auth`
  della versione open source (`litellm/keycloak_auth.py`).
- **Il token è salvato?** No: solo header e claim decodificati. Il token intero è una credenziale finché non scade.
- **L'audit si può modificare?** No: la tabella è di sola aggiunta, un trigger del database rifiuta modifiche e
  cancellazioni.
- **Perché due login diversi?** Il CRM usa il client Keycloak `crm-web` (login classico, nessuna delega).
  L'assistente usa il client `demo-crm`, che chiede il consenso e mette `may_act` nel token. Così l'AS-IS non
  contiene niente dell'AI, e la delega nasce solo quando Luca apre l'assistente.
- **Chi vede l'audit?** Gli area manager, di persona. Gli agenti no, nemmeno a nome di un area manager.
- **Dove sono i dati?** Tutto sintetico, generato all'avvio (`demo-crm/api/app/seed.py`).

## Rigenerare le evidenze

```bash
docker compose --profile check run --rm evidence             # scrive evidence/run-<data>/
node scripts/capture-screens.js evidence/run-<data>/screens   # facoltativo, serve Playwright
```

`SUMMARY.md` elenca i controlli per atto, l'audit di demo-crm con il JWT di ogni chiamata e il log LiteLLM di
Luca. Le cartelle `run-*` non vengono committate; quella di esempio sì.
