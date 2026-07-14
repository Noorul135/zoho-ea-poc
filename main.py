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

def require_key(x_api_key):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing x-api-key header.")

# ---- health ---------------------------------------------------------
@app.get("/api/health")
def health():
    r = run("RETURN 1 AS ok")
    return {"status": "ok", "neo4j": r[0]["ok"] == 1}

# ---- full graph -----------------------------------------------------
@app.get("/api/graph")
def graph():
    nodes = [parse_node(r["c"]) for r in run("MATCH (c:Component) RETURN c")]
    edges = [{"id": e["id"], "s": e["s"], "t": e["t"], "r": e["r"]} for e in run(
        "MATCH (a:Component)-[r]->(b:Component) WHERE r.ref IS NOT NULL "
        "RETURN r.id AS id, a.id AS s, b.id AS t, r.ref AS r")]
    return {"nodes": nodes, "edges": edges}

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
    require_key(x_api_key)
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
    require_key(x_api_key)
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
def delete_node(id: str, x_api_key: str = Header(default="")):
    require_key(x_api_key)
    run("MATCH (c:Component {id:$id}) DETACH DELETE c", {"id": id}, True)
    return {"deleted": id}

# ---- delete reference ----------------------------------------------
@app.delete("/api/edge/{id}")
def delete_edge(id: str, x_api_key: str = Header(default="")):
    require_key(x_api_key)
    run("MATCH ()-[r {id:$id}]->() DELETE r", {"id": id}, True)
    return {"deleted": id}

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
    require_key(x_api_key)
    b = await request.json()
    org = b.get("org")
    if not org:
        raise HTTPException(status_code=400, detail="org (GitHub org/user) is required")
    import github_sync
    return github_sync.sync_org(org, token=os.getenv("GITHUB_TOKEN"), max_repos=b.get("maxRepos", 30))

# ---- dashboard with runtime config injection -----------------------
@app.get("/", response_class=HTMLResponse)
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
