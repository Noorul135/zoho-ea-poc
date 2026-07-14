// =====================================================================
// 02-metamodel.cypher
// The META MODEL = the schema of the Enterprise Intelligence Graph.
// It defines (a) the allowed COMPONENT TYPES, (b) the allowed REFERENCE
// (relationship) TYPES, and (c) which component type may connect to which,
// and via which reference. This mirrors Ardoq's foundation metamodel.
// Run this SECOND, once. Safe to re-run (MERGE).
// =====================================================================

// ---------- (a) COMPONENT TYPES -------------------------------------
// tier is used by the dashboard's "Concentric (by tier)" + layered views.
UNWIND [
  {name:'Organization',        tier:1, category:'Organization', shape:'roundrectangle', color:'#E8212A'},
  {name:'Org Unit',            tier:2, category:'Organization', shape:'roundrectangle', color:'#185FA5'},
  {name:'Business Capability', tier:3, category:'Business',     shape:'roundrectangle', color:'#993C1D'},
  {name:'Person',              tier:4, category:'Organization', shape:'ellipse',        color:'#3B6D11'},
  {name:'Application',         tier:5, category:'Application',  shape:'roundrectangle', color:'#085041'},
  {name:'App Module',          tier:6, category:'Application',  shape:'roundrectangle', color:'#1D9E75'},
  {name:'Interface',           tier:7, category:'Application',  shape:'roundrectangle', color:'#854F0B'},
  {name:'Data Store',          tier:7, category:'Data',         shape:'roundrectangle', color:'#BA7517'},
  {name:'Server',              tier:8, category:'Technology',   shape:'roundrectangle', color:'#444441'},
  {name:'Tech Service',        tier:8, category:'Technology',   shape:'roundrectangle', color:'#378ADD'},
  {name:'Tech Product',        tier:9, category:'Technology',   shape:'roundrectangle', color:'#888780'},
  {name:'Location',            tier:10,category:'Other',        shape:'roundrectangle', color:'#993556'}
] AS ct
MERGE (t:MetaComponentType {name:ct.name})
SET t.tier=ct.tier, t.category=ct.category, t.shape=ct.shape, t.color=ct.color;

// ---------- (b) REFERENCE TYPES -------------------------------------
// relType = the sanitised Neo4j relationship type actually stored on edges.
UNWIND [
  {name:'Owns',            relType:'OWNS',            color:'#3B6D11'},
  {name:'Is Expert In',    relType:'IS_EXPERT_IN',    color:'#1D9E75'},
  {name:'Belongs To',      relType:'BELONGS_TO',      color:'#888780'},
  {name:'Reports To',      relType:'REPORTS_TO',      color:'#5F5E5A'},
  {name:'Consumes',        relType:'CONSUMES',        color:'#185FA5'},
  {name:'Is Realized By',  relType:'IS_REALIZED_BY',  color:'#993C1D'},
  {name:'Is Supported By', relType:'IS_SUPPORTED_BY', color:'#444441'},
  {name:'Connects To',     relType:'CONNECTS_TO',     color:'#085041'},
  {name:'Has Successor',   relType:'HAS_SUCCESSOR',   color:'#BA7517'},
  {name:'Deploys To',      relType:'DEPLOYS_TO',      color:'#534AB7'},
  {name:'Is Located At',   relType:'IS_LOCATED_AT',   color:'#993556'},
  {name:'Child Of',        relType:'CHILD_OF',        color:'#b4b2a9'},
  {name:'Module Of',       relType:'MODULE_OF',       color:'#97C459'}
] AS rt
MERGE (r:MetaReferenceType {name:rt.name})
SET r.relType=rt.relType, r.color=rt.color;

// ---------- (c) ALLOWED CONNECTIONS ---------------------------------
// (:MetaComponentType)-[:ALLOWS {ref}]->(:MetaComponentType)
// This is the "which can connect to what" rule set. The API validates
// every new reference against these rules before writing it.
UNWIND [
  {from:'Org Unit',            ref:'Belongs To',      to:'Organization'},
  {from:'Person',              ref:'Belongs To',      to:'Org Unit'},
  {from:'Person',              ref:'Reports To',      to:'Person'},
  {from:'Person',              ref:'Owns',            to:'Org Unit'},
  {from:'Person',              ref:'Owns',            to:'Application'},
  {from:'Person',              ref:'Owns',            to:'Interface'},
  {from:'Person',              ref:'Owns',            to:'Server'},
  {from:'Person',              ref:'Is Expert In',    to:'Business Capability'},
  {from:'Person',              ref:'Is Expert In',    to:'Application'},
  {from:'Person',              ref:'Is Expert In',    to:'Interface'},
  {from:'Org Unit',            ref:'Consumes',        to:'Application'},
  {from:'Org Unit',            ref:'Owns',            to:'Server'},
  {from:'Business Capability', ref:'Is Realized By',  to:'Application'},
  {from:'Business Capability', ref:'Is Realized By',  to:'Org Unit'},
  {from:'Business Capability', ref:'Child Of',        to:'Business Capability'},
  {from:'Application',         ref:'Is Supported By', to:'Server'},
  {from:'Application',         ref:'Is Supported By', to:'Tech Service'},
  {from:'Application',         ref:'Connects To',     to:'Interface'},
  {from:'Application',         ref:'Has Successor',   to:'Application'},
  {from:'App Module',          ref:'Module Of',       to:'Application'},
  {from:'App Module',          ref:'Connects To',     to:'Interface'},
  {from:'App Module',          ref:'Is Supported By', to:'Server'},
  {from:'Interface',           ref:'Connects To',     to:'Application'},
  {from:'Data Store',          ref:'Module Of',       to:'Application'},
  {from:'Data Store',          ref:'Is Supported By', to:'Server'},
  {from:'Server',              ref:'Is Located At',   to:'Location'},
  {from:'Server',              ref:'Is Supported By', to:'Tech Service'},
  {from:'Tech Service',        ref:'Is Located At',   to:'Location'},
  {from:'Tech Product',        ref:'Deploys To',      to:'Server'},
  {from:'Tech Product',        ref:'Deploys To',      to:'Tech Service'}
] AS rule
MATCH (a:MetaComponentType {name:rule.from})
MATCH (b:MetaComponentType {name:rule.to})
MERGE (a)-[x:ALLOWS {ref:rule.ref}]->(b);

// Verify the metamodel.
MATCH (a:MetaComponentType)-[x:ALLOWS]->(b:MetaComponentType)
RETURN a.name AS from, x.ref AS reference, b.name AS to
ORDER BY from, reference, to;
