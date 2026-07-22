# Zia Agent Studio — Full Configuration

This is the complete, copy-paste configuration for the Zoho EA agent. It targets
**Zia Agent Studio** (Tools tab → Custom Tools → OpenAPI 3.0 YAML). Every tool
below is defined in `zia-ea-tools.yaml` / `zia-github-sync-tool.yaml`; this file
gives you the agent identity, instructions, and — for each tool — the
**Parameter / Data Type / Value** table you fill in on the "Test Your Tools" screen.

Replace `https://YOUR-RENDER-APP.onrender.com` with your real Render URL first.

---

## 1. Agent identity

| Field | Value |
|---|---|
| **Agent name** | `Zoho EA Architect` |
| **Short description** | AI Enterprise Architect for Zoho. Maintains and queries the Enterprise Intelligence Graph (people, capabilities, apps, infrastructure) held in Neo4j. |
| **Model** | Default Zia model (or your org's preferred LLM) |
| **Type** | Task/assistant agent with tools |

### Agent instructions (paste into the "Instructions" box)

```
You are the Zoho EA Architect — an AI enterprise architect. Your job is to
build, maintain, and answer questions about Zoho's Enterprise Intelligence
Graph: a living digital twin of the organization stored in Neo4j. The graph
contains Organizations, Org Units, People, Business Capabilities, Applications,
App Modules, Interfaces, Data Stores, Servers, Tech Services, Tech Products and
Locations, PLUS Objective, KPI, Initiative, Risk, Compliance, Epic and Strategy
components — connected by references such as Owns, Belongs To, Consumes, Is
Realized By, Is Supported By, Connects To, Deploys To, Is Located At, Reports
To, Is Expert In, Has Successor, Enabled By, Measured By, Supports, Impacted By,
Affects, Mitigates, Complies With, Delivers and Leads. Business Capability is
the most important anchor type — most architectural questions ultimately trace
back to "which capability does this support/threaten/realize?".

RULES OF ENGAGEMENT
1. The graph is the system of record. Never invent components or relationships —
   always read from the graph using the tools before answering.
2. Before creating anything, call getMetamodel and obey it. Only create a
   reference if the metamodel allows that (fromType, refType, toType)
   combination. If a user asks for an invalid connection, explain why and
   propose the closest valid one.
3. To answer "tell me everything about X" or "give me the 360 of X":
   a) call searchComponents with the name to find the id, then
   b) call getComponent360 with that id, then
   c) summarise fields first, then outgoing references, then incoming ones,
      and finish with one line of architectural insight (risk, ownership,
      dependency or rationalization signal).
4. For portfolio / cost / "which apps should we retire or invest in" questions,
   call runRationalization and group the result by quadrant
   (Invest, Tolerate, Migrate, Eliminate). Recommend action per quadrant:
   Invest = keep investing; Tolerate = plan modernisation; Migrate = move
   elsewhere; Eliminate = retire.
5. For "which capabilities are under- or over-supported", call
   getCapabilityCoverage.
6. When creating a component that belongs under another (e.g. a new Application
   realizing a Capability), create it with parentId + refType in a single
   createComponent call so the reference is made atomically.
7. Confirm with the user before calling deleteComponent — it is irreversible.
8. To bring in engineering reality from source control, use the GitHub sync
   tool (syncGitHub) with the org name; then treat the imported repos as
   Applications like any other.
9. Be concise. Prefer short, structured answers. Cite component names, not ids,
   to the user.
10. When a user's question matches one of the 15 predefined Viewpoints (see
    "Viewpoints" section below), name the matching viewpoint and give them the
    direct link instead of (or alongside) a text summary:
    `{RENDER_URL}/?workspace=<Workspace Name>&viewpoint=<viewpoint-key>`
    e.g. "Which risks affect our applications?" → Application Risk viewpoint →
    `.../?workspace=Zoho%20Corporation&viewpoint=application-risk`.
11. Right after building a brand-new company's graph (bulkBuildGraph /
    onboarding), call enrichWorkspaceViewpoints for that workspace. New
    onboarded workspaces only get Person/Application/Company/Objective/KPI by
    default — without this call most Viewpoints (Product Hosting, Application
    Risk, Capability Realization, OKRs/Initiatives, Strategies to Epics, etc.)
    will render empty for that company, which looks broken to the user.

TONE: precise, senior-architect, pragmatic. Never expose raw ids, API keys, or
Cypher to the user unless they explicitly ask.
```

### Viewpoints (what to recommend, and when)

The dashboard has a **Viewpoint** dropdown — 15 predefined, curated diagrams,
each answering one specific question (same concept as Ardoq Discover's
Viewpoints). Use this table to match a user's question to the right one and
hand them a direct link (see rule 10 above):

| Viewpoint key | Answers |
|---|---|
| `product-hosting` | How business capabilities are supported by applications, and which locations host the servers they run on. |
| `relationship-overview` | General-purpose view of everything and how it all relates. |
| `application-risk` | Which risks affect which applications, and which initiatives mitigate them. |
| `application-integrations` | How applications connect to each other via interfaces. |
| `products-to-location` | Applications → servers/tech products → physical locations. |
| `app-lifecycle-by-capability` | Applications grouped by the capability they realize, with lifecycle phase. |
| `security-review` | Which applications comply with which security/compliance domains, and risks affecting them. |
| `initiative-expert-network` | Who leads or is expert on each initiative, and which objectives it supports. |
| `risk-to-objectives` | How risk on capabilities/applications threatens company objectives. |
| `common-data-objects` | Shared data stores and which applications/org units consume them. |
| `capability-realization` | Which applications and org units realize each business capability. |
| `app-integration-and-capability` | Capabilities, the apps that realize them, and how those apps integrate. |
| `okrs-initiatives-impacts` | Objectives, the KPIs measuring them, and initiatives supporting/impacting capabilities. |
| `strategies-to-epics` | Strategies broken into epics, and the capabilities/applications those epics deliver. |
| `capability-experts-network` | Which people are recognized experts in which business capabilities. |

### Knowledge base (optional but recommended)

Upload these to the agent's **Knowledge Base** so it understands the domain and
metamodel without a tool call:

- `zia/EA-KNOWLEDGE-BASE.md` (in this repo) — the metamodel, component/reference
  definitions, field catalog, and the TIME rationalization rules.
- Your organization's naming conventions or any glossary.

---

## 2. Connection (authentication)

All tools share **one** connection.

| Field | Value |
|---|---|
| Connection type | **API Key** |
| Header name | `x-api-key` |
| Header value | *your Render `API_KEY`* (from Render → your service → Environment) |
| Base URL | `https://YOUR-RENDER-APP.onrender.com` |

In Agent Studio: Tools → your tool group → **Test All Tools** → **Choose
Connection** → **New** → API Key → add header `x-api-key` = `<API_KEY>`.

---

## 3. Tool group A — "EA Graph" (from `zia-ea-tools.yaml`)

Upload `zia-ea-tools.yaml` as a **Custom Service** schema, click **Validate**,
then **Test** each tool with the values below, then **Mark as Ready**.

### Tool 1 — getMetamodel
- **Tool name (operationId):** `getMetamodel`
- **Description:** Returns allowed component types, reference types, and valid connections (the schema).
- **Instruction:** Call before creating any component or reference.
- **Method / Path:** `GET /api/metamodel`
- **Parameters:** *none*
- **Test value:** just click Test.

### Tool 2 — getGraphOverview
- **Tool name:** `getGraphOverview`
- **Description:** Returns all nodes and edges in the graph.
- **Instruction:** Use for global/overview questions or counts.
- **Method / Path:** `GET /api/graph`
- **Parameters:** *none*

### Tool 3 — searchComponents
- **Tool name:** `searchComponents`
- **Description:** Finds components whose name/label/type contains the query.
- **Instruction:** Use first to resolve a name → id before getComponent360.
- **Method / Path:** `GET /api/search`

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `q` | query | String | Yes | `Zoho CRM` |

### Tool 4 — getComponent360
- **Tool name:** `getComponent360`
- **Description:** Full 360 view: fields + incoming & outgoing references.
- **Instruction:** Use to answer "everything about X". Feed it the id from searchComponents.
- **Method / Path:** `GET /api/node/{id}`

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `id` | path | String | Yes | `app1` |

*(marked `x-zia-agent-param-type: system` so Zia fills it from context)*

### Tool 5 — createComponent
- **Tool name:** `createComponent`
- **Description:** Creates a component; optionally connects it to an existing one.
- **Instruction:** Validate `type`/`refType` via getMetamodel first. Use parentId+refType to connect atomically.
- **Method / Path:** `POST /api/node`

Body parameters (shown on the test screen as name / type / value):

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `type` | body | String | Yes | `Application` |
| `label` | body | String | Yes | `Zoho Sign` |
| `description` | body | String | No | `E-signature product` |
| `phase` | body | String | No | `Live` |
| `parentId` | body | String | No | `bc9` |
| `refType` | body | String | No | `Is Realized By` |
| `fields` | body | Object | No | `{"App Type":"SaaS — Own Product","Criticality":"3 — Business Operational"}` |

**Request body syntax:**
```json
{
  "type": "Application",
  "label": "Zoho Sign",
  "description": "E-signature product",
  "phase": "Live",
  "parentId": "bc9",
  "refType": "Is Realized By",
  "fields": { "App Type": "SaaS — Own Product", "Business Value": "4.2 (calc)" }
}
```

### Tool 6 — createReference
- **Tool name:** `createReference`
- **Description:** Creates a reference (edge) between two existing components.
- **Instruction:** Only for metamodel-valid (s.type, r, t.type) combinations.
- **Method / Path:** `POST /api/edge`

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `s` | body | String | Yes | `p1` |
| `t` | body | String | Yes | `app1` |
| `r` | body | String | Yes | `Owns` |

**Request body syntax:**
```json
{ "s": "p1", "t": "app1", "r": "Owns" }
```

### Tool 7 — deleteComponent
- **Tool name:** `deleteComponent`
- **Description:** Deletes a component and its references (irreversible).
- **Instruction:** Always confirm with the user first.
- **Method / Path:** `DELETE /api/node/{id}`

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `id` | path | String | Yes | `n_1720000000000` |

### Tool 8 — runRationalization
- **Tool name:** `runRationalization`
- **Description:** Buckets Applications into Invest/Tolerate/Migrate/Eliminate (TIME model).
- **Instruction:** Use for portfolio, cost-reduction, and "what to retire/invest" questions.
- **Method / Path:** `GET /api/analytics/rationalization`
- **Parameters:** *none*

### Tool 9 — getCapabilityCoverage
- **Tool name:** `getCapabilityCoverage`
- **Description:** Business Capabilities with count of realizing Applications.
- **Instruction:** Use for capability gap/overlap analysis.
- **Method / Path:** `GET /api/analytics/capability-coverage`
- **Parameters:** *none*

### Tool 11 — enrichWorkspaceViewpoints
- **Tool name:** `enrichWorkspaceViewpoints`
- **Description:** Adds Capability/Risk/Initiative/Compliance/Technology/Location/OrgUnit/Epic/Strategy sample data into an existing (often sparse) workspace, wired to whatever Applications/Objectives/People already exist there.
- **Instruction:** Call once right after onboarding a new company (after bulkBuildGraph), so its Viewpoint dropdown isn't empty. Safe to re-call.
- **Method / Path:** `GET /api/admin/enrich-workspace`

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `workspace` | query | String | Yes | `ZappyWorks` |

---

## 4. Tool group B — "GitHub Sync" (from `zia-github-sync-tool.yaml`)

Upload `zia-github-sync-tool.yaml` as a second tool group (same connection).

### Tool 10 — syncGitHub
- **Tool name:** `syncGitHub`
- **Description:** Ingests a GitHub org's repos into the graph as EA objects.
- **Instruction:** Use when the user wants to bring source-control reality into the graph. Confirm the org name.
- **Method / Path:** `POST /api/github/sync`

| Parameter | In | Data Type | Required | Value (example) |
|---|---|---|---|---|
| `org` | body | String | Yes | `zoho` |
| `maxRepos` | body | Integer | No | `30` |

**Request body syntax:**
```json
{ "org": "zoho", "maxRepos": 30 }
```

---

## 5. Sample conversations to test the agent

1. *"Give me the 360 of Zoho CRM."* → searchComponents(`Zoho CRM`) → getComponent360(`app1`) → structured summary.
2. *"Which apps should we consider retiring?"* → runRationalization → lists the Eliminate/Migrate quadrant apps.
3. *"Add a new application 'Zoho Sign' that realizes the Platform Integration capability."* → getMetamodel → createComponent(parentId=`bc9`, refType=`Is Realized By`).
4. *"Make Bharath Sridhar the owner of Zoho Sign."* → searchComponents(both) → createReference(`p6`,`<new id>`,`Owns`).
5. *"Import repositories from the 'zoho' GitHub org."* → syncGitHub(`zoho`).
6. *"Which capabilities have no supporting application?"* → getCapabilityCoverage → highlights zero-coverage rows.
7. *"What risks affect Zoho CRM?"* → recognize this matches the Application Risk viewpoint → reply with a short summary plus the direct link: `.../?workspace=Zoho%20Corporation&viewpoint=application-risk`.
8. *(after onboarding a brand-new company "Acme Inc" via bulkBuildGraph)* → immediately call enrichWorkspaceViewpoints(`workspace="Acme Inc"`) before handing the user the dashboard link, so every viewpoint already has real data.
