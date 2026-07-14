# =====================================================================
# seed.py  —  Python loader. Loads data.json (65 components, 115 refs)
# into Neo4j Aura. Run once after 01-constraints.cypher + 02-metamodel.cypher.
#
#   python seed.py           (add/update)
#   python seed.py --wipe     (delete existing components first)
# =====================================================================
import os, json, re, sys
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

REF_TO_REL = {
    "Owns": "OWNS", "Is Expert In": "IS_EXPERT_IN", "Belongs To": "BELONGS_TO",
    "Reports To": "REPORTS_TO", "Consumes": "CONSUMES", "Is Realized By": "IS_REALIZED_BY",
    "Is Supported By": "IS_SUPPORTED_BY", "Connects To": "CONNECTS_TO",
    "Has Successor": "HAS_SUCCESSOR", "Deploys To": "DEPLOYS_TO",
    "Is Located At": "IS_LOCATED_AT", "Child Of": "CHILD_OF", "Module Of": "MODULE_OF",
}
def ref_to_rel(r): return REF_TO_REL.get(r) or re.sub(r"[^A-Z0-9]+", "_", r.upper())
def type_to_label(t): return re.sub(r"[^A-Za-z0-9]", "", t)
def num(v):
    if v is None: return None
    m = re.search(r"-?\d+(\.\d+)?", str(v))
    return float(m.group()) if m else None

def main():
    uri, user, pwd = os.getenv("NEO4J_URI"), os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")
    if not uri or not pwd:
        sys.exit("Missing NEO4J_URI / NEO4J_PASSWORD")
    data = json.load(open(os.path.join(os.path.dirname(__file__), "data.json"), encoding="utf-8"))
    nodes, edges = data["nodes"], data["edges"]
    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    with driver.session() as s:
        if "--wipe" in sys.argv:
            print("Wiping existing :Component nodes ...")
            s.run("MATCH (c:Component) DETACH DELETE c")

        print(f"Loading {len(nodes)} components ...")
        rows = []
        for n in nodes:
            f = n["f"]
            rows.append({
                "id": n["id"], "label": n["label"], "type": n["type"],
                "name": f.get("Name", n["label"]), "description": f.get("Description", ""),
                "lifecycle": f.get("Lifecycle Phase", ""),
                "strategicRating": re.sub(r"\s*\(.*?\)", "", f.get("Strategic Rating", "")) or None,
                "businessValue": num(f.get("Business Value")), "technicalFit": num(f.get("Technical Fit")),
                "fields": json.dumps(f, ensure_ascii=False),
            })
        s.run("""UNWIND $rows AS row MERGE (c:Component {id: row.id})
                 SET c.label=row.label, c.type=row.type, c.name=row.name,
                     c.description=row.description, c.lifecycle=row.lifecycle,
                     c.strategicRating=row.strategicRating, c.businessValue=row.businessValue,
                     c.technicalFit=row.technicalFit, c.fields=row.fields""", rows=rows)

        for t in {n["type"] for n in nodes}:
            s.run(f"MATCH (c:Component {{type:$t}}) SET c:{type_to_label(t)}", t=t)

        print(f"Loading {len(edges)} references ...")
        by_ref = {}
        for e in edges:
            by_ref.setdefault(e["r"], []).append(e)
        for ref, group in by_ref.items():
            rel = ref_to_rel(ref)
            s.run(f"""UNWIND $rows AS row
                      MATCH (a:Component {{id: row.s}}) MATCH (b:Component {{id: row.t}})
                      MERGE (a)-[x:{rel} {{id: row.id}}]->(b) SET x.ref=$ref""", rows=group, ref=ref)

        c = s.run("MATCH (c:Component) RETURN count(c) AS n").single()["n"]
        r = s.run("MATCH ()-[r]->() WHERE r.ref IS NOT NULL RETURN count(r) AS n").single()["n"]
        print(f"Done. Graph now holds: {c} components, {r} references")
    driver.close()

if __name__ == "__main__":
    main()
