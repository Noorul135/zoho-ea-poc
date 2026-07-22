// =====================================================================
// 03-viewpoints-metamodel.cypher
// Additive metamodel extension that backs the new "Viewpoint" dropdown
// on the dashboard (see public/index.html, VIEWPOINTS config).
//
// It does NOT touch anything defined in 01-constraints.cypher or
// 02-metamodel.cypher — it only MERGEs new component types, new
// reference types, and new allowed triples on top of them, following
// the same Ardoq-style "chain of triples" model documented at
// https://help.ardoq.com/en/articles/43962 and 43959.
//
// New component types:  Objective, KPI, Initiative, Risk, Compliance,
//                        Epic, Strategy
// New reference types:  Enabled By, Measured By, Supports, Impacted By,
//                        Affects, Mitigates, Complies With, Delivers, Leads
//
// Run this AFTER 01-constraints.cypher and 02-metamodel.cypher, once.
// Safe to re-run (MERGE).
// =====================================================================

// ---------- (a) NEW COMPONENT TYPES ----------------------------------
UNWIND [
  {name:'Objective',  tier:11, category:'Strategy',    shape:'roundrectangle', color:'#7A1FA2'},
  {name:'KPI',        tier:12, category:'Performance',  shape:'roundrectangle', color:'#0F9D9D'},
  {name:'Initiative', tier:11, category:'Actions',      shape:'roundrectangle', color:'#534AB7'},
  {name:'Risk',       tier:13, category:'Risk',         shape:'diamond',        color:'#C41019'},
  {name:'Compliance', tier:13, category:'Governance',   shape:'roundrectangle', color:'#72243E'},
  {name:'Strategy',   tier:10, category:'Strategy',     shape:'roundrectangle', color:'#3B6D11'},
  {name:'Epic',       tier:11, category:'Actions',      shape:'roundrectangle', color:'#BA7517'}
] AS ct
MERGE (t:MetaComponentType {name:ct.name})
SET t.tier=ct.tier, t.category=ct.category, t.shape=ct.shape, t.color=ct.color;

// ---------- (b) NEW REFERENCE TYPES -----------------------------------
UNWIND [
  {name:'Enabled By',    relType:'ENABLED_BY',    color:'#7A1FA2'},
  {name:'Measured By',   relType:'MEASURED_BY',   color:'#0F9D9D'},
  {name:'Supports',      relType:'SUPPORTS',      color:'#534AB7'},
  {name:'Impacted By',   relType:'IMPACTED_BY',   color:'#534AB7'},
  {name:'Affects',       relType:'AFFECTS',       color:'#C41019'},
  {name:'Mitigates',     relType:'MITIGATES',     color:'#3B6D11'},
  {name:'Complies With', relType:'COMPLIES_WITH', color:'#72243E'},
  {name:'Delivers',      relType:'DELIVERS',      color:'#BA7517'},
  {name:'Leads',         relType:'LEADS',         color:'#185FA5'}
] AS rt
MERGE (r:MetaReferenceType {name:rt.name})
SET r.relType=rt.relType, r.color=rt.color;

// ---------- (c) NEW ALLOWED TRIPLES -----------------------------------
// Each row is a (from, reference, to) triple — the same "chain" concept
// Ardoq uses to build a Viewpoint model.
UNWIND [
  {from:'Objective',            ref:'Enabled By',    to:'Business Capability'},
  {from:'Objective',            ref:'Measured By',   to:'KPI'},
  {from:'Initiative',           ref:'Supports',      to:'Objective'},
  {from:'Business Capability',  ref:'Impacted By',   to:'Initiative'},
  {from:'Risk',                 ref:'Affects',       to:'Application'},
  {from:'Risk',                 ref:'Affects',       to:'Business Capability'},
  {from:'Initiative',           ref:'Mitigates',     to:'Risk'},
  {from:'Application',          ref:'Complies With', to:'Compliance'},
  {from:'Strategy',             ref:'Delivers',      to:'Epic'},
  {from:'Epic',                 ref:'Delivers',      to:'Business Capability'},
  {from:'Epic',                 ref:'Delivers',      to:'Application'},
  {from:'Person',               ref:'Leads',         to:'Initiative'}
] AS rule
MATCH (a:MetaComponentType {name:rule.from})
MATCH (b:MetaComponentType {name:rule.to})
MERGE (a)-[x:ALLOWS {ref:rule.ref}]->(b);

// Verify.
MATCH (a:MetaComponentType)-[x:ALLOWS]->(b:MetaComponentType)
WHERE a.name IN ['Objective','Initiative','Business Capability','Risk','Application','Strategy','Epic','Person']
   OR b.name IN ['Objective','KPI','Initiative','Risk','Compliance','Epic','Strategy']
RETURN a.name AS from, x.ref AS reference, b.name AS to
ORDER BY from, reference, to;
