# =====================================================================
# github_sync.py  —  Python GitHub -> Neo4j ingestion (separate tool).
# Maps GitHub into the metamodel: org->Org Unit, GitHub->Tech Service,
# repo->Application, owner->Person, with metamodel-valid references.
#
#   python github_sync.py <org-or-user> [maxRepos]
# or via API: POST /api/github/sync {"org":"...","maxRepos":30}
# =====================================================================
import os, re, sys, json, requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
GH = "https://api.github.com"
REF_TO_REL = {
    "Owns": "OWNS", "Belongs To": "BELONGS_TO", "Consumes": "CONSUMES",
    "Is Supported By": "IS_SUPPORTED_BY",
}
def ref_to_rel(r): return REF_TO_REL.get(r) or re.sub(r"[^A-Z0-9]+", "_", r.upper())
def type_to_label(t): return re.sub(r"[^A-Za-z0-9]", "", t)

def _driver():
    return GraphDatabase.driver(os.getenv("NEO4J_URI"),
                                auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")))

def _get(url, token):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "zoho-ea-poc"}
    if token: h["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=h, timeout=30)
    r.raise_for_status()
    return r.json()

def _fetch_repos(login, token, max_repos):
    try:
        repos = _get(f"{GH}/orgs/{login}/repos?per_page=100&sort=updated", token)
    except Exception:
        repos = _get(f"{GH}/users/{login}/repos?per_page=100&sort=updated", token)
    return repos[:max_repos]

def _upsert_component(s, cid, label, ctype, f):
    s.run("""MERGE (c:Component {id:$id})
             SET c.label=$label, c.type=$type, c.name=$name, c.description=$desc,
                 c.lifecycle=$life, c.fields=$fields""",
          id=cid, label=label, type=ctype, name=f.get("Name", label),
          desc=f.get("Description", ""), life=f.get("Lifecycle Phase", "Live"),
          fields=__import__("json").dumps(f, ensure_ascii=False))
    s.run(f"MATCH (c:Component {{id:$id}}) SET c:{type_to_label(ctype)}", id=cid)

def _upsert_ref(s, src, tgt, ref):
    eid = f"gh_{src}__{ref_to_rel(ref)}__{tgt}"
    s.run(f"""MATCH (a:Component {{id:$s}}) MATCH (b:Component {{id:$t}})
              MERGE (a)-[r:{ref_to_rel(ref)} {{id:$eid}}]->(b) SET r.ref=$ref""",
          s=src, t=tgt, eid=eid, ref=ref)

def sync_org(login, token=None, max_repos=30):
    """Batched GitHub -> Neo4j ingest. Builds all rows first, then writes in a
    handful of UNWIND queries so it stays well under the tool timeout."""
    token = token or os.getenv("GITHUB_TOKEN")
    ws = f"GitHub: {login}"
    repos = _fetch_repos(login, token, max_repos)

    def cf(cid, label, ctype, f):
        return {"id": cid, "label": label, "type": ctype,
                "fields": json.dumps(f, ensure_ascii=False)}

    comps = [
        cf("gh_service", "GitHub", "Tech Service",
           {"Name": "GitHub", "Server Hosting": "Cloud — GitHub", "Lifecycle Phase": "Live",
            "Description": "Source code hosting & CI (github.com)"}),
        cf(f"gh_org_{login}", f"GitHub: {login}", "Org Unit",
           {"Name": f"{login} (GitHub organisation)",
            "Description": f"Repositories synced from github.com/{login}", "Source": "GitHub sync"}),
    ]
    org_id = f"gh_org_{login}"
    refs, seen = [], set()
    for repo in repos:
        app_id = f"gh_repo_{login}_{repo['name']}"
        comps.append(cf(app_id, repo["name"], "Application", {
            "Name": repo["full_name"], "App Type": "GitHub Repository",
            "Lifecycle Phase": "Retired" if repo.get("archived") else "Live",
            "Service Level": "Public" if not repo.get("private") else "Internal",
            "Language": repo.get("language") or "n/a",
            "Stars": str(repo.get("stargazers_count", 0)),
            "Forks": str(repo.get("forks_count", 0)),
            "Open Issues": str(repo.get("open_issues_count", 0)),
            "URL": repo.get("html_url", ""), "Updated At": repo.get("updated_at", ""),
            "Description": repo.get("description") or "", "Note": "Ingested from GitHub."}))
        refs.append({"s": org_id, "t": app_id, "ref": "Consumes"})
        refs.append({"s": app_id, "t": "gh_service", "ref": "Is Supported By"})
        owner = (repo.get("owner") or {}).get("login")
        if owner:
            pid = f"gh_person_{owner}"
            if pid not in seen:
                comps.append(cf(pid, owner, "Person",
                               {"Name": owner, "Role": "GitHub owner/maintainer",
                                "Contact Email": f"{owner}@users.noreply.github.com",
                                "Status": "Imported from GitHub"}))
                seen.add(pid)
            refs.append({"s": pid, "t": app_id, "ref": "Owns"})

    driver = _driver()
    made = 0
    with driver.session() as s:
        # 1) all components in one query
        s.run("""UNWIND $rows AS r MERGE (c:Component {id:r.id})
                 SET c.label=r.label, c.type=r.type, c.name=r.label,
                     c.workspace=$ws, c.fields=r.fields""", rows=comps, ws=ws)
        # 2) type labels, one query per distinct type (scoped to this workspace)
        for t in {c["type"] for c in comps}:
            s.run(f"MATCH (c:Component {{type:$t, workspace:$ws}}) SET c:{type_to_label(t)}", t=t, ws=ws)
        # 3) references, one query per reference type
        by_ref = {}
        for e in refs:
            by_ref.setdefault(e["ref"], []).append(e)
        for ref, group in by_ref.items():
            rel = ref_to_rel(ref)
            for g in group:
                g["eid"] = f"gh_{g['s']}__{rel}__{g['t']}"
            res = s.run(f"""UNWIND $rows AS r MATCH (a:Component {{id:r.s}}) MATCH (b:Component {{id:r.t}})
                            MERGE (a)-[x:{rel} {{id:r.eid}}]->(b) SET x.ref=$ref RETURN count(x) AS n""",
                        rows=group, ref=ref)
            made += res.single()["n"]
    driver.close()
    return {"login": login, "workspace": ws, "reposSynced": len(repos),
            "componentsUpserted": len(comps), "referencesCreated": made,
            "dashboardUrl": f"/?workspace={ws}"}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python github_sync.py <org-or-user> [maxRepos]")
    print(sync_org(sys.argv[1], max_repos=int(sys.argv[2]) if len(sys.argv) > 2 else 30))
