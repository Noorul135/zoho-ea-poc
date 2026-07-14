# =====================================================================
# github_sync.py  —  Python GitHub -> Neo4j ingestion (separate tool).
# Maps GitHub into the metamodel: org->Org Unit, GitHub->Tech Service,
# repo->Application, owner->Person, with metamodel-valid references.
#
#   python github_sync.py <org-or-user> [maxRepos]
# or via API: POST /api/github/sync {"org":"...","maxRepos":30}
# =====================================================================
import os, re, sys, requests
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
    token = token or os.getenv("GITHUB_TOKEN")
    created = {"orgUnit": 0, "apps": 0, "persons": 0, "refs": 0}
    driver = _driver()
    with driver.session() as s:
        _upsert_component(s, "gh_service", "GitHub", "Tech Service", {
            "Name": "GitHub", "Server Hosting": "Cloud — GitHub", "Deploy Env": "Production",
            "Lifecycle Phase": "Live", "Description": "Source code hosting & CI (github.com)"})
        org_id = f"gh_org_{login}"
        _upsert_component(s, org_id, f"GitHub: {login}", "Org Unit", {
            "Name": f"{login} (GitHub organisation)",
            "Description": f"Repositories synced from github.com/{login}", "Source": "GitHub sync"})
        created["orgUnit"] += 1
        orgs = s.run("MATCH (o:Organization) RETURN o.id AS id LIMIT 1").single()
        if orgs:
            _upsert_ref(s, org_id, orgs["id"], "Belongs To"); created["refs"] += 1

        repos = _fetch_repos(login, token, max_repos)
        seen = set()
        for repo in repos:
            app_id = f"gh_repo_{login}_{repo['name']}"
            _upsert_component(s, app_id, repo["name"], "Application", {
                "Name": repo["full_name"], "App Type": "GitHub Repository",
                "Lifecycle Phase": "Retired" if repo.get("archived") else "Live",
                "Service Level": "Public" if not repo.get("private") else "Internal",
                "Language": repo.get("language") or "n/a",
                "Stars": str(repo.get("stargazers_count", 0)),
                "Forks": str(repo.get("forks_count", 0)),
                "Open Issues": str(repo.get("open_issues_count", 0)),
                "Default Branch": repo.get("default_branch", ""),
                "URL": repo.get("html_url", ""), "Updated At": repo.get("updated_at", ""),
                "Description": repo.get("description") or "",
                "Note": "Ingested from GitHub via github_sync tool."})
            created["apps"] += 1
            _upsert_ref(s, org_id, app_id, "Consumes"); created["refs"] += 1
            _upsert_ref(s, app_id, "gh_service", "Is Supported By"); created["refs"] += 1
            owner = (repo.get("owner") or {}).get("login")
            if owner:
                pid = f"gh_person_{owner}"
                if pid not in seen:
                    _upsert_component(s, pid, owner, "Person", {
                        "Name": owner, "Role": "GitHub owner/maintainer",
                        "Contact Email": f"{owner}@users.noreply.github.com",
                        "Status": "Imported from GitHub"})
                    seen.add(pid); created["persons"] += 1
                _upsert_ref(s, pid, app_id, "Owns"); created["refs"] += 1
    driver.close()
    return {"login": login, "reposSynced": len(repos), "created": created}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python github_sync.py <org-or-user> [maxRepos]")
    print(sync_org(sys.argv[1], max_repos=int(sys.argv[2]) if len(sys.argv) > 2 else 30))
