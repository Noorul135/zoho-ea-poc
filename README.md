# Zoho EA POC — Enterprise Intelligence Graph

A working proof-of-concept of an Ardoq-style Enterprise Architecture platform for
Zoho. **Neo4j is the system of record**; a Node.js API on Render serves both a
REST API and the interactive graph dashboard; **Zia agents** call that API as
tools; and GitHub is used both to auto-deploy (on push) and — optionally — as a
**data source** ingested into the graph.

```
                 ┌────────────────────────┐
   Zia Agent ───▶│                        │
   (tools)       │   Node.js API (Render) │──────▶  Neo4j Aura
   Dashboard ───▶│   server.js  + db.js   │◀──────  (the graph =
   Browser       │                        │          system of record)
                 └────────────────────────┘
                        ▲          ▲
              GitHub push│          │GitHub REST (github-sync.js)
              auto-deploy│          │ingests repos as EA objects
```

## Choose your backend — Python OR Node (same API)

This repo ships **two interchangeable backends** that expose the **identical**
REST API. Pick one:

- **Python / FastAPI** → `main.py` (+ `requirements.txt`, `seed.py`,
  `github_sync.py`). Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
  **Use this if your Render service runs uvicorn / asks for `main.py`.**
- **Node / Express** → `server.js` (+ `package.json`, `db.js`, `scripts/`).
  Start command: `npm start`.

The dashboard, Cypher schema, seed data, and Zia tool configs are shared and
work with either backend. `render.yaml` is currently set to the **Python**
option. Don't run both at once.

## Viewpoints (new)

The dashboard's topbar now has a **Viewpoint** dropdown (next to the existing
View dropdown), modeled on Ardoq Discover's Viewpoints concept: each option is
a predefined "chain of triples" — a curated set of component types (Business
Capability, Application, Server, Risk, Objective, Initiative, Epic, Strategy,
etc.) that answers one specific question, e.g. *Product Hosting*, *Application
Risk*, *OKRs, Initiatives and Impacts*, *Strategies to Epics*. Picking one
filters the graph down to just those component types (and the references
that naturally connect them) and switches to a fitting view style.

- Config lives client-side in `public/index.html` → `VIEWPOINTS` object +
  `applyViewpoint()`. Every viewpoint renders into the real Cytoscape
  node-link canvas (not the text/card-based Dependency Map, Tree, Swimlanes
  or Capability Map views — those never draw connecting lines, so a
  viewpoint routed to one of them always looked empty/disconnected even with
  good data). Each viewpoint also picks a fitting layout (`tree-td`, `cose`,
  `concentric`, or `clusters`) — Business Capability is treated as the
  highest-priority root for hierarchical layouts, since it's the anchor most
  of these viewpoints are built around.
- Deep link directly into a viewpoint with `?workspace=<ws>&viewpoint=<key>`,
  e.g. `/?workspace=Zoho%20Corporation&viewpoint=application-risk`.
- New component/reference types the viewpoints need (Objective, KPI,
  Initiative, Risk, Compliance, Epic, Strategy) are defined in
  **`cypher/03-viewpoints-metamodel.cypher`** — run it once in the Neo4j
  console, after `01-constraints.cypher` and `02-metamodel.cypher`.
- The Zia agent config (`zia/ZIA-AGENT-CONFIG.md`, `zia/zia-ea-tools.yaml`,
  `zia/EA-KNOWLEDGE-BASE.md`) now knows about all 15 viewpoints (so it can
  recommend and link to the right one) and about `enrichWorkspaceViewpoints`,
  which it should call right after onboarding any new company.
- Sample instances of those new types (wired into the real Zoho Corporation
  graph — e.g. `Objective → Enabled By → Business Capability`,
  `Risk → Affects → Application`) were added to `data.json`. Re-run the seed
  loader (`GET/POST /api/admin/seed`, or `python seed.py`) to load them.

## Enriching an existing sparse workspace (e.g. ZappyWorks)

Workspaces built live through the Zia onboarding chat (rather than the
`data.json` seed) often only end up with a handful of component types
(Person, Application, Company, Objective, KPI) — enough for a couple of
viewpoints but not most of them. Either option below adds the missing types
(Capability, Risk, Initiative, Compliance, Technology, Location, OrgUnit,
Epic, Strategy) into an already-live workspace, wired to whatever
Applications/Objectives/People already exist there (no need to know their
exact labels — both look them up at runtime).

**Option 1 — no local setup (recommended).** Once this repo is deployed on
Render, just open this URL once (replace with your own values):

```
https://<your-app>.onrender.com/api/admin/enrich-workspace?workspace=ZappyWorks&x-api-key=YOUR_API_KEY
```

That's it — no install, no `.env`, nothing to run on your machine. It calls
the new `/api/admin/enrich-workspace` route in `main.py`, which runs the same
enrichment directly against your live Neo4j from the server. Swap `ZappyWorks`
for any other workspace name (case-sensitive — must match the dashboard's
workspace selector exactly), and your existing `API_KEY` is whatever you set
in Render → Environment (the same one already used by `/api/admin/seed`).

**Option 2 — run it locally**, if you'd rather not expose the admin route or
want to inspect what it does first. From the root of this repo (the folder
containing `requirements.txt`, `main.py`, `enrich_workspace.py` — i.e. wherever
you unzipped/cloned this project):

```
pip install -r requirements.txt
cp .env.example .env          # fill in your Aura NEO4J_URI / NEO4J_PASSWORD
python enrich_workspace.py "ZappyWorks"
python enrich_workspace.py "ZappyWorks" --wipe   # removes prior enrichment first, then re-adds
```

Either way, reload `…/?workspace=ZappyWorks` afterwards — Product Hosting,
Application Risk, Capability Realization, OKRs/Initiatives, Strategies to
Epics, etc. should now render real, non-empty graphs for that workspace too.

## What's in this repo

| Path | What it is |
|---|---|
| `public/index.html` | The dashboard (your original file, now API-backed). |
| **`main.py`** | **Python/FastAPI API + dashboard host (uvicorn).** |
| **`requirements.txt`** | **Python dependencies.** |
| **`seed.py`** | **Python seed loader (reads `data.json`).** |
| **`github_sync.py`** | **Python GitHub → graph ingestion.** |
| **`data.json`** | **Seed dataset used by the Python loader.** |
| `server.js` | Node/Express API + dashboard host (alternative to main.py). |
| `db.js` | Neo4j driver + shared helpers (Node). |
| `cypher/01-constraints.cypher` | Unique-id constraints + indexes. |
| `cypher/02-metamodel.cypher` | The metamodel (component types, reference types, allowed connections). |
| `scripts/data.js` | The full Zoho seed dataset (65 components, 115 references). |
| `scripts/load-seed.js` | Loads the seed into Neo4j. |
| `scripts/github-sync.js` | **Separate** GitHub → graph ingestion tool. |
| `zia/zia-ea-tools.yaml` | OpenAPI 3.0 custom tools for the Zia agent. |
| `zia/zia-github-sync-tool.yaml` | OpenAPI 3.0 GitHub-sync tool for Zia. |
| `zia/ZIA-AGENT-CONFIG.md` | Agent name, instructions, and each tool's Parameter/Type/Value. |
| `zia/EA-KNOWLEDGE-BASE.md` | Knowledge base to upload to the agent. |
| `render.yaml` | Render Blueprint (auto-deploy config). |
| `.env.example` | Environment variable template. |

You can do the whole thing in well under a day. Order matters — follow A → E.

---

## Part A — Neo4j Aura (the graph / system of record)  ~10 min

1. Go to **https://neo4j.com/product/auradb/** → **Start free**. Sign in.
2. Click **New Instance → AuraDB Free**. Pick a region, name it `zoho-ea`.
3. When it creates, a **credentials file downloads** (or is shown once). It
   contains:
   - `NEO4J_URI` — looks like `neo4j+s://xxxxxxxx.databases.neo4j.io`
   - `NEO4J_USERNAME` — `neo4j`
   - `NEO4J_PASSWORD` — a generated password
   **Save these now — the password is shown only once.**
4. Open the instance → **Query** (the console). Paste and run, in order:
   - the contents of `cypher/01-constraints.cypher`
   - the contents of `cypher/02-metamodel.cypher`
   (You'll seed the actual data in Part C with one command.)

> AuraDB Free pauses after a few days idle — just resume it from the console.

---

## Part B — GitHub (host the repo)  ~5 min

1. Create a new **empty** GitHub repo, e.g. `zoho-ea-poc`.
2. From this folder:
   ```bash
   git init
   git add .
   git commit -m "Zoho EA POC"
   git branch -M main
   git remote add origin https://github.com/<you>/zoho-ea-poc.git
   git push -u origin main
   ```
   `.gitignore` already excludes `.env` and `node_modules/`.

---

## Part C — Load the seed data into Neo4j  ~3 min

Do this locally once (you can also re-run any time):

```bash
cp .env.example .env          # then edit .env with your Aura URI/password
```

**Python:**
```bash
pip install -r requirements.txt
python seed.py                # loads 65 components + 115 references
# python seed.py --wipe       # (optional) wipe + reload from scratch
```

**Node (alternative):**
```bash
npm install
npm run seed                  # npm run seed:wipe to wipe + reload
```

You should see `Done. Graph now holds: 65 components, 115 references`.

---

## Part D — Render (deploy the API + dashboard)  ~10 min

1. Go to **https://render.com** → sign in with GitHub.
2. **New + → Blueprint** → pick your `zoho-ea-poc` repo. Render reads
   `render.yaml` and proposes a free web service.
3. Set the secret environment variables when prompted (or under the service →
   **Environment**):
   - `NEO4J_URI` = your Aura URI
   - `NEO4J_PASSWORD` = your Aura password
   - (`NEO4J_USER` defaults to `neo4j`; `API_KEY` is auto-generated — **copy it**;
     `GITHUB_TOKEN` optional)
4. Click **Apply / Deploy**. `render.yaml` deploys the **Python** backend:
   build `pip install -r requirements.txt`, start
   `uvicorn main:app --host 0.0.0.0 --port $PORT`.
   *If you configured the service by hand instead of Blueprint, set exactly
   those Build and Start commands and Runtime = Python.*
5. When live, open `https://<your-app>.onrender.com` → the dashboard loads
   **live from Neo4j** (the hint bar shows "● Live"). Health check:
   `https://<your-app>.onrender.com/api/health` → `{"status":"ok"}`.

> Free tier sleeps after 15 min idle; the first request then takes ~30–60s to
> wake. That's expected for a POC.

Every `git push` to `main` now auto-redeploys.

---

## Part E — Zia Agent Studio (the AI agent)  ~15 min

Full detail (agent instructions + every tool's Parameter/Type/Value) is in
**`zia/ZIA-AGENT-CONFIG.md`**. Short version:

1. In `zia/zia-ea-tools.yaml` and `zia/zia-github-sync-tool.yaml`, set the
   `servers.url` to your Render URL.
2. Zia Agent Studio → **Agents → Create** → name it `Zoho EA Architect`,
   paste the instructions from `ZIA-AGENT-CONFIG.md`.
3. **Knowledge Base** → upload `zia/EA-KNOWLEDGE-BASE.md`.
4. **Tools → + New Tool Group** → name `EA Graph` → **Add Schema → Custom
   Service** → upload `zia-ea-tools.yaml` → **Validate**.
5. **Test All Tools** → **Choose Connection → New → API Key**: header
   `x-api-key` = your Render `API_KEY`. Fill test values from the config doc →
   **Test** → **Mark as Ready → Save**.
6. Repeat 4–5 for `zia-github-sync-tool.yaml` (tool group `GitHub Sync`).
7. Attach both tool groups to the agent. Try: *"Give me the 360 of Zoho CRM."*

---

## Part F (optional) — Ingest GitHub as EA data

Bring repos/owners into the graph as Applications/Persons:

```bash
# locally — Python
GITHUB_TOKEN=<token> python github_sync.py zoho 30
# locally — Node (alternative)
GITHUB_TOKEN=<token> node scripts/github-sync.js zoho 30
```
or via the API / Zia tool:
```bash
curl -X POST https://<your-app>.onrender.com/api/github/sync \
  -H "x-api-key: <API_KEY>" -H "Content-Type: application/json" \
  -d '{"org":"zoho","maxRepos":30}'
```
Reload the dashboard — the new repos appear as Applications hosted on a "GitHub"
Tech Service and owned by imported Persons.

---

## Part G — Onboard a new company via the Zia chat

A second agent (**EA Onboarding Architect**, see `zia/ZIA-AGENT-CONFIG.md` Part 2)
builds a brand-new customer's graph from a short chat:

1. It knows the user's name, email, company name and URL from sign-up.
2. It calls `enrichCompany(url)` → the backend fetches the company's website
   (home/about/products) and returns text the agent uses to infer the segment,
   products, and structure.
3. It asks a few questions (employees, capabilities, apps, KPIs, infra).
4. It calls `bulkBuildGraph({workspace:"<Company>", components, references})`
   to create the whole graph under that company's **workspace**.
5. It returns the live link `…/?workspace=<Company>`.

Each company lives in its own **workspace**; the dashboard has a workspace
selector (top bar) to switch between them. Upload `zia/zia-onboarding-tools.yaml`
as a third tool group (same API-key connection).

## Using the dashboard

**Views** (the "View" dropdown, Ardoq-style, all over live Neo4j data):

- *Graph* — Block / Graph — Dependency Map — Component Tree — Swimlanes — Dependency Wheel
- *Lists* — Pages — Table (sortable) — Reference Table — Component Matrix (type × lifecycle) — Dependency Matrix (adjacency) — Relationships
- *Analytics* — Capability Map — Treemap — Bubble Chart (BV × TF, size = criticality) — Spider Chart — Tagscape

Other controls:

- **Click any node or chip** → 360 panel (fields + tags + incoming/outgoing references + generated narrative). Works in every view.
- **Layouts** dropdown (Graph view only) → Force / Tree / Concentric / Circle / Grid.
- **Graph traversal** (left sidebar) → pick a start component + depth → shows only the reachable sub-graph.
- **Tags** (left sidebar) → click a tag to filter; add tags via a component's **✎ Edit fields & tags**.
- **⚡ Rationalize** → recolours applications by TIME quadrant (Invest / Tolerate / Migrate / Eliminate).
- **+ Add node** → create a component with custom fields + tags (persisted to Neo4j). Delete + edit persist too.
- **⚙ Metamodel** → add/remove component types, reference types, and allowed connections (persisted to Neo4j).
- **Search** filters the current view.

## API reference (quick)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health` | – | Liveness + Neo4j check |
| GET | `/api/graph` | – | All nodes + edges |
| GET | `/api/metamodel` | – | Types + allowed connections |
| GET | `/api/search?q=` | – | Search components |
| GET | `/api/node/:id` | – | 360 view of a component |
| POST | `/api/node` | key | Create component (+ optional edge) |
| POST | `/api/edge` | key | Create a reference |
| DELETE | `/api/node/:id` | key | Delete component + edges |
| DELETE | `/api/edge/:id` | key | Delete a reference |
| GET | `/api/analytics/rationalization` | – | TIME buckets for apps |
| GET | `/api/analytics/capability-coverage` | – | Apps per capability |
| POST | `/api/github/sync` | key | Ingest a GitHub org |

`key` = send header `x-api-key: <API_KEY>`.

## Local development

```bash
npm install
cp .env.example .env      # fill in Aura creds + API_KEY
npm run seed              # once
npm start                 # http://localhost:3000
```

## Security note (POC)

For simplicity the dashboard receives the `API_KEY` injected at page-serve time,
so browser writes work. Anyone who can open the page can read the key from page
source. That is fine for a POC/demo. For production: move writes behind
authenticated user sessions, keep the key server-side only, and restrict CORS.

## Troubleshooting

- **Dashboard says "○ Offline demo data"** → the API/Neo4j isn't reachable.
  Check `/api/health`, the Render env vars, and that Aura is running (not paused).
- **`Missing NEO4J_URI / NEO4J_PASSWORD`** → env vars not set (Render Environment
  or local `.env`).
- **401 on writes** → the `x-api-key` header doesn't match Render's `API_KEY`.
- **GitHub 403 / rate limit** → set `GITHUB_TOKEN`.
- **Relationship type errors** → only use the reference names from the metamodel.
