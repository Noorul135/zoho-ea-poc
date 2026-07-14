# =====================================================================
# main.py  —  Zoho EA POC API + dashboard host (Python / FastAPI)
#
# This is the PYTHON equivalent of server.js. Use this if your Render
# service runs uvicorn (Start command: uvicorn main:app --host 0.0.0.0 --port $PORT).
# It exposes the EXACT SAME REST API, so the dashboard and all Zia tools
# work unchanged.
#
# Env vars (see .env.example):
#   NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, API_KEY, GITHUB_TOKEN (optional)
# =====================================================================
import os, json, time, re, sys, logging, traceback
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

# ---- logging (streams to Render Logs; flush immediately) ------------
logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("zoho-ea")

# ---- config ---------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
API_KEY = os.getenv("API_KEY", "")

app = FastAPI(title="Zoho EA POC")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup():
    log.info("Zoho EA API starting — NEO4J_URI set=%s, API_KEY set=%s",
             bool(NEO4J_URI), bool(API_KEY))
    if not NEO4J_URI or not NEO4J_PASSWORD:
        log.error("NEO4J_URI / NEO4J_PASSWORD are NOT set — DB calls will fail. "
                  "Set them in Render -> Environment.")

# Log full tracebacks for any unhandled error so they show up in Render Logs.
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.error("Unhandled error on %s %s\n%s", request.method, request.url.path,
              traceback.format_exc())
    return JSONResponse(status_code=500, content={"error": str(exc)})

# Collapse accidental double slashes (e.g. //api/metamodel -> /api/metamodel)
# so a trailing-slash base URL in Zia still routes correctly.
@app.middleware("http")
async def _normalize_path(request: Request, call_next):
    p = request.scope.get("path", "")
    if "//" in p:
        request.scope["path"] = re.sub(r"/{2,}", "/", p)
    return await call_next(request)

_driver = None
def driver():
    global _driver
    if _driver is None:
        if not NEO4J_URI or not NEO4J_PASSWORD:
            raise RuntimeError("Missing NEO4J_URI / NEO4J_PASSWORD environment variables.")
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver

def run(cypher, params=None, write=False):
    params = params or {}
    with driver().session() as s:
        if write:
            return [r.data() for r in s.execute_write(lambda tx: list(tx.run(cypher, **params)))]
        return [r.data() for r in s.execute_read(lambda tx: list(tx.run(cypher, **params)))]

# ---- reference-type -> Neo4j relationship-type mapping --------------
REF_TO_REL = {
    "Owns": "OWNS", "Is Expert In": "IS_EXPERT_IN", "Belongs To": "BELONGS_TO",
    "Reports To": "REPORTS_TO", "Consumes": "CONSUMES", "Is Realized By": "IS_REALIZED_BY",
    "Is Supported By": "IS_SUPPORTED_BY", "Connects To": "CONNECTS_TO",
    "Has Successor": "HAS_SUCCESSOR", "Deploys To": "DEPLOYS_TO",
    "Is Located At": "IS_LOCATED_AT", "Child Of": "CHILD_OF", "Module Of": "MODULE_OF",
}
def ref_to_rel(ref):
    return REF_TO_REL.get(ref) or re.sub(r"[^A-Z0-9]+", "_", ref.upper())

def type_to_label(t):
    return re.sub(r"[^A-Za-z0-9]", "", t)

def parse_node(props):
    try:
        f = json.loads(props.get("fields") or "{}")
    except Exception:
        f = {}
    return {"id": props.get("id"), "label": props.get("label"), "type": props.get("type"), "f": f}

def require_key(x_api_key, request=None):
    if not API_KEY:
        return
    key = x_api_key
    if (not key) and request is not None:
        key = request.query_params.get("x-api-key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key (header x-api-key).")

# ---- health ---------------------------------------------------------
@app.get("/api/health")
def health():
    r = run("RETURN 1 AS ok")
    return {"status": "ok", "neo4j": r[0]["ok"] == 1}

# ---- full graph -----------------------------------------------------
@app.get("/api/graph")
def graph(workspace: str = None):
    # Optional ?workspace= filters to one company's graph. Existing seed data
    # (no workspace property) is treated as workspace "Zoho Corporation".
    if workspace:
        nodes = [parse_node(r["c"]) for r in run(
            "MATCH (c:Component) WHERE coalesce(c.workspace,'Zoho Corporation')=$ws RETURN c",
            {"ws": workspace})]
        edges = [{"id": e["id"], "s": e["s"], "t": e["t"], "r": e["r"]} for e in run(
            "MATCH (a:Component)-[r]->(b:Component) WHERE r.ref IS NOT NULL "
            "AND coalesce(a.workspace,'Zoho Corporation')=$ws "
            "AND coalesce(b.workspace,'Zoho Corporation')=$ws "
            "RETURN r.id AS id, a.id AS s, b.id AS t, r.ref AS r", {"ws": workspace})]
    else:
        nodes = [parse_node(r["c"]) for r in run("MATCH (c:Component) RETURN c")]
        edges = [{"id": e["id"], "s": e["s"], "t": e["t"], "r": e["r"]} for e in run(
            "MATCH (a:Component)-[r]->(b:Component) WHERE r.ref IS NOT NULL "
            "RETURN r.id AS id, a.id AS s, b.id AS t, r.ref AS r")]
    return {"nodes": nodes, "edges": edges}

# ---- list workspaces (for the dashboard workspace selector) ---------
@app.get("/api/workspaces")
def workspaces():
    rows = run("MATCH (c:Component) WITH coalesce(c.workspace,'Zoho Corporation') AS ws, "
               "count(*) AS n RETURN ws, n ORDER BY n DESC")
    return [{"workspace": r["ws"], "components": r["n"]} for r in rows]

# ---- metamodel ------------------------------------------------------
@app.get("/api/metamodel")
def metamodel():
    component_types = run(
        "MATCH (t:MetaComponentType) RETURN t.name AS name, t.tier AS tier, "
        "t.category AS category, t.shape AS shape, t.color AS color ORDER BY t.tier")
    reference_types = run("MATCH (r:MetaReferenceType) RETURN r.name AS name, r.color AS color")
    allowed = run("MATCH (a:MetaComponentType)-[x:ALLOWS]->(b:MetaComponentType) "
                  "RETURN a.name AS from, x.ref AS ref, b.name AS to ORDER BY from")
    return {"componentTypes": component_types, "referenceTypes": reference_types, "allowed": allowed}

# ---- search ---------------------------------------------------------
@app.get("/api/search")
def search(q: str = ""):
    rows = run(
        "MATCH (c:Component) WHERE toLower(c.name) CONTAINS toLower($q) "
        "OR toLower(c.label) CONTAINS toLower($q) OR toLower(c.type) CONTAINS toLower($q) "
        "RETURN c LIMIT 50", {"q": q})
    return [parse_node(r["c"]) for r in rows]

# ---- 360 view -------------------------------------------------------
@app.get("/api/node/{id}")
def node360(id: str):
    node_rows = run("MATCH (c:Component {id:$id}) RETURN c", {"id": id})
    if not node_rows:
        raise HTTPException(status_code=404, detail="Not found")
    node = parse_node(node_rows[0]["c"])
    outgoing = run("MATCH (c:Component {id:$id})-[r]->(b:Component) WHERE r.ref IS NOT NULL "
                   "RETURN r.id AS edgeId, r.ref AS ref, b.id AS id, b.label AS label, b.type AS type", {"id": id})
    incoming = run("MATCH (a:Component)-[r]->(c:Component {id:$id}) WHERE r.ref IS NOT NULL "
                   "RETURN r.id AS edgeId, r.ref AS ref, a.id AS id, a.label AS label, a.type AS type", {"id": id})
    node["outgoing"] = outgoing
    node["incoming"] = incoming
    return node

# ---- create component (+ optional reference) ------------------------
@app.post("/api/node")
async def create_node(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    if not b.get("type") or not b.get("label"):
        raise HTTPException(status_code=400, detail="type and label are required")
    nid = b.get("id") or ("n_" + str(int(time.time() * 1000)))
    f = {"Name": b["label"], "Description": b.get("description", ""),
         "Lifecycle Phase": b.get("phase", "Live")}
    f.update(b.get("fields") or {})
    run("MERGE (c:Component {id:$id}) SET c.label=$label, c.type=$type, c.name=$name, "
        "c.description=$desc, c.lifecycle=$phase, c.fields=$fields",
        {"id": nid, "label": b["label"], "type": b["type"], "name": f["Name"],
         "desc": f["Description"], "phase": f["Lifecycle Phase"], "fields": json.dumps(f)}, True)

    edge = None
    if b.get("parentId") and b.get("refType"):
        eid = "e_" + str(int(time.time() * 1000))
        rel = ref_to_rel(b["refType"])
        run(f"MATCH (a:Component {{id:$pid}}) MATCH (c:Component {{id:$id}}) "
            f"MERGE (a)-[r:{rel} {{id:$eid}}]->(c) SET r.ref=$ref",
            {"pid": b["parentId"], "id": nid, "eid": eid, "ref": b["refType"]}, True)
        edge = {"id": eid, "s": b["parentId"], "t": nid, "r": b["refType"]}
    return JSONResponse(status_code=201, content={"node": {"id": nid, "label": b["label"], "type": b["type"], "f": f}, "edge": edge})

# ---- create reference ----------------------------------------------
@app.post("/api/edge")
async def create_edge(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    if not (b.get("s") and b.get("t") and b.get("r")):
        raise HTTPException(status_code=400, detail="s, t and r are required")
    eid = "e_" + str(int(time.time() * 1000))
    rel = ref_to_rel(b["r"])
    run(f"MATCH (a:Component {{id:$s}}) MATCH (b:Component {{id:$t}}) "
        f"MERGE (a)-[x:{rel} {{id:$eid}}]->(b) SET x.ref=$r",
        {"s": b["s"], "t": b["t"], "eid": eid, "r": b["r"]}, True)
    return JSONResponse(status_code=201, content={"id": eid, "s": b["s"], "t": b["t"], "r": b["r"]})

# ---- delete component ----------------------------------------------
@app.delete("/api/node/{id}")
def delete_node(id: str, request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    run("MATCH (c:Component {id:$id}) DETACH DELETE c", {"id": id}, True)
    return {"deleted": id}

# ---- delete reference ----------------------------------------------
@app.delete("/api/edge/{id}")
def delete_edge(id: str, request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    run("MATCH ()-[r {id:$id}]->() DELETE r", {"id": id}, True)
    return {"deleted": id}

# ---- update component fields / tags (custom fields) ----------------
@app.patch("/api/node/{id}")
async def update_node(id: str, request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    rows = run("MATCH (c:Component {id:$id}) RETURN c", {"id": id})
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    props = rows[0]["c"]
    try:
        f = json.loads(props.get("fields") or "{}")
    except Exception:
        f = {}
    if b.get("fields"):
        f.update(b["fields"])
    if "tags" in b:
        f["Tags"] = b["tags"]
    label = b.get("label", props.get("label"))
    run("MATCH (c:Component {id:$id}) SET c.label=$label, c.name=$name, c.fields=$fields",
        {"id": id, "label": label, "name": f.get("Name", label),
         "fields": json.dumps(f, ensure_ascii=False)}, True)
    return {"id": id, "label": label, "type": props.get("type"), "f": f}

# ---- metamodel editing (add/remove types & allowed connections) ----
@app.post("/api/metamodel/component-type")
async def add_ctype(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    run("""MERGE (t:MetaComponentType {name:$name})
           SET t.tier=$tier, t.category=$cat, t.shape=$shape, t.color=$color""",
        {"name": b["name"], "tier": b.get("tier", 99), "cat": b.get("category", "Other"),
         "shape": b.get("shape", "roundrectangle"), "color": b.get("color", "#888780")}, True)
    return {"ok": True, "name": b["name"]}

@app.delete("/api/metamodel/component-type/{name}")
def del_ctype(name: str, request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    run("MATCH (t:MetaComponentType {name:$name}) DETACH DELETE t", {"name": name}, True)
    return {"deleted": name}

@app.post("/api/metamodel/reference-type")
async def add_rtype(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    run("MERGE (r:MetaReferenceType {name:$name}) SET r.color=$color, r.relType=$rel",
        {"name": b["name"], "color": b.get("color", "#888780"), "rel": ref_to_rel(b["name"])}, True)
    return {"ok": True, "name": b["name"]}

@app.delete("/api/metamodel/reference-type/{name}")
def del_rtype(name: str, request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    run("MATCH (r:MetaReferenceType {name:$name}) DETACH DELETE r", {"name": name}, True)
    return {"deleted": name}

@app.post("/api/metamodel/allowed")
async def add_allowed(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    run("""MATCH (a:MetaComponentType {name:$f}) MATCH (b:MetaComponentType {name:$t})
           MERGE (a)-[x:ALLOWS {ref:$r}]->(b)""",
        {"f": b["from"], "t": b["to"], "r": b["ref"]}, True)
    return {"ok": True}

@app.delete("/api/metamodel/allowed")
async def del_allowed(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    run("""MATCH (a:MetaComponentType {name:$f})-[x:ALLOWS {ref:$r}]->(b:MetaComponentType {name:$t})
           DELETE x""", {"f": b["from"], "t": b["to"], "r": b["ref"]}, True)
    return {"deleted": True}

# ---- rationalization (TIME model) ----------------------------------
@app.get("/api/analytics/rationalization")
def rationalization():
    rows = run("MATCH (a:Application) RETURN a.id AS id, a.label AS label, "
               "a.businessValue AS bv, a.technicalFit AS tf, a.strategicRating AS rating")
    out = []
    for r in rows:
        bv, tf = r.get("bv") or 0, r.get("tf") or 0
        if bv >= 4 and tf >= 4: q = "Invest"
        elif bv >= 4 and tf < 4: q = "Tolerate"
        elif bv < 4 and tf >= 4: q = "Migrate"
        else: q = "Eliminate"
        out.append({"id": r["id"], "label": r["label"], "businessValue": bv,
                    "technicalFit": tf, "declaredRating": r.get("rating"), "quadrant": q})
    return out

# ---- capability coverage -------------------------------------------
@app.get("/api/analytics/capability-coverage")
def capability_coverage():
    rows = run("MATCH (bc:BusinessCapability) OPTIONAL MATCH (bc)-[:IS_REALIZED_BY]->(app:Application) "
               "RETURN bc.id AS id, bc.label AS label, count(app) AS apps ORDER BY apps DESC")
    return [{"id": r["id"], "label": r["label"], "apps": r["apps"]} for r in rows]

# ---- GitHub sync ---------------------------------------------------
@app.post("/api/github/sync")
async def github_sync_endpoint(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    org = b.get("org")
    if not org:
        raise HTTPException(status_code=400, detail="org (GitHub org/user) is required")
    import github_sync
    return github_sync.sync_org(org, token=os.getenv("GITHUB_TOKEN"), max_repos=b.get("maxRepos", 30))

# =====================================================================
# ONBOARDING  —  build a new customer's EA graph from scratch via the
# Zia agent. The agent interviews the user, enriches from their website,
# then calls bulk-build to create the whole graph in one shot.
# =====================================================================

# ---- enrich a company from its public website ----------------------
def _http_get(url):
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 zoho-ea-poc"})
        return r.text if r.status_code < 400 else ""
    except Exception:
        return ""

def _extract(html):
    if not html:
        return {}
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    desc = ""
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.I | re.S)
    if m:
        desc = m.group(1).strip()
    heads = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.I | re.S)
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in heads]
    heads = [h for h in heads if h][:25]
    jsonld = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S)
    body = re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()[:3500]
    return {"title": title, "description": desc, "headings": heads,
            "jsonld": [j.strip()[:1500] for j in jsonld[:3]], "text": body}

@app.post("/api/onboard/enrich")
async def onboard_enrich(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    url = (b.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    if not url.startswith("http"):
        url = "https://" + url
    base = url.rstrip("/")
    pages = {}
    for suffix in ["", "/about", "/about-us", "/products", "/solutions", "/company"]:
        data = _extract(_http_get(base + suffix))
        if data and (data.get("text") or data.get("headings")):
            pages[suffix or "/"] = data
    if not pages:
        return {"url": url, "reachable": False,
                "note": "Could not fetch the site server-side. Ask the user to describe the company instead."}
    return {"url": url, "reachable": True, "pages": pages}

# ---- bulk build the graph (agent constructs the whole EA model) -----
@app.post("/api/graph/bulk")
async def graph_bulk(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    ws = b.get("workspace") or "default"
    comps = b.get("components") or []
    refs = b.get("references") or []

    def num(v):
        if v is None:
            return None
        m = re.search(r"-?\d+(\.\d+)?", str(v))
        return float(m.group()) if m else None

    rows = []
    for c in comps:
        f = dict(c.get("fields") or {})
        f.setdefault("Name", c.get("label"))
        if c.get("description"):
            f["Description"] = c["description"]
        if c.get("phase"):
            f["Lifecycle Phase"] = c["phase"]
        if c.get("tags"):
            f["Tags"] = c["tags"]
        rows.append({
            "id": c.get("id") or (ws.lower().replace(" ", "-") + "_" + re.sub(r"[^a-zA-Z0-9]+", "-", (c.get("label") or "n")).lower()),
            "label": c.get("label"), "type": c.get("type"), "ws": ws,
            "name": f.get("Name", c.get("label")), "desc": f.get("Description", ""),
            "life": f.get("Lifecycle Phase", ""),
            "sr": (re.sub(r"\s*\(.*?\)", "", str(f.get("Strategic Rating", ""))) or None),
            "bv": num(f.get("Business Value")), "tf": num(f.get("Technical Fit")),
            "fields": json.dumps(f, ensure_ascii=False),
        })
    if rows:
        run("""UNWIND $rows AS row MERGE (c:Component {id: row.id})
               SET c.label=row.label, c.type=row.type, c.workspace=row.ws, c.name=row.name,
                   c.description=row.desc, c.lifecycle=row.life, c.strategicRating=row.sr,
                   c.businessValue=row.bv, c.technicalFit=row.tf, c.fields=row.fields""",
            {"rows": rows}, True)
        for t in {r["type"] for r in rows if r["type"]}:
            run(f"MATCH (c:Component {{type:$t, workspace:$ws}}) SET c:{type_to_label(t)}", {"t": t, "ws": ws}, True)

    # references: accept ids OR labels (agent may pass labels)
    made = 0
    for e in refs:
        s, t, r = e.get("s"), e.get("t"), e.get("r")
        if not (s and t and r):
            continue
        rel = ref_to_rel(r)
        eid = "e_" + re.sub(r"[^a-zA-Z0-9]+", "-", f"{ws}-{s}-{rel}-{t}").lower()
        res = run(f"""MATCH (a:Component) WHERE (a.id=$s OR a.label=$s) AND coalesce(a.workspace,'Zoho Corporation')=$ws
                      MATCH (b:Component) WHERE (b.id=$t OR b.label=$t) AND coalesce(b.workspace,'Zoho Corporation')=$ws
                      MERGE (a)-[x:{rel} {{id:$eid}}]->(b) SET x.ref=$r RETURN count(x) AS n""",
                  {"s": s, "t": t, "eid": eid, "r": r, "ws": ws}, True)
        made += (res[0]["n"] if res else 0)
    return {"workspace": ws, "componentsUpserted": len(rows), "referencesCreated": made,
            "dashboardUrl": f"/?workspace={ws}"}

# ---- reset a workspace (fresh start) -------------------------------
@app.post("/api/onboard/reset")
async def onboard_reset(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    ws = b.get("workspace")
    if not ws:
        raise HTTPException(status_code=400, detail="workspace is required")
    run("MATCH (c:Component) WHERE c.workspace=$ws DETACH DELETE c", {"ws": ws}, True)
    return {"reset": ws}

# ---- one-click seed loader (POC convenience) -----------------------
# Loads data.json (65 components + 115 references) into Neo4j. Idempotent.
# Call once:  https://<app>/api/admin/seed?x-api-key=YOUR_API_KEY
@app.api_route("/api/admin/seed", methods=["GET", "POST"])
def admin_seed(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)

    def num(v):
        if v is None:
            return None
        m = re.search(r"-?\d+(\.\d+)?", str(v))
        return float(m.group()) if m else None

    data = json.load(open(os.path.join(os.path.dirname(__file__), "data.json"), encoding="utf-8"))
    nodes, edges = data["nodes"], data["edges"]

    try:
        run("CREATE CONSTRAINT component_id IF NOT EXISTS FOR (c:Component) REQUIRE c.id IS UNIQUE", {}, True)
    except Exception as e:
        log.warning("constraint step skipped: %s", e)

    rows = [{
        "id": n["id"], "label": n["label"], "type": n["type"],
        "name": n["f"].get("Name", n["label"]), "description": n["f"].get("Description", ""),
        "lifecycle": n["f"].get("Lifecycle Phase", ""),
        "strategicRating": (re.sub(r"\s*\(.*?\)", "", n["f"].get("Strategic Rating", "")) or None),
        "businessValue": num(n["f"].get("Business Value")), "technicalFit": num(n["f"].get("Technical Fit")),
        "fields": json.dumps(n["f"], ensure_ascii=False),
    } for n in nodes]
    run("""UNWIND $rows AS row MERGE (c:Component {id: row.id})
           SET c.label=row.label, c.type=row.type, c.name=row.name,
               c.workspace='Zoho Corporation',
               c.description=row.description, c.lifecycle=row.lifecycle,
               c.strategicRating=row.strategicRating, c.businessValue=row.businessValue,
               c.technicalFit=row.technicalFit, c.fields=row.fields""", {"rows": rows}, True)

    for t in {n["type"] for n in nodes}:
        run(f"MATCH (c:Component {{type:$t}}) SET c:{type_to_label(t)}", {"t": t}, True)

    by_ref = {}
    for e in edges:
        by_ref.setdefault(e["r"], []).append(e)
    for ref, group in by_ref.items():
        rel = ref_to_rel(ref)
        run(f"""UNWIND $rows AS row MATCH (a:Component {{id: row.s}}) MATCH (b:Component {{id: row.t}})
                MERGE (a)-[x:{rel} {{id: row.id}}]->(b) SET x.ref=$ref""", {"rows": group, "ref": ref}, True)

    c = run("MATCH (c:Component) RETURN count(c) AS n")[0]["n"]
    r = run("MATCH ()-[x]->() WHERE x.ref IS NOT NULL RETURN count(x) AS n")[0]["n"]
    log.info("Seed complete: %s components, %s references", c, r)
    return {"seeded": True, "components": c, "references": r}

# ---- dashboard with runtime config injection -----------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/graph/view", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    path = os.path.join(os.path.dirname(__file__), "public", "index.html")
    if not os.path.exists(path):
        log.error("Dashboard file missing: %s — commit the public/ folder to the repo.", path)
        return HTMLResponse(status_code=200, content=(
            "<h1>Zoho EA API is running ✅</h1>"
            "<p>But <code>public/index.html</code> was not found on the server. "
            "Commit the <code>public/</code> folder to your GitHub repo and redeploy.</p>"
            "<p>The API works now — try "
            "<a href='/api/health'>/api/health</a> and "
            "<a href='/api/metamodel'>/api/metamodel</a>.</p>"))
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace("__API_BASE__", "").replace("__API_KEY__", API_KEY)
    return HTMLResponse(content=html)
