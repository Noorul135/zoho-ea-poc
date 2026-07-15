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
    return {"id": props.get("id"), "label": props.get("label"), "type": props.get("type"),
            "f": f, "status": props.get("status"), "layer": props.get("layer")}

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
        edges = [{"id": e["id"], "s": e["s"], "t": e["t"], "r": e["r"], "inferred": e["inf"]} for e in run(
            "MATCH (a:Component)-[r]->(b:Component) WHERE r.ref IS NOT NULL "
            "AND coalesce(a.workspace,'Zoho Corporation')=$ws "
            "AND coalesce(b.workspace,'Zoho Corporation')=$ws "
            "RETURN r.id AS id, a.id AS s, b.id AS t, r.ref AS r, coalesce(r.inferred,false) AS inf", {"ws": workspace})]
    else:
        nodes = [parse_node(r["c"]) for r in run("MATCH (c:Component) RETURN c")]
        edges = [{"id": e["id"], "s": e["s"], "t": e["t"], "r": e["r"], "inferred": e["inf"]} for e in run(
            "MATCH (a:Component)-[r]->(b:Component) WHERE r.ref IS NOT NULL "
            "RETURN r.id AS id, a.id AS s, b.id AS t, r.ref AS r, coalesce(r.inferred,false) AS inf")]
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
    ws = b.get("workspace")
    wsA = "AND coalesce(a.workspace,'Zoho Corporation')=$ws" if ws else ""
    wsB = "AND coalesce(b.workspace,'Zoho Corporation')=$ws" if ws else ""
    # match by id OR label (case-insensitive) so agents can pass either
    res = run(f"""MATCH (a:Component) WHERE (a.id=$s OR toLower(a.label)=toLower($s)) {wsA}
                  MATCH (b:Component) WHERE (b.id=$t OR toLower(b.label)=toLower($t)) {wsB}
                  MERGE (a)-[x:{rel} {{id:$eid}}]->(b) SET x.ref=$r RETURN count(x) AS n""",
              {"s": b["s"], "t": b["t"], "eid": eid, "r": b["r"], "ws": ws}, True)
    made = res[0]["n"] if res else 0
    if not made:
        raise HTTPException(status_code=404, detail=f"Could not find source '{b['s']}' or target '{b['t']}' (check the exact name or workspace).")
    return JSONResponse(status_code=201, content={"id": eid, "s": b["s"], "t": b["t"], "r": b["r"], "created": made})

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
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
def _http_get(url):
    try:
        r = requests.get(url, timeout=10, allow_redirects=True, headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
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

# ---- shared graph-build core (used by bulk + build) -----------------
def _as_list(v):
    """Accept a list, a JSON string, or None; always return a list."""
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return []
    return v if isinstance(v, list) else []

def _normalize_payload(b):
    """Accept ANY shape the agent might send and return (components, references):
       - {"spec": "<json string>"}                          (recommended)
       - {"components":[...], "references":[...]}            (nested, or JSON strings)
       - parallel arrays {"label":[...],"type":[...]} nodes  and
         {"s":[...],"t":[...],"r":[...]} references          (agent fallback shape)
    """
    if isinstance(b.get("spec"), str):
        try:
            b = {**b, **json.loads(b["spec"])}
        except Exception:
            pass
    elif isinstance(b.get("spec"), dict):
        b = {**b, **b["spec"]}
    comps = _as_list(b.get("components"))
    refs = _as_list(b.get("references"))
    # parallel label/type arrays -> components (stubs where label==type are dropped later)
    labels, types = b.get("label"), b.get("type")
    descs, ids = b.get("description"), b.get("id")
    if isinstance(labels, list) and isinstance(types, list) and not comps:
        for i in range(min(len(labels), len(types))):
            c = {"label": labels[i], "type": types[i]}
            if isinstance(descs, list) and i < len(descs):
                c["description"] = descs[i]
            if isinstance(ids, list) and i < len(ids):
                c["id"] = ids[i]
            comps.append(c)
    # parallel s/t/r arrays -> references (broadcast a single r across all pairs)
    ss, tt, rr = b.get("s"), b.get("t"), b.get("r")
    if isinstance(ss, list) and isinstance(tt, list) and isinstance(rr, list) and not refs:
        n = min(len(ss), len(tt))
        for i in range(n):
            rel = rr[i] if i < len(rr) else (rr[0] if rr else None)
            if rel:
                refs.append({"s": ss[i], "t": tt[i], "r": rel})
    return comps, refs

def _build_graph(ws, comps, refs):
    def num(v):
        if v is None:
            return None
        m = re.search(r"-?\d+(\.\d+)?", str(v))
        return float(m.group()) if m else None

    rows, skipped = [], 0
    for c in comps:
        if not isinstance(c, dict):
            skipped += 1; continue
        label = (c.get("label") or "").strip()
        ctype = (c.get("type") or "").strip()
        # skip empty or placeholder stubs where label just repeats the type name
        if not label or not ctype or label.lower() == ctype.lower():
            skipped += 1; continue
        f = dict(c.get("fields") or {})
        f.setdefault("Name", label)
        if c.get("description"):
            f["Description"] = c["description"]
        if c.get("phase"):
            f["Lifecycle Phase"] = c["phase"]
        if c.get("tags"):
            f["Tags"] = c["tags"]
        for pk in ("confidence", "evidence", "source_doc", "as_of"):
            if c.get(pk) is not None:
                f[pk.replace("_", " ").title()] = c[pk]
        rows.append({
            "id": c.get("id") or (re.sub(r"[^a-z0-9]+", "-", ws.lower()) + "_" + re.sub(r"[^a-zA-Z0-9]+", "-", label).lower()),
            "label": label, "type": ctype, "ws": ws,
            "name": f.get("Name", label), "desc": f.get("Description", ""),
            "life": f.get("Lifecycle Phase", ""),
            "status": c.get("status") or "active", "layer": c.get("layer"),
            "sr": (re.sub(r"\s*\(.*?\)", "", str(f.get("Strategic Rating", ""))) or None),
            "bv": num(f.get("Business Value")), "tf": num(f.get("Technical Fit")),
            "fields": json.dumps(f, ensure_ascii=False),
        })
    if rows:
        run("""UNWIND $rows AS row MERGE (c:Component {id: row.id})
               SET c.label=row.label, c.type=row.type, c.workspace=row.ws, c.name=row.name,
                   c.description=row.desc, c.lifecycle=row.life, c.status=row.status, c.layer=row.layer,
                   c.strategicRating=row.sr, c.businessValue=row.bv, c.technicalFit=row.tf, c.fields=row.fields""",
            {"rows": rows}, True)
        for t in {r["type"] for r in rows if r["type"]}:
            run(f"MATCH (c:Component {{type:$t, workspace:$ws}}) SET c:{type_to_label(t)}", {"t": t, "ws": ws}, True)

    made, unresolved = 0, []
    for e in refs:
        if not isinstance(e, dict):
            continue
        s, t, r = e.get("s"), e.get("t"), e.get("r")
        if not (s and t and r):
            continue
        rel = ref_to_rel(r)
        inferred = bool(e.get("inferred"))
        eid = "e_" + re.sub(r"[^a-zA-Z0-9]+", "-", f"{ws}-{s}-{rel}-{t}").lower()
        res = run(f"""MATCH (a:Component) WHERE (a.id=$s OR toLower(a.label)=toLower($s)) AND coalesce(a.workspace,'Zoho Corporation')=$ws
                      MATCH (b:Component) WHERE (b.id=$t OR toLower(b.label)=toLower($t)) AND coalesce(b.workspace,'Zoho Corporation')=$ws
                      MERGE (a)-[x:{rel} {{id:$eid}}]->(b) SET x.ref=$r, x.inferred=$inf RETURN count(x) AS n""",
                  {"s": s, "t": t, "eid": eid, "r": r, "ws": ws, "inf": inferred}, True)
        n = res[0]["n"] if res else 0
        made += n
        if not n:
            unresolved.append(f"{s} -[{r}]-> {t}")
    return {"workspace": ws, "componentsUpserted": len(rows), "componentsSkipped": skipped,
            "referencesCreated": made, "unresolvedReferences": unresolved,
            "dashboardUrl": f"/?workspace={ws}"}

# ---- bulk build — accepts ANY payload shape ------------------------
@app.post("/api/graph/bulk")
async def graph_bulk(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    ws = b.get("workspace") or "default"
    comps, refs = _normalize_payload(b)
    return _build_graph(ws, comps, refs)

# ---- build from ONE JSON string (recommended) — also accepts any shape
@app.post("/api/graph/build")
async def graph_build(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    ws = b.get("workspace") or "default"
    comps, refs = _normalize_payload(b)
    return _build_graph(ws, comps, refs)

# ---- delete stub nodes (label == type) -----------------------------
@app.api_route("/api/admin/cleanup-stubs", methods=["GET", "POST"])
def cleanup_stubs(request: Request, x_api_key: str = Header(default=""), workspace: str = None):
    require_key(x_api_key, request)
    if workspace:
        rows = run("MATCH (c:Component) WHERE toLower(c.label)=toLower(c.type) "
                   "AND coalesce(c.workspace,'Zoho Corporation')=$ws DETACH DELETE c RETURN count(c) AS n",
                   {"ws": workspace}, True)
    else:
        rows = run("MATCH (c:Component) WHERE toLower(c.label)=toLower(c.type) "
                   "DETACH DELETE c RETURN count(c) AS n", {}, True)
    return {"deletedStubs": rows[0]["n"] if rows else 0}

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

# =====================================================================
# CARTOGRAPH tools — web fetch, graph summary, read-only query, ontology
# =====================================================================

# ---- fetch any public web page (agent website intake) --------------
def _same_site_links(html, base):
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href, txt = m.group(1).strip(), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        if href.startswith("/"):
            href = base.rstrip("/") + href
        if not href.startswith("http"):
            continue
        try:
            from urllib.parse import urlparse as _up
            if _up(href).netloc != _up(base).netloc:
                continue
        except Exception:
            continue
        if len(txt) < 3 or href in seen:
            continue
        seen.add(href)
        out.append({"url": href.split("#")[0], "text": txt[:120]})
        if len(out) >= 40:
            break
    return out

@app.post("/api/web/fetch")
async def fetch_web_page(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    url = (b.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    if not url.startswith("http"):
        url = "https://" + url
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith(("10.", "192.168.", "172.16.")):
        raise HTTPException(status_code=400, detail="Cannot fetch private/localhost URLs.")
    html = _http_get(url)
    if not html:
        # graceful 200 so the agent can proceed by asking the user instead
        return {"url": url, "reachable": False,
                "note": "The site blocked server-side fetching or is unreachable. Ask the user to describe the company instead."}
    data = _extract(html)
    data["url"] = url
    data["same_site_links"] = _same_site_links(html, url)
    data["reachable"] = True
    return data

# ---- graph summary + gap analysis (getGraphSummary) ----------------
@app.get("/api/graph/summary")
def graph_summary(workspace: str = None):
    wsf = "coalesce(c.workspace,'Zoho Corporation')=$ws" if workspace else "true"
    p = {"ws": workspace} if workspace else {}
    counts = run(f"MATCH (c:Component) WHERE {wsf} RETURN c.type AS type, count(*) AS n ORDER BY n DESC", p)
    total = run(f"MATCH (c:Component) WHERE {wsf} RETURN count(c) AS n", p)[0]["n"]
    refs = run(f"MATCH (a:Component)-[r]->(b:Component) WHERE r.ref IS NOT NULL AND {wsf.replace('c.','a.')} "
               f"RETURN count(r) AS n", p)[0]["n"]
    # spine gaps
    gaps = {}
    def cnt(q):
        return run(q, p)[0]["n"]
    gaps["objectivesWithoutKpi"] = cnt(f"MATCH (o:Component) WHERE o.type IN ['Objective'] AND {wsf.replace('c.','o.')} AND NOT (o)-[:MEASURED_BY]->() RETURN count(o) AS n") if _has_type("Objective") else 0
    gaps["objectivesWithoutCapability"] = cnt(f"MATCH (o:Component) WHERE o.type IN ['Objective'] AND {wsf.replace('c.','o.')} AND NOT (o)-[:ENABLED_BY]->() RETURN count(o) AS n") if _has_type("Objective") else 0
    gaps["capabilitiesWithoutProcess"] = cnt(f"MATCH (c:Component) WHERE c.type IN ['Capability','Business Capability'] AND {wsf} AND NOT (c)-[:REALIZED_BY]->() RETURN count(c) AS n")
    gaps["processesWithoutApp"] = cnt(f"MATCH (c:Component) WHERE c.type='Process' AND {wsf} AND NOT (c)-[:SUPPORTED_BY]->() RETURN count(c) AS n")
    gaps["risksWithoutOwner"] = cnt(f"MATCH (c:Component) WHERE c.type='Risk' AND {wsf} AND NOT ()-[:OWNS]->(c) AND NOT (c)-[:OWNED_BY]->() RETURN count(c) AS n")
    gaps["missingNodes"] = cnt(f"MATCH (c:Component) WHERE c.status='missing' AND {wsf} RETURN count(c) AS n")
    return {"workspace": workspace or "all", "totalComponents": total, "totalReferences": refs,
            "countsByType": [{"type": r["type"], "n": r["n"]} for r in counts], "gaps": gaps}

def _has_type(t):
    try:
        return run("MATCH (c:Component) WHERE c.type=$t RETURN count(c) AS n", {"t": t})[0]["n"] >= 0
    except Exception:
        return True

# ---- read-only Cypher (runReadQuery) -------------------------------
_WRITE_KW = re.compile(r"\b(CREATE|MERGE|SET|DELETE|REMOVE|DROP|DETACH|FOREACH|LOAD\s+CSV)\b", re.I)
@app.post("/api/query")
async def read_query(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    b = await request.json()
    cypher = (b.get("cypher") or "").strip()
    if not cypher:
        raise HTTPException(status_code=400, detail="cypher is required")
    if _WRITE_KW.search(cypher):
        raise HTTPException(status_code=400, detail="Only read-only queries are allowed (no CREATE/MERGE/SET/DELETE).")
    if " limit " not in cypher.lower():
        cypher += " LIMIT 200"
    try:
        return {"rows": run(cypher, b.get("params") or {})}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query error: {e}")

# ---- install the Cartograph EA ontology into the metamodel ----------
@app.api_route("/api/admin/install-ontology", methods=["GET", "POST"])
def install_ontology(request: Request, x_api_key: str = Header(default="")):
    require_key(x_api_key, request)
    ctypes = [
        ("Company", 1, "Business", "#E8212A"), ("Objective", 2, "Strategy", "#7A1FA2"),
        ("KPI", 3, "Performance", "#0F9D9D"), ("Capability", 3, "Business", "#993C1D"),
        ("Process", 4, "Operations", "#B5651D"), ("Person", 4, "Organization", "#3B6D11"),
        ("OrgUnit", 2, "Organization", "#185FA5"), ("Application", 5, "Application", "#085041"),
        ("Data", 6, "Data", "#BA7517"), ("Integration", 6, "Application", "#854F0B"),
        ("Technology", 7, "Technology", "#444441"), ("Vendor", 8, "Technology", "#888780"),
        ("Policy", 9, "Governance", "#5F5E5A"), ("Risk", 9, "Risk", "#C41019"),
        ("Initiative", 3, "Actions", "#534AB7"), ("Compliance", 9, "Governance", "#72243E"),
        ("Product", 5, "Commercial", "#1D9E75"), ("Customer", 5, "Commercial", "#378ADD"),
        ("Market", 4, "Commercial", "#993556"), ("Competitor", 5, "Commercial", "#9A6324"),
        ("Location", 10, "Other", "#993556"), ("Document", 11, "Provenance", "#b4b2a9"),
    ]
    rtypes = [
        ("HAS_OBJECTIVE", "#7A1FA2"), ("MEASURED_BY", "#0F9D9D"), ("ENABLED_BY", "#993C1D"),
        ("REALIZED_BY", "#B5651D"), ("SUPPORTED_BY", "#085041"), ("OWNS", "#3B6D11"),
        ("OWNED_BY", "#3B6D11"), ("AFFECTS", "#C41019"), ("DEPENDS_ON", "#854F0B"),
        ("SUPPORTS", "#534AB7"), ("IMPACTED_BY", "#534AB7"), ("RUNS_ON", "#444441"),
        ("PROVIDED_BY", "#888780"), ("COMPLIES_WITH", "#72243E"), ("INTEGRATES_VIA", "#854F0B"),
        ("CONNECTS_TO", "#085041"), ("REPORTS_TO", "#5F5E5A"), ("MEMBER_OF", "#185FA5"),
        ("LEADS", "#185FA5"), ("PART_OF", "#888780"), ("GOVERNED_BY", "#5F5E5A"),
        ("LOCATED_IN", "#993556"), ("DERIVED_FROM", "#b4b2a9"), ("MITIGATES", "#3B6D11"),
        ("COMPETES_WITH", "#9A6324"), ("SERVES", "#378ADD"), ("SELLS", "#1D9E75"),
    ]
    allowed = [
        ("Company", "HAS_OBJECTIVE", "Objective"), ("Objective", "MEASURED_BY", "KPI"),
        ("Objective", "ENABLED_BY", "Capability"), ("Capability", "REALIZED_BY", "Process"),
        ("Process", "SUPPORTED_BY", "Application"), ("Application", "OWNS", "Data"),
        ("Application", "RUNS_ON", "Technology"), ("Application", "PROVIDED_BY", "Vendor"),
        ("Application", "COMPLIES_WITH", "Compliance"), ("Application", "INTEGRATES_VIA", "Integration"),
        ("Integration", "CONNECTS_TO", "Application"), ("Risk", "AFFECTS", "Capability"),
        ("Risk", "AFFECTS", "Application"), ("Initiative", "SUPPORTS", "Objective"),
        ("Capability", "IMPACTED_BY", "Initiative"), ("Person", "OWNS", "Objective"),
        ("Person", "LEADS", "OrgUnit"), ("Person", "REPORTS_TO", "Person"),
        ("OrgUnit", "PART_OF", "Company"), ("Company", "SELLS", "Product"),
        ("Company", "COMPETES_WITH", "Competitor"), ("Company", "SERVES", "Customer"),
    ]
    # Batched into 3 round-trips (was ~70) so it stays well under the tool timeout.
    run("""UNWIND $rows AS r MERGE (t:MetaComponentType {name:r.name})
           SET t.tier=r.tier, t.category=r.cat, t.shape='roundrectangle', t.color=r.color""",
        {"rows": [{"name": n, "tier": ti, "cat": c, "color": col} for n, ti, c, col in ctypes]}, True)
    run("""UNWIND $rows AS r MERGE (m:MetaReferenceType {name:r.name})
           SET m.color=r.color, m.relType=r.name""",
        {"rows": [{"name": n, "color": c} for n, c in rtypes]}, True)
    run("""UNWIND $rows AS r MATCH (a:MetaComponentType {name:r.f}) MATCH (b:MetaComponentType {name:r.t})
           MERGE (a)-[x:ALLOWS {ref:r.r}]->(b)""",
        {"rows": [{"f": f, "t": t, "r": r} for f, r, t in allowed]}, True)
    return {"installed": True, "componentTypes": len(ctypes), "referenceTypes": len(rtypes), "allowed": len(allowed)}

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
