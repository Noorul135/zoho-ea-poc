// =====================================================================
// 01-constraints.cypher
// Run this FIRST, once, in the Neo4j Aura "Query" console (or via cypher-shell).
// It guarantees every EA component has a unique id and speeds up lookups.
// Safe to re-run (IF NOT EXISTS).
// =====================================================================

// Every Enterprise-Architecture component carries the shared label :Component
// plus a specific type label (e.g. :Application). id is the business key.
CREATE CONSTRAINT component_id IF NOT EXISTS
FOR (c:Component) REQUIRE c.id IS UNIQUE;

// Metamodel definition nodes (the "schema" of the graph itself).
CREATE CONSTRAINT ctype_name IF NOT EXISTS
FOR (t:MetaComponentType) REQUIRE t.name IS UNIQUE;

CREATE CONSTRAINT rtype_name IF NOT EXISTS
FOR (r:MetaReferenceType) REQUIRE r.name IS UNIQUE;

// Helpful secondary indexes for search / filtering.
CREATE INDEX component_type IF NOT EXISTS FOR (c:Component) ON (c.type);
CREATE INDEX component_name IF NOT EXISTS FOR (c:Component) ON (c.name);

// Show what was created.
SHOW CONSTRAINTS;
