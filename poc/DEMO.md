# Copione della demo · Wave 0

Durata: circa 15 minuti. Un solo schermo con il browser su **http://localhost:3000** e un terminale
nella cartella `poc/`. Ogni atto indica cosa fare, cosa vede il pubblico e la prova che resta.
Le immagini sono in [`evidence/sample-2026-11-22/screens/`](evidence/sample-2026-11-22/screens/), da
una prova completa del 22 novembre 2026.

## Prima di iniziare (5 minuti prima)

```bash
cd poc
docker compose down -v && docker compose up -d --build     # parte pulito
docker compose --profile check run --rm check               # deve finire con "Demo: 13/13 checks passed"
docker compose down -v && docker compose up -d              # di nuovo pulito: la prova ha scritto note e promemoria
```

- `/etc/hosts` contiene `127.0.0.1 sso.demo.local`.
- Con un modello: in `.env` `LLM_MODEL=gpt` e `OPENAI_API_KEY` (oppure `claude-sonnet` e `ANTHROPIC_API_KEY`).
  Senza, l'assistente lavora in *modalità scripted*: i flussi di identità e permessi sono identici.
- Schede aperte: la UI su `localhost:3000`, la UI admin di LiteLLM su `localhost:4000/ui`
  (`admin` / master key), la console Keycloak su `sso.demo.local:8080` (facoltativa).

## Il messaggio in una frase

Ogni agente ha un'identità sua in Keycloak. Quando lavora per una persona porta con sé *chi è la persona* e
*chi è l'agente*, e tre livelli indipendenti (Keycloak, LiteLLM, l'applicazione) decidono cosa può fare.

---

## Atto 1 · Luca entra e vede solo il suo territorio

**Fai:** *Sign in*, utente `luca` / `luca`.

**Il pubblico vede:** Keycloak chiede *"Allow agent-crm-assistant to act on your behalf?"*. Clicca **Yes**.
Nella UI compaiono solo i clienti NORTH; in alto *area-manager, rep* e il badge **assistant allowed**.

**Da dire:** il consenso è esplicito e registrato. Il token di Luca ora contiene `may_act`: solo
quell'agente può agire per lui, e solo per lui. Il territorio viene dal token, non da una tabella dell'app.

**Prova:** `act1-consent.png`, `act1-territory.png`.

## Atto 2 · L'assistente prepara la visita e scrive una bozza

**Fai:** apri il primo cliente, clicca **Assistant: prepare visit and draft a note**.

**Il pubblico vede:** sotto i pulsanti la traccia: *Delegated token: sub = luca, act = agent-crm-assistant,
roles = rep*, i tool chiamati, l'id di correlazione. A destra la nota con il badge
*proposed by agent-crm-assistant for luca* e lo stato **draft**. Luca clicca **Confirm**: diventa **final**.

**Da dire:** l'agente ha scambiato il token di Luca con uno nuovo (token exchange, RFC 8693): la persona
resta il soggetto, l'agente è l'attore, i ruoli sono ridotti a `rep`. L'app sa sempre che la nota l'ha
proposta un agente. Solo una persona può renderla definitiva.

**Prova:** `act2-draft-note.png`; in `evidence/.../demo-crm-notes-luca.json` i campi `created_by` e `via_agent`.

## Atto 3 · Il report del team: Luca può, l'assistente no

**Fai:** clicca **Assistant: team report**. Con un modello puoi anche chiederlo in chat.

**Il pubblico vede:** `get_team_report` **refused by demo-crm**.

**Da dire:** Luca è area manager, ma l'assistente riceve solo `rep`. È un limite dell'assistente, non di
Luca: lui il report lo vede dalla sua app. Il privilegio minimo si decide in Keycloak, non nel prompt.

**Prova:** `act3-team-report-refused.png`.

## Atto 4 · L'agente autonomo lavora di notte

**Fai:** clicca **Run agent-dq now** (fa le veci dello scheduler notturno).

**Il pubblico vede:** promemoria con il badge **agent-dq (autonomous)** per le visite senza esito.

**Da dire:** nessuna persona dietro: agent-dq usa la sua identità (service account, ruolo `dq-agent`) e si
autentica con una chiave privata, senza segreti condivisi. Può creare promemoria, non note.

**Prova:** `act4-agent-dq-reminders.png`, `evidence/.../demo-crm-reminders-by-agent-dq.json`.

## Atto 5 · Il gateway ferma ciò che l'agente non deve fare

**Fai:** clicca **Assistant: try a tool it doesn't have**, poi **Assistant: try a final note**.

**Il pubblico vede:** `create_reminder` **refused by gateway**; poi `draft_visit_note`
**refused by gateway** con *Violated guardrail policy*.

**Da dire:** LiteLLM conosce la lista di tool di ogni agente e la regola "gli agenti scrivono solo bozze".
La richiesta non arriva nemmeno all'app.

**Prova:** `act5a-tool-not-allowed.png`, `act5b-final-note-guardrail.png`; nel log LiteLLM le righe `failure`.

## Atto 6 · E se l'agente aggira il gateway?

**Fai:** clicca **Assistant: bypass the gateway**.

**Il pubblico vede:** la nota "Final note sent straight to the API" compare, ma come **draft**.

**Da dire:** anche chiamando l'API direttamente, l'app riconosce l'agente dal token e salva solo bozze.
Due livelli indipendenti: se uno cede, l'altro tiene.

**Prova:** `act6-direct-call-stored-as-draft.png`.

## Atto 7 · Kill switch e audit

**Fai:** nel terminale

```bash
./scripts/kill-switch.sh block
```

poi clicca un pulsante dell'assistente: la UI mostra *gateway refused agent-crm-assistant*. Ripristina con

```bash
./scripts/kill-switch.sh unblock
```

Infine apri la UI admin di LiteLLM, **Logs**: ogni chiamata ha l'utente (il `sub` di Luca) e il team
(l'agente), con lo stato.

**Da dire:** un comando ferma l'agente per tutti, subito, senza toccare le persone. Il log risponde a
"chi ha fatto cosa, per conto di chi".

**Prova:** tabella *LiteLLM log* in [`evidence/sample-2026-11-22/SUMMARY.md`](evidence/sample-2026-11-22/SUMMARY.md).

**Limite da dichiarare:** il kill switch agisce sul gateway. Una chiamata diretta all'app (atto 6) passa
ancora, come bozza. In produzione le app vanno rese raggiungibili solo tramite gateway/MCP, oppure si
disabilita anche il client dell'agente in Keycloak.

---

## Domande probabili

- **Serve LiteLLM Enterprise?** No. La verifica dei token Keycloak è un hook `custom_auth` della versione
  open source (`litellm/keycloak_auth.py`).
- **E con un altro modello?** Cambia `LLM_MODEL`. La chiave resta in LiteLLM; l'agente non la vede mai.
- **Dove sono i dati?** Tutto sintetico, generato all'avvio (`demo-crm/api/app/seed.py`).

## Rigenerare le evidenze

```bash
docker compose --profile check run --rm evidence             # scrive evidence/run-<data>/
node scripts/capture-screens.js evidence/run-<data>/screens   # facoltativo, serve Playwright
```

`SUMMARY.md` elenca i controlli per atto e il log LiteLLM delle chiamate di Luca. Le cartelle `run-*`
non vengono committate; quella di esempio sì.
