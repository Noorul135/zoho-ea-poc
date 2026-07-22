# Enterprise Architecture Knowledge Base (for the Zia agent)

Upload this to the Zia agent's Knowledge Base. It teaches the agent the
metamodel, definitions, field catalog and analysis rules so it reasons like an
enterprise architect. It mirrors the Ardoq foundation metamodel.

## What the graph is

An **Enterprise Intelligence Graph** — a living digital twin of the
organization connecting people, business capabilities, applications, data,
and infrastructure. It replaces static diagrams with an always-current,
queryable graph. It is the **system of record**.

## Component types (nodes)

| Type | Category | Meaning |
|---|---|---|
| Organization | Organization | Top-level legal entity (usually one). |
| Org Unit | Organization | Department, team, division (hierarchical). |
| Person | Organization | An individual (employee, owner, expert). |
| Business Capability | Business | What the business does (strategic ability). |
| Application | Application | A deployed software solution / product. |
| App Module | Application | A functional module inside an Application. |
| Interface | Application | An API / integration point. |
| Data Store | Data | A database / data lake / warehouse. |
| Server | Technology | A host / data centre / node. |
| Tech Service | Technology | A platform service (CDN, cloud storage, GitHub). |
| Tech Product | Technology | Software/tech product (OS, DB engine, k8s). |
| Location | Other | A physical place (office, data-centre site). |

## Reference types (edges) and their meaning

| Reference | Meaning |
|---|---|
| Owns | Responsibility / ownership (Person → App / Org Unit / Server / Interface). |
| Belongs To | Membership / part-of (Person → Org Unit; Org Unit → Organization). |
| Reports To | Reporting line (Person → Person). |
| Is Expert In | Knowledge / specialization (Person → Capability / App / Interface). |
| Consumes | Value consumption / internal use (Org Unit → Application). |
| Is Realized By | Implementation (Business Capability → Application / Org Unit). |
| Is Supported By | Runs-on / hosting (Application/Module/Data Store → Server / Tech Service). |
| Connects To | Integration (Application/Module ↔ Interface). |
| Deploys To | Deployment (Tech Product → Server / Tech Service). |
| Is Located At | Physical placement (Server / Tech Service → Location). |
| Has Successor | Time-based replacement (Application → Application). |
| Child Of | Hierarchy (Business Capability → Business Capability). |
| Module Of | Composition (App Module / Data Store → Application). |

## Allowed connections (the metamodel — enforce these)

Only these (from → reference → to) combinations are valid. The API's
`/api/metamodel` returns the authoritative list; this is a readable copy:

- Org Unit — Belongs To → Organization
- Person — Belongs To → Org Unit
- Person — Reports To → Person
- Person — Owns → Org Unit / Application / Interface / Server
- Person — Is Expert In → Business Capability / Application / Interface
- Org Unit — Consumes → Application
- Org Unit — Owns → Server
- Business Capability — Is Realized By → Application / Org Unit
- Business Capability — Child Of → Business Capability
- Application — Is Supported By → Server / Tech Service
- Application — Connects To → Interface
- Application — Has Successor → Application
- App Module — Module Of → Application
- App Module — Connects To → Interface
- App Module — Is Supported By → Server
- Interface — Connects To → Application
- Data Store — Module Of → Application
- Data Store — Is Supported By → Server
- Server — Is Located At → Location
- Server — Is Supported By → Tech Service
- Tech Service — Is Located At → Location
- Tech Product — Deploys To → Server / Tech Service

## Viewpoint-supporting types (added for the dashboard's Viewpoint dropdown)

The dashboard now has a **Viewpoint** selector (Ardoq Discover-style curated
diagrams — see `cypher/03-viewpoints-metamodel.cypher` for the authoritative
schema). It introduces seven more component types and their references,
additive to everything above:

| Type | Meaning |
|---|---|
| Objective | A strategic goal ("Accelerate AI-Native Product Experience"). |
| KPI | A measurable metric tracking an Objective. |
| Initiative | A funded program of work supporting an Objective. |
| Risk | A threat to an Application or Business Capability. |
| Compliance | A regulatory/security domain an Application must comply with (GDPR, SOX, ISO 27001...). |
| Strategy | A high-level strategic direction, broken into Epics. |
| Epic | A body of work delivering a Strategy, realized against Capabilities/Applications. |

| Reference | Meaning |
|---|---|
| Enabled By | Objective → Business Capability (the capability that enables the objective). |
| Measured By | Objective → KPI. |
| Supports | Initiative → Objective. |
| Impacted By | Business Capability → Initiative. |
| Affects | Risk → Application / Business Capability. |
| Mitigates | Initiative → Risk. |
| Complies With | Application → Compliance. |
| Delivers | Strategy → Epic; Epic → Business Capability / Application. |
| Leads | Person → Initiative. |

Every new onboarded workspace should get this data via the
`enrichWorkspaceViewpoints` tool right after it's built — otherwise the
Viewpoint dropdown will look empty for that company even though the base
Application/Objective/Person data is fine.

## Field catalog (common fields per type)

- **All:** Name (required), Description.
- **Person:** Role, Contact Email, Status.
- **Business Capability:** Maturity, Market Diff(erentiation), Lifecycle Phase,
  Component Level, Complexity.
- **Application:** App Type, Lifecycle Phase, Service Level, Strategic Rating,
  Business Value, Technical Fit, Criticality, Ownership State.
- **Server:** Server Hosting, Server Type, Network Zone, Deploy Env, Lifecycle Phase.
- **Interface:** Protocol, Request Type, Lifecycle Phase.
- **Tech Product:** Vendor, Version, Lifecycle Phase.
- **Location:** Address, Type.

Custom fields (text/number/date/list/URL) may be added to any type.

## Analysis rules

**TIME / rationalization model** — bucket each Application by Business Value (BV)
and Technical Fit (TF), each on a 1–5 scale:

| BV | TF | Quadrant | Recommended action |
|---|---|---|---|
| ≥ 4 | ≥ 4 | **Invest** | Strong value + good fit — keep investing. |
| ≥ 4 | < 4 | **Tolerate** | Valuable but poor fit — plan modernisation. |
| < 4 | ≥ 4 | **Migrate** | Low value, good fit — migrate function elsewhere. |
| < 4 | < 4 | **Eliminate** | Retire this asset. |

**Risk signals to surface:** capabilities with no realizing Application
(coverage gap); Applications on a single Server/DC (concentration risk);
single-owner key-person dependency; apps with a declared `Has Successor`
(planned replacement).
