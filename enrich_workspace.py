# =====================================================================
# enrich_workspace.py — adds the component types the new Viewpoint
# dropdown needs (Capability, Risk, Initiative, Compliance, Technology,
# Location, OrgUnit, Epic, Strategy) into an EXISTING, already-live
# workspace (e.g. one built through the Zia onboarding chat, such as
# "ZappyWorks") that currently only has a handful of types (Person,
# Application, Company, Objective, KPI).
#
# It does NOT know or guess your workspace's exact component labels.
# Instead it queries Neo4j at runtime for whatever Applications,
# Objectives and People already exist in the target workspace, then
# wires new sample components to THOSE real nodes — so it's safe to
# run against any workspace, and idempotent (safe to re-run; it MERGEs
# on a deterministic id, so re-running updates rather than duplicates).
#
# Usage:
#   pip install -r requirements.txt      # if not already done
#   cp .env.example .env                 # fill in your Aura creds
#   python enrich_workspace.py "ZappyWorks"
#   python enrich_workspace.py "ZappyWorks" --wipe   # remove prior enrichment first
#
# After running, reload the dashboard for that workspace
# (…/?workspace=ZappyWorks) — Product Hosting, Application Risk,
# Capability Realization, OKRs/Initiatives, Strategies to Epics, etc.
# should now show real, non-empty graphs.
# =====================================================================
import os, sys, json, re
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wipe = "--wipe" in sys.argv
    ws = args[0] if args else "ZappyWorks"

    uri, user, pwd = os.getenv("NEO4J_URI"), os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")
    if not uri or not pwd:
        sys.exit("Missing NEO4J_URI / NEO4J_PASSWORD (set them in .env).")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    wsid = slug(ws)

    with driver.session() as s:
        if wipe:
            print(f"Wiping prior enrichment for workspace '{ws}' ...")
            s.run("MATCH (c:Component) WHERE c.workspace=$ws AND c.id STARTS WITH $prefix DETACH DELETE c",
                  ws=ws, prefix=f"enr-{wsid}-")

        def existing(type_):
            rows = s.run("MATCH (c:Component) WHERE coalesce(c.workspace,'Zoho Corporation')=$ws AND c.type=$t "
                         "RETURN c.id AS id, c.label AS label ORDER BY c.label", ws=ws, t=type_)
            return [{"id": r["id"], "label": r["label"]} for r in rows]

        apps = existing("Application")
        objs = existing("Objective")
        people = existing("Person")
        if not apps:
            sys.exit(f"No Application components found in workspace '{ws}'. Nothing to attach enrichment to — "
                      f"check the workspace name (case-sensitive) matches what's in the dashboard's workspace selector.")

        print(f"Found in '{ws}': {len(apps)} Application(s), {len(objs)} Objective(s), {len(people)} Person(s).")

        def nid(label):
            return f"enr-{wsid}-{slug(label)}"

        def upsert_node(label, type_, **fields):
            fields = {"Name": label, **fields}
            s.run("""MERGE (c:Component {id:$id}) SET c.label=$label, c.type=$type, c.workspace=$ws,
                     c.name=$label, c.fields=$fields""",
                  id=nid(label), label=label, type=type_, ws=ws, fields=json.dumps(fields, ensure_ascii=False))
            s.run(f"MATCH (c:Component {{id:$id}}) SET c:{re.sub(r'[^A-Za-z0-9]', '', type_)}", id=nid(label))
            return nid(label)

        def link(s_id, ref, t_id):
            rel = re.sub(r"[^A-Z0-9]+", "_", ref.upper())
            eid = f"e-{s_id}-{rel}-{t_id}"
            s.run(f"""MATCH (a:Component {{id:$s}}) MATCH (b:Component {{id:$t}})
                      MERGE (a)-[x:{rel} {{id:$eid}}]->(b) SET x.ref=$ref""",
                  s=s_id, t=t_id, eid=eid, ref=ref)

        # ---- Capabilities, realized by the existing Applications (round-robin) ----
        cap_names = ["Product Development", "Customer Engagement", "Revenue Operations", "Platform Reliability"]
        cap_ids = [upsert_node(n, "Capability", Description=f"{n} capability for {ws}.") for n in cap_names]
        for i, a in enumerate(apps):
            link(cap_ids[i % len(cap_ids)], "Is Realized By", a["id"])
        for i, o in enumerate(objs):
            link(o["id"], "Enabled By", cap_ids[i % len(cap_ids)])
        print(f"  + {len(cap_ids)} Capability nodes, realized by {len(apps)} existing Application(s)")

        # ---- Risks affecting existing Applications + the new Capabilities ----
        risk_defs = [
            ("Key Person Dependency Risk", "High", "Medium"),
            ("Customer Data Security Risk", "Critical", "Low"),
            ("Platform Scalability Risk", "Medium", "High"),
        ]
        risk_ids = []
        for i, (name, sev, lik) in enumerate(risk_defs):
            rid = upsert_node(name, "Risk", Severity=sev, Likelihood=lik)
            risk_ids.append(rid)
            link(rid, "Affects", apps[i % len(apps)]["id"])
            link(rid, "Affects", cap_ids[i % len(cap_ids)])
        print(f"  + {len(risk_ids)} Risk nodes")

        # ---- Initiatives supporting existing Objectives, mitigating the Risks,
        #      led by existing People, impacting the new Capabilities ----
        init_defs = ["Customer Trust & Security Program", "Scale-Up Infrastructure Initiative", "Growth Acceleration Initiative"]
        init_ids = []
        for i, name in enumerate(init_defs):
            iid = upsert_node(name, "Initiative", Status="In Progress")
            init_ids.append(iid)
            if objs:
                link(iid, "Supports", objs[i % len(objs)]["id"])
            link(cap_ids[i % len(cap_ids)], "Impacted By", iid)
            link(iid, "Mitigates", risk_ids[i % len(risk_ids)])
            if people:
                link(people[i % len(people)]["id"], "Leads", iid)
        print(f"  + {len(init_ids)} Initiative nodes")

        # ---- Compliance domains the existing Applications comply with ----
        comp_defs = ["SOC 2", "GDPR"]
        comp_ids = [upsert_node(n, "Compliance", Region="Global") for n in comp_defs]
        for i, a in enumerate(apps):
            link(a["id"], "Complies With", comp_ids[i % len(comp_ids)])
        print(f"  + {len(comp_ids)} Compliance nodes")

        # ---- Technology + Location, so Product Hosting / Products to Location work ----
        tech_id = upsert_node(f"{ws} Cloud Platform", "Technology", Provider="AWS")
        loc_ids = [upsert_node(n, "Location", Type="Data Center") for n in [f"{ws} Primary Region", f"{ws} DR Region"]]
        for a in apps:
            link(a["id"], "Is Supported By", tech_id)
        link(tech_id, "Is Located At", loc_ids[0])
        print(f"  + 1 Technology node + {len(loc_ids)} Location nodes, supporting all {len(apps)} Application(s)")

        # ---- OrgUnit(s), consuming existing Applications, home to existing People ----
        org_id = upsert_node(f"{ws} Product & Engineering", "OrgUnit", Description="Owns the product and platform.")
        for a in apps:
            link(org_id, "Consumes", a["id"])
        for p in people:
            link(p["id"], "Belongs To", org_id)
        print(f"  + 1 OrgUnit node")

        # ---- Strategy -> Epics -> Capability / Application ----
        strat_id = upsert_node(f"{ws} Growth Strategy", "Strategy", Horizon="FY26-FY27")
        epic_defs = ["Harden Security & Compliance", "Expand Platform Capacity"]
        for i, name in enumerate(epic_defs):
            eid = upsert_node(name, "Epic", Status="Planned")
            link(strat_id, "Delivers", eid)
            link(eid, "Delivers", cap_ids[i % len(cap_ids)])
            link(eid, "Delivers", apps[i % len(apps)]["id"])
        print(f"  + 1 Strategy node + {len(epic_defs)} Epic nodes")

        total = s.run("MATCH (c:Component) WHERE coalesce(c.workspace,'Zoho Corporation')=$ws RETURN count(c) AS n", ws=ws).single()["n"]
        print(f"\nDone. Workspace '{ws}' now holds {total} components total.")
        print(f"Reload: <your-app>.onrender.com/?workspace={ws.replace(' ', '%20')}")

    driver.close()


if __name__ == "__main__":
    main()
