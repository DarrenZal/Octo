# Ontological Architecture

*How the BKC knowledge commons honors diverse ways of knowing while enabling cross-bioregional pattern mining.*

**Related documents:**
- [Strategy: Holonic Bioregional Knowledge Commons](./holonic-bioregional-knowledge-commons.md)
- [Implementation Plan](./implementation-plan.md)

---

## 1. The Core Tension

The BKC project needs a shared vocabulary for pattern mining to work. Practices can only `aggregates_into` patterns across bioregions if the agents share enough common structure to recognize similarity. But the project also commits to **ontological pluriversality** — honoring diverse ontologies that center relationality and the commons, rather than universalizing any single framework.

These are not contradictory if the BKC ontology is positioned correctly.

### The Three Foundational Commitments

From the BKC CoIP proposal:

> **Knowledge sovereignty:** Who "owns" knowledge and how access is governed matters, especially given power imbalances and information weaponization.

> **Epistemic justice:** Respect for diverse epistemologies, recognition of the violence and unsustainability of modernity/coloniality.

> **Ontological pluriversality:** Rather than universalizing colonialist ontologies that center state and market reductionism, we need to recognize diverse ontologies that center relationality and the commons.

These commitments are interdependent. Knowledge sovereignty requires that each community controls how their knowledge is organized, not just who can access it. Epistemic justice means not forcing knowledge into categories that erase its context. Ontological pluriversality means the system itself must support multiple ways of organizing reality.

The technical architecture must embody all three.

---

## 2. The BKC Ontology as Lingua Franca

The BKC ontology (15 entity types, 27 predicates) should be positioned as a **bridge language** — a shared vocabulary for cross-bioregional communication, not a claim about how reality is organized.

The analogy is natural language translation. English serves as a lingua franca for international science — not because it is the best or most nuanced language, but because having a shared medium enables connection. Each community still speaks its own language internally. The act of translation is acknowledged as imperfect — something is always lost, something is always gained. But the alternative (no communication at all, or forced adoption of one language) is worse.

The BKC ontology works the same way:

| Aspect | What the ontology IS | What the ontology IS NOT |
|--------|---------------------|------------------------|
| **Function** | A bridge for cross-bioregional pattern mining | The one true way to organize knowledge |
| **Scope** | Minimum shared vocabulary for interoperability | Comprehensive model of all possible knowledge |
| **Authority** | Community-governed and evolvable | Fixed and imposed |
| **Relationship to sources** | One lens among many | The lens that replaces all others |

### Why a Bridge Language Is Needed

Without some shared structure, cross-bioregional pattern mining is impossible. If the Salish Sea agent organizes knowledge by "practices" and the Devon agent organizes by "land-based activities" and the Barichara agent organizes by "modos de vida," they cannot discover that they are all documenting instances of the same pattern — unless there is a shared vocabulary in which similarity can be computed.

The BKC ontology provides this. Its 15 entity types (Practice, Pattern, CaseStudy, Bioregion, etc.) and 27 predicates (aggregates_into, suggests, practiced_in, etc.) are the **minimum shared structure** needed for the `aggregates_into` / `suggests` cycle to operate across bioregions.

### How This Aligns with the Holon Pattern

The KOI-net architecture already supports this model:

- **Each node has its own internal knowledge organization.** The vault parser, entity types, and relationship conventions can vary per node.
- **The protocol layer provides shared vocabulary.** RIDs, events, and manifests use a common format regardless of internal differences.
- **Edge profiles control what flows between nodes.** Each node decides what to share in what format.
- **The holon boundary hides internal complexity.** A node's external interface presents a coherent view; internal diversity is invisible to peers.

The bridge ontology lives at the **edge** — where knowledge crosses between nodes. Internally, each node can organize knowledge however makes sense for its community. At the boundary, the shared vocabulary enables communication.

---

## 3. Three Ingestion Modes

Knowledge enters the system through three distinct paths, each requiring different handling:

### Mode 1: Unstructured → Structured (Extraction)

**The most common case.** Read a document, interview transcript, web page, or field note. Extract entities and relationships using the BKC ontology. The source has no explicit schema — the agent imposes one.

**Example:** A field report on salmon monitoring in the Cowichan River. The agent reads the text and identifies: a Practice (community salmon monitoring), a Bioregion (Cowichan Valley), People (participants), an Organization (Cowichan Tribes), and relationships (practiced_in, involves_person, involves_organization).

**Key principle:** Be transparent that the extraction is an interpretation. "These are entities we identified according to the BKC ontology" — not "this is what the source really means." Store the original source text alongside the extracted structure.

**Metadata preserved:**
- Original source document (full text or reference)
- Extraction method (AI extraction, manual annotation, automated parser)
- Extraction date and agent identity
- Confidence/certainty where applicable

### Mode 2: Structured → Structured (Mapping)

**When the source has its own schema.** The BKC CoIP Obsidian vault is the immediate case — 59 case studies and 57 organization profiles with YAML frontmatter using the BKC CoIP's own conventions.

**Example:** A BKC CoIP organization file:
```yaml
---
id: accion-serrana
type: organization
category: Bioregional Organizer
website: https://www.accionserrana.com/
description: >
  Acción Serrana focuses on biocultural restoration...
place: Sierras Grandes, Córdoba, Argentina
location:
  - -31.4
  - -64.8
bioregional_context: >
  The Sierras Grandes of Córdoba are part of...
activities:
  - Participatory Forest Restoration
  - Monitoring, Evaluation, and Learning
patterns:
  - Ecosystem_Management_and_Regeneration
  - Ecological_Monitoring
network-affiliation:
  - "[[BioFi Project]]"
status: ✅ Human Edited
---
```

Some fields map cleanly to BKC ontology. Others don't. The three-layer architecture (Section 5) handles this.

**Key principles:**
1. **Preserve the full source structure** — never throw away the original schema
2. **Map what you can** — create explicit, human-reviewed mappings to BKC ontology
3. **Flag what you can't** — unmapped fields are preserved and surfaced for review
4. **Never auto-apply mappings** — mappings are proposals until a human approves them

### Mode 3: Federated (Node-to-Node)

**When knowledge arrives from another KOI-net node.** The other node has its own ontology, potentially different from BKC. Edge profiles and the handler pipeline negotiate what flows and how.

**Example:** A bioregional agent in Devon uses entity types like "Land-Based Activity" (their equivalent of Practice) and predicates like "situated_in" (their equivalent of practiced_in). When their coordinator shares knowledge with a Cascadia node, the receiving node's RID handler and bundle handler must decide: is this something we can map? Should we store it in our ontology or preserve it in theirs?

**Key principles:**
- Each node declares its ontology in its `NodeProfile`
- Edge negotiation can include ontology translation rules
- Knowledge that doesn't translate stays at the source node (this is a feature, not a bug)
- The shared bridge vocabulary is the minimum needed for cross-network pattern mining

---

## 4. The Agent's Ontology Skillset

The agent should have the capability to work with diverse ontologies — but always with human-in-the-loop at the mapping step. This is not an autocomplete function; it is a perception and proposal function.

### What the Agent SHOULD Do

**1. Detect structure.** When incoming data has explicit schema (YAML frontmatter, JSON-LD, RDF, CSV headers, structured databases), the agent recognizes it rather than treating it as unstructured text.

**2. Profile the schema.** Generate a schema profile for human review:
- Fields present (names, types, cardinality)
- Example values for each field
- Statistical summary (which fields are always present, which are optional)
- Detected patterns (wikilinks, URIs, controlled vocabularies)

**3. Suggest mappings.** Use semantic similarity to propose mappings from source schema to BKC ontology:
- "Their `activities` field contains values like 'Participatory Forest Restoration' — this looks like a list of `Practice` references"
- "Their `patterns` field uses underscore-separated names — these map to `Pattern` entities with name normalization"
- "Their `category` field has no equivalent in BKC ontology — suggest storing in `source_metadata`"

**4. Flag gaps.** Identify source concepts that don't map to the BKC ontology, and surface these as potential ontology extension proposals:
- "The field `category` appears in 57/57 organizations with values: 'Bioregional Organizer' (34), 'Learning Network' (12), 'Indigenous Alliance' (5), 'Support Organization' (6). No BKC ontology equivalent exists. Consider adding an `organizational_role` property or entity subtype?"

**5. Preserve originals.** Always store the full source structure alongside any BKC mapping. The source data is never modified or reduced during ingestion.

**6. Track provenance.** Record: who contributed this data, when, through what channel, with what permissions, using what schema, mapped by whom, approved by whom.

### What the Agent Should NOT Do

- **Auto-apply mappings without human review.** The mapping from one ontology to another encodes interpretive choices that should be explicit and accountable. Note: the Phase 1 markdown sensor *does* apply mappings programmatically — but only mappings that were human-reviewed and approved during Phase 0.5. The sensor applies pre-approved mappings, not auto-generated ones. If a new source arrives with an unknown schema, the sensor flags it for review rather than guessing.
- **Assume BKC ontology is "correct" and the source is "wrong."** Both are valid ways of organizing knowledge. The mapping is a bridge, not a correction.
- **Strip away source structure that doesn't map.** Unmapped fields may be deeply meaningful in the source community's context.
- **Treat unmapped concepts as noise.** They may signal gaps in the BKC ontology or genuine incommensurability between frameworks.
- **Automatically extend the ontology.** Extensions should go through community governance — the agent proposes, humans decide.

---

## 5. Three-Layer Architecture

Every piece of ingested knowledge exists in three layers simultaneously:

```
┌──────────────────────────────────────────┐
│         COMMONS LAYER (BKC ontology)     │
│   Practices, Patterns, aggregates_into   │
│   — the shared vocabulary for pattern    │
│     mining across bioregions             │
├──────────────────────────────────────────┤
│         MAPPING LAYER (human-reviewed)   │
│   source_field → bkc_predicate           │
│   mapping_type: equivalent/narrower/     │
│     broader/related/unmapped/proposed    │
│   reviewed_by, approved_date, notes      │
├──────────────────────────────────────────┤
│         SOURCE LAYER (preserved as-is)   │
│   Full original YAML/schema/structure    │
│   Source provenance, attribution         │
│   Access permissions, sovereignty flags  │
└──────────────────────────────────────────┘
```

### Source Layer

The complete original data as it arrived, with its own structure and vocabulary. Stored in `source_metadata` (JSONB) on the entity record. This layer is never modified by the mapping process.

Includes:
- Full original YAML frontmatter or structured data
- Source file path or URI
- Source schema reference (which schema this data conforms to)
- Ingestion timestamp and method
- Attribution (who contributed, from what community)
- Access/permission metadata

### Mapping Layer

Explicit, human-reviewed correspondences between source schema elements and BKC ontology concepts. Each mapping has:

- **Source field** — the field name in the source schema
- **BKC target** — the entity type, predicate, or property in BKC ontology
- **Mapping type** — the nature of the correspondence:
  - `equivalent` — direct mapping (source's `type: organization` = BKC `Organization`)
  - `narrower` — source concept is more specific than BKC concept
  - `broader` — source concept is more general than BKC concept
  - `related` — related but not equivalent
  - `unmapped` — no BKC equivalent; preserved in source_metadata only
  - `proposed_extension` — should trigger ontology extension governance
- **Notes** — human explanation of mapping rationale
- **Reviewed by / Approved date** — governance trail
- **Confidence** — how certain the mapping is (for AI-proposed mappings)

The mapping layer makes interpretation explicit. When we say "their `activities` field maps to BKC `Practice` entities," that's an interpretive choice with implications — their "activities" might include things we wouldn't call "Practices." Making the mapping visible means it can be examined, contested, and revised.

### Commons Layer

The BKC ontology representation — entity types, predicates, relationships. This is what participates in cross-bioregional pattern mining. An entity exists in the commons layer only through an explicit mapping from its source representation.

The commons layer is:
- The shared vocabulary for cross-bioregional search and discovery
- The substrate for `aggregates_into` / `suggests` pattern mining
- Governed by the BKC ontology specification (evolvable through community governance)
- Never the only representation — always accompanied by the source layer

**Feedback loop with pattern mining:** The quality and completeness of Phase 0.5/1.1b mappings directly determines the effectiveness of cross-scale pattern mining (Phase 6). An entity only enters the commons layer through an explicit mapping from its source representation. If most source fields are `unmapped`, the commons layer is thin and pattern mining has little to work with. This creates a virtuous cycle: investing in mapping quality during ingestion pays dividends in pattern discovery; discovering useful patterns motivates further mapping work. Monitor the ratio of `equivalent`/`narrower` mappings to `unmapped` fields across source schemas — if a schema has < 30% mapped fields, pattern mining from that source will be limited.

---

## 6. Schema Design

### New Table: `source_schemas`

Records known external data schemas. Each schema describes the structure of a particular data source.

```sql
-- Canonical definition in implementation plan migration 039b_ontology_mappings.sql
CREATE TABLE IF NOT EXISTS source_schemas (
    id SERIAL PRIMARY KEY,
    schema_name TEXT UNIQUE NOT NULL,           -- e.g., "bkc-coip-organizations-v1"
    description TEXT,
    source_community TEXT,                      -- e.g., "BKC CoIP / Andrea Farias"
    source_type TEXT,                           -- "obsidian_yaml", "csv", "json_ld", "rdf"
    field_definitions JSONB NOT NULL DEFAULT '{}',  -- { field_name: { type, required, examples, notes } }
    mapping_status TEXT DEFAULT 'unmapped',     -- unmapped, partial, complete
    consent_status TEXT DEFAULT 'pending',      -- pending, verbal, written, formal_agreement, declined
    consent_details JSONB DEFAULT '{}',
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);
```

**Example entry for BKC CoIP organizations:**
```json
{
  "schema_name": "bkc-coip-organizations-v1",
  "source_community": "BKC CoIP / Andrea Farias",
  "source_type": "obsidian_yaml",
  "field_definitions": {
    "id": {"type": "string", "required": true, "examples": ["accion-serrana"], "notes": "URL-safe identifier"},
    "type": {"type": "string", "required": true, "examples": ["organization"], "notes": "Always 'organization' in this schema"},
    "category": {"type": "string", "required": true, "examples": ["Bioregional Organizer", "Learning Network"], "notes": "No BKC equivalent"},
    "activities": {"type": "string[]", "required": false, "examples": ["Participatory Forest Restoration"], "notes": "Maps to Practice references"},
    "patterns": {"type": "string[]", "required": false, "examples": ["Ecosystem_Management_and_Regeneration"], "notes": "Maps to Pattern references"},
    "place": {"type": "string", "required": true, "examples": ["Sierras Grandes, Córdoba, Argentina"], "notes": "Maps to located_in"},
    "location": {"type": "number[]", "required": false, "examples": [[-31.4, -64.8]], "notes": "lat/lon coordinates"},
    "network-affiliation": {"type": "wikilink[]", "required": false, "examples": ["[[BioFi Project]]"], "notes": "Maps to affiliated_with"},
    "bioregional_context": {"type": "text", "required": false, "notes": "Rich description, no BKC equivalent"},
    "status": {"type": "string", "required": false, "examples": ["✅ Human Edited"], "notes": "Editorial metadata, no BKC equivalent"}
  }
}
```

### New Table: `ontology_mappings`

Explicit correspondences between source schema fields and BKC ontology concepts.

```sql
CREATE TABLE IF NOT EXISTS ontology_mappings (
    id SERIAL PRIMARY KEY,
    source_schema_id INTEGER REFERENCES source_schemas(id),
    source_field TEXT NOT NULL,
    source_value_pattern TEXT,                  -- regex or glob for value matching (optional)
    bkc_entity_type TEXT,                       -- target entity type (if applicable)
    bkc_predicate TEXT REFERENCES allowed_predicates(predicate),  -- target predicate (if applicable)
    bkc_property TEXT,                          -- target property (if applicable)
    mapping_type TEXT NOT NULL DEFAULT 'unmapped'
        CHECK (mapping_type IN ('equivalent', 'narrower', 'broader', 'related', 'unmapped', 'proposed_extension')),
    mapping_direction TEXT DEFAULT 'outgoing',  -- outgoing, incoming (for relationship mappings)
    confidence FLOAT DEFAULT 1.0,              -- 1.0 for human-reviewed, lower for AI-suggested
    notes TEXT,
    reviewed_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ontology_mappings_schema ON ontology_mappings(source_schema_id);
CREATE INDEX IF NOT EXISTS idx_ontology_mappings_field ON ontology_mappings(source_field);
```

### Additions to `entity_registry`

```sql
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_schema_id INTEGER REFERENCES source_schemas(id);
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}';
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS access_level TEXT DEFAULT 'public';
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS contributed_by TEXT;
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_community TEXT;
```

- `source_schema_id` — links entity to the schema it was ingested from
- `source_metadata` — full original structured data, preserved as-is
- `access_level` — `public`, `community`, `restricted`, `sacred` (see Section 8)
- `contributed_by` — attribution for who contributed this knowledge
- `source_community` — which community this knowledge comes from

**Note on existing entities:** Entities already in `octo_koi` (57 as of Feb 2026) were created from Octo's own vault using `vault_parser.py`. After migration 039b, these entities will have `source_metadata = '{}'` and `source_schema_id = NULL` — they are native to the BKC ontology, not ingested from an external schema. No backfill is needed; the three-layer architecture applies to entities ingested from external sources going forward.

---

## 7. BKC CoIP Mapping — Concrete Example

Applying the three-layer architecture to the BKC CoIP's organization schema:

| Source Field | BKC Mapping | Mapping Type | Notes |
|---|---|---|---|
| `type: organization` | `Organization` entity type | equivalent | Direct match |
| `id` | `entity_slug` property | equivalent | Used for URI generation |
| `place` | `located_in` → `Location/Bioregion` | equivalent | May need geocoding |
| `location` | Coordinates stored in `source_metadata` | unmapped | No BKC property for lat/lon (could propose extension) |
| `activities[]` | Each → `Practice` entity + relationship | narrower | Their "activities" may be broader than BKC "Practice" |
| `patterns[]` | Each → `Pattern` entity + `aggregates_into` | equivalent | Need name normalization (underscore → space) |
| `network-affiliation[]` | `affiliated_with` predicate → Organization | equivalent | Wikilink parsing needed |
| `category` | No equivalent | unmapped | Store in `source_metadata`. Consider extension proposal. |
| `bioregional_context` | No equivalent | unmapped | Rich text, store in `source_metadata` |
| `website` | No equivalent | unmapped | Store in `source_metadata` |
| `links[]` | No equivalent | unmapped | Store in `source_metadata` |
| `status` | No equivalent | unmapped | Editorial metadata, store in `source_metadata` |
| `description` | Entity description (if we add the field) | related | Could map to `rdfs:comment` |

The mapping is partial — and that's correct. The unmapped fields (`category`, `bioregional_context`, `website`, etc.) are preserved in `source_metadata`, searchable, and available for future mapping decisions. They don't participate in cross-bioregional pattern mining *yet*, but they remain intact if the community decides to extend the ontology.

### What This Mapping Reveals

The BKC CoIP schema has concepts that the BKC ontology doesn't cover:

1. **Organizational role/category** — "Bioregional Organizer", "Learning Network", "Indigenous Alliance" — a meaningful typology that could inform pattern mining. Consider proposing `organizational_role` as a property.

2. **Geographic coordinates** — lat/lon for map visualization. The BKC ontology has `Bioregion` and `Location` entity types but no coordinate properties. Consider proposing `geo:lat` / `geo:long` using the GeoSPARQL vocabulary.

3. **Editorial status** — "Human Edited" vs AI-generated. Important for quality/trust signaling. Could become `provenance_status` or similar.

These gaps are **not failures of the BKC ontology**. They are signals from the source community about concepts that matter to them. The ontology extension governance process should consider each one.

---

## 8. Attribution, Permissions, and OCAP

### Entity-Level Access Control

The `access_level` field on `entity_registry` implements a four-tier access model:

| Level | Meaning | Pattern Mining | Network Sharing |
|-------|---------|---------------|----------------|
| `public` | Freely shareable | Yes | Yes |
| `community` | Visible to community members | Yes (within community) | With consent |
| `restricted` | Limited access, specific protocols | No | No |
| `sacred` | Indigenous sacred knowledge | No | Never |

The network handler in the KOI-net pipeline checks `access_level` before including entities in outbound events. Entities with `restricted` or `sacred` access levels **never leave the local node**, regardless of edge configuration.

### Attribution Chain

Every entity carries provenance:

- **`contributed_by`** — Who contributed this knowledge (person, community, or organization)
- **`source_community`** — Which community this knowledge comes from
- **`source_schema_id`** — Which schema it was ingested from (links to mapping provenance)
- **`source_metadata`** — Full original data including any attribution fields from the source

When knowledge flows through the network (e.g., a Practice from Greater Victoria → Octo → Cascadia), the attribution chain is preserved in the event payload. Each node can verify provenance.

### OCAP Principles

The OCAP principles (Ownership, Control, Access, Possession) for Indigenous data governance map directly to the architecture:

| OCAP Principle | Technical Implementation |
|----------------|------------------------|
| **Ownership** | `contributed_by` and `source_community` fields; `access_level: sacred` prevents extraction |
| **Control** | Handler pipeline gives each node veto over what enters and exits; `access_level` enforced at query and network layers |
| **Access** | Edge profiles define who can access what; `access_level` filtering on all API queries; proxy nodes mediate external access |
| **Possession** | Knowledge stored locally (PostgreSQL + vault); no central database; deletion is local and sovereign |

### Consent Tracking

For structured data ingestion (Mode 2), the mapping process should include consent verification:

- Did the source community consent to their data being ingested?
- Did they consent to the specific mapping being applied?
- Did they consent to the resulting BKC entities participating in cross-bioregional pattern mining?

These are social questions with technical implications. The `source_schemas` table includes `consent_status` and `consent_details` columns — see the canonical schema definition in the [implementation plan migration 039b](./implementation-plan.md#11b-schema--mapping-infrastructure).

Valid `consent_status` values: `pending`, `verbal`, `written`, `formal_agreement`, or `declined`.

---

## 9. Ontological Pluriversality in Practice

### What It Means Technically

1. **Multiple ontologies can coexist per entity.** An entity is a `Practice` in the BKC ontology but might be a `ceremony` in the source community's schema, or a `land-based activity` in another. Both (or all) are valid. The `source_metadata` preserves the source's framing. The BKC mapping enables cross-bioregional discovery. Neither erases the other.

2. **The mapping itself is a knowledge artifact.** The fact that we map "Participatory Forest Restoration" to `Practice` is an interpretation that encodes a particular worldview. Making this explicit (in the `ontology_mappings` table with provenance, rationale, and review history) means it can be examined, contested, and revised. Transparent mapping is accountable mapping.

3. **"No equivalent" is a valid and important answer.** Some knowledge is genuinely incommensurable across ontological frameworks. The architecture handles this gracefully: the data is preserved in `source_metadata`, searchable locally, and present in the source layer — but it doesn't get forced through the pattern mining machinery. This is not a failure of the system; it is the system respecting epistemic boundaries.

4. **The BKC ontology is evolvable through governance.** When the agent encounters repeated unmapped concepts across multiple sources (e.g., every bioregional group has an "organizational role" field that doesn't map), it surfaces this as an ontology extension proposal. The community governance process decides whether to extend the ontology. The agent proposes; humans decide.

### What It Means for the Holon Pattern

Each KOI node can declare its ontology as part of its `NodeProfile`:

```python
class NodeProfile(BaseModel):
    node_rid: str
    node_name: str
    node_type: str
    base_url: str | None
    provides: NodeProvides
    ontology_uri: str | None       # URI to the node's ontology schema
    ontology_version: str | None   # Version of the ontology
    public_key: str | None
```

When two nodes negotiate an edge, they can:
- **Discover shared ontology** → full interop (both use BKC ontology)
- **Discover compatible ontologies** → mapping negotiation (partial overlap, create bridging rules)
- **Discover incompatible ontologies** → limited interop (exchange only universally understood types, or exchange raw data without semantic mapping)

The edge profile includes which ontology translations apply:

```python
class KoiNetEdge(BaseModel):
    source_node: str
    target_node: str
    edge_type: str           # WEBHOOK, POLL
    status: str              # PROPOSED, APPROVED
    rid_types: list[str]     # Which RID types flow on this edge
    ontology_mapping: str | None  # Reference to mapping between node ontologies
```

### What It Means Philosophically

The commitment to ontological pluriversality is not just about having a flexible data model. It reflects a deeper principle from the BKC CoIP: that diverse ways of understanding reality are not problems to be resolved but resources to be honored.

From Bollier & Helfrich's "OntoShift": the dominant ontology of modernity treats the world as a collection of resources to be managed. Bioregional ontologies often center relationality — the world as a web of relationships, where value flows through connections rather than being extracted from objects. The BKC ontology's design reflects this: its asymmetric `aggregates_into`/`suggests` predicates encode the difference between emergent discovery and prescriptive application; its "the value is what flows through relationships" principle from SOUL.md grounds the entire graph model.

But the BKC ontology is itself one ontology. It cannot claim to represent all possible ways of knowing. The three-layer architecture (source → mapping → commons) acknowledges this: the commons layer is a shared bridge, not a master schema. The source layer preserves each community's own way of organizing knowledge. The mapping layer makes the translation explicit and accountable.

This is **Three-Eyed Seeing** applied to knowledge architecture: integrate Western scientific categorization (entity types, predicates), Indigenous ways of knowing (preserved in source metadata, protected by access controls), and the land itself as knowledge-holder (bioregional grounding, place-specific practices) — not by collapsing them into one view, but by creating channels for each to flow on its own terms while enabling connection where connection is wanted.

---

## 10. The Ontology Extension Governance Process

When the agent identifies unmapped concepts that recur across sources, it should surface these for community review. The proposed process:

### Step 1: Detection

The agent identifies patterns in unmapped fields:
- "The field `category` appears in 57/57 BKC CoIP organizations with 4 distinct values"
- "3 out of 5 sources include geographic coordinates but BKC ontology has no coordinate property"
- "The predicate `stewards` appears in 2 source schemas but doesn't exist in BKC ontology"

### Step 2: Proposal

The agent creates an extension proposal stored in `ontology_mappings` with `mapping_type = 'proposed_extension'`:

```json
{
  "source_field": "category",
  "proposed_addition": {
    "type": "property",
    "name": "organizational_role",
    "domain": ["Organization"],
    "description": "The role an organization plays in the bioregional movement",
    "examples": ["Bioregional Organizer", "Learning Network", "Indigenous Alliance"],
    "evidence": "Appears in 57/57 BKC CoIP organizations across 4 values"
  }
}
```

### Step 3: Human Review

The proposal is surfaced to community stewards (e.g., the BKC CoIP working group on "Philosophy, Epistemology & Indigenous Knowledge"). They evaluate:

- Does this concept genuinely add value to cross-bioregional pattern mining?
- Does it respect diverse ontological frameworks, or does it impose one?
- Is it needed now, or should it wait until more data clarifies the pattern?
- Who should govern this concept?

### Step 4: Decision

Options:
- **Accept** → Add to BKC ontology (`bkc-ontology.jsonld`), create migration, update `allowed_predicates`
- **Defer** → Keep as `proposed_extension`, revisit when more evidence accumulates
- **Reject** → Change to `unmapped`, document rationale
- **Reframe** → Accept but with different semantics than proposed (e.g., "not a property, but a subclass")

### Step 5: Propagation

If accepted, the updated ontology propagates through the network via KOI-net events. Each node decides whether to adopt the extension (the ontology is shared, not forced). Nodes that don't adopt it simply ignore the new predicate/type in incoming events.

---

## References

### BKC CoIP
- BKC CoIP Proposal: [Google Doc](https://docs.google.com/document/d/1_6GVoM1D7vmI6q4oqIxkqleo1afVS73LBThbXDBdMME/edit)
- Farias, A. "Bioregional Knowledge Commons — A Meta Perspective." r3.0, 2025.
- Bollier, D. & Helfrich, S. *Free, Fair & Alive.* 2019.

### Ontological Pluriversality
- Escobar, A. & Kothari, A. Advocacy for ontological pluriversality.
- Bollier, D. & Helfrich, S. "OntoShift" — from *Free, Fair & Alive.*
- Andreotti, V. Epistemic justice and modernity/coloniality.

### Knowledge Sovereignty
- Flores, W. et al. "A Framework for Kara-Kichwa Data Sovereignty." arXiv:2601.06634.
- Yunkaporta, T. & Goodchild, M. "Protocols for Non-Indigenous People Working with Indigenous Knowledge."
- OCAP Principles: Ownership, Control, Access, Possession (First Nations Information Governance Centre).

### Technical
- BKC Ontology: `ontology/bkc-ontology.jsonld`
- Vault Parser: `koi-processor/api/vault_parser.py`
- Entity Schema: `koi-processor/api/entity_schema.py`
- BKC Predicates Migration: `koi-processor/migrations/038_bkc_predicates.sql`
- Implementation Plan: `docs/implementation-plan.md`
