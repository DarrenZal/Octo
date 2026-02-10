# Holonic Bioregional Knowledge Commons

*How OpenClaw agents become KOI holons to create a fractal network of bioregional knowledge commons.*

---

## 1. The Fractal Pattern

Bioregions are nested. The Gorge Creek watershed feeds into the Goldstream River, which flows into Finlayson Arm, which opens into the Salish Sea, which sits within the Cascadia bioregion, which is part of the Pacific Northwest ecoregion. At every scale, the same pattern repeats: a living system defined by ecological and cultural boundaries, distinct yet inseparable from the systems it is part of.

Knowledge commons should mirror this structure. The practices of herring monitoring in Victoria's inner harbour are specific to that place, but the *pattern* of community-led marine monitoring recurs across the Salish Sea, across Cascadia, across the Pacific coast. Local knowledge is place-specific; the patterns that emerge from it are trans-local. A knowledge infrastructure that forces everything into a single flat database destroys the very structure that makes the knowledge meaningful.

What we need is a **holonic architecture** — where each bioregional knowledge commons is a whole unto itself (autonomous, self-governing, place-specific) and simultaneously a part of something larger (connected, pattern-sharing, federated). Arthur Koestler coined the term "holon" for exactly this: something that is both a whole and a part, depending on the scale at which you observe it.

KOI — Knowledge Organization Infrastructure — provides the technical foundation for this. Built by [BlockScience](https://github.com/BlockScience/koi), the [KOI-net](https://github.com/BlockScience/koi-net) protocol has a remarkable property: **a network of KOI nodes can itself function as a single node to the outside world**. This fractal composition means we can build knowledge commons at every bioregional scale, each internally complex and externally coherent, nesting within each other like watersheds within watersheds.

This document maps the path from where we are today — a single bioregional agent running on a VPS — to a global web of federated bioregional knowledge commons.

---

## 2. What We Have Today

Three KOI deployments exist, each operating at a different scale and purpose. Together they demonstrate that the infrastructure works; what remains is to connect them.

### Octo — Bioregional Knowledge for the Salish Sea

Octo is an OpenClaw agent deployed on a VPS at `<SERVER_IP>`, serving as the AI agent for the BKC CoIP (Bioregional Knowledge Commons Community of Inquiry & Practice). It combines:

- **OpenClaw runtime** — multi-platform chat agent (Telegram + Discord) with plugin system
- **KOI backend** — FastAPI service (port 8351) with four-tier entity resolution:
  - Tier 1: Exact match (normalized text, B-Tree index)
  - Tier 1.x: Fuzzy string match (Jaro-Winkler, phonetic codes)
  - Tier 2: Semantic match (OpenAI embeddings + pgvector HNSW)
  - Tier 3: Create new entity (deterministic URI generation)
- **PostgreSQL** with pgvector (vector similarity), Apache AGE (graph queries), pg_trgm (fuzzy text)
- **Obsidian-style vault** — 13 entity folders (Practices, Patterns, CaseStudies, Bioregions, etc.)
- **BKC Ontology** — 15 entity types, 27 predicates across four categories
- **Identity** — SOUL.md, KNOWLEDGE.md, IDENTITY.md encode the agent's bioregional grounding, values, and domain expertise

The bioregional-koi plugin exposes six tools to the agent: `resolve_entity`, `get_entity_neighborhood`, `get_entity_documents`, `koi_search`, `vault_read_note`, and `vault_write_note`. Through these tools, Octo can query its knowledge graph, resolve ambiguous entity names, traverse relationships, and write new knowledge into its vault.

As of February 2026, the knowledge graph contains 57 registered entities and 31 relationships — small but structurally complete, with the full ontology wired up and the predicate chain validated (Practice → Pattern → CaseStudy → Bioregion, plus the discourse graph and SKOS/hyphal lineages).

### RegenAI — Organizational Knowledge Processing

The RegenAI deployment is the production KOI system, processing organizational knowledge at scale:

- **15,000+ documents** ingested from 15+ active sensors (Discourse, GitHub, Notion, Twitter, web)
- **12,985 unique entities** resolved from 43,430 raw mentions (70% deduplication rate)
- **64,925 RDF triples** in the Apache Jena knowledge graph
- **KOI-net coordinator node** with signed envelope authentication (ECDSA P-256)
- **Event system** — sensors broadcast NEW/UPDATE events; coordinator routes to subscribers

The coordinator node (`koi_coordinator.py`) implements the full KOI-net protocol: event broadcasting, polling, manifest/bundle fetching, content deduplication, and sensor monitoring. It is the most complete implementation of a KOI full node.

### Personal KOI — Individual Knowledge Management

The [personal-koi-mcp](https://github.com/DarrenZal/personal-koi-mcp) server wraps a local KOI backend for personal knowledge management through Claude Code:

- **13,400+ emails** indexed with semantic search
- **260+ Claude sessions** searchable
- **Obsidian vault integration** — entity extraction, wikilink parsing, bidirectional linking
- **MCP tools** — search, vault operations, entity resolution with contextual disambiguation
- **BGE embeddings** (1024-dim) for local semantic matching

The personal instance demonstrates that KOI scales down to the individual while maintaining the same entity resolution and relationship model. This matters because **every agent in a holonic network needs to function autonomously at its own scale**.

### The Pattern

These three deployments map to three scales of knowledge organization:

| Scale | Instance | Function |
|-------|----------|----------|
| Individual | Personal KOI | Personal knowledge management |
| Community | Octo | Bioregional knowledge commons |
| Organization | RegenAI | Organizational memory and processing |

Each uses the same core infrastructure (KOI API, entity resolution, relationship tracking) but serves a different community at a different scale. The question is: how do we connect them?

---

## 3. KOI-net: The Protocol

KOI-net is a protocol for **heterogeneous compositions of KOI nodes** that can autonomously input, process, and output knowledge — both independently and when wired together. It was designed by [BlockScience](https://github.com/BlockScience/koi) and builds on the [RID](https://github.com/BlockScience/rid-lib) (Reference Identifier) protocol.

### RIDs: The Universal Reference System

The foundation of KOI is a careful distinction between **references** and **referents**. As Orion Reed articulates in ["Objects as Reference"](https://blog.block.science/objects-as-reference-toward-robust-first-principles-of-digital-organization/):

> "A relation between a reference (a thing which refers) and a referent (a thing referred to)."

An RID is a digital reference — it *points to* something without *being* that thing. The referent need not be digital; it could be a herring spawning ground, a governance practice, or a person. The digital representation creates objecthood and enables organization, but the map is never the territory.

RIDs follow the ORN (Object Reference Name) format:

```
orn:<namespace>:<reference>
```

For KOI-net nodes: `orn:koi-net.node:regen-coordinator+c5ca332d...`
For entities: `orn:entity:person/bill-baue+a8f3...`

This design enables different organizations to **reference the same thing in different ways** — maintaining internal representations without forcing a unified world model. Two bioregional agents can both reference "herring monitoring" using their own schemas, contexts, and relationships, while the RID system allows cross-reference when they need to coordinate.

### Knowledge Objects: RID + Manifest + Bundle

Every piece of knowledge in KOI is represented as a **Knowledge Object** with three layers:

**RID** — the stable reference identifier. Points to the knowledge, persists across versions.

**Manifest** — metadata about the knowledge:
- `rid` — the reference identifier
- `timestamp` — ISO 8601 UTC (e.g., `2025-12-23T12:00:00Z`)
- `sha256_hash` — cryptographic hash via JCS canonicalization (deterministic, verifiable)
- `size_bytes`, `content_type`, `version` — standard metadata

**Bundle** — the complete package: manifest + contents (the actual data payload as a JSON dictionary).

In code (`koi_net/processor/knowledge_object.py`):

```python
class KnowledgeObject(BaseModel):
    rid: RID
    manifest: Manifest | None = None
    contents: dict | None = None
    event_type: EventType | None = None
    normalized_event_type: EventType | None = None
    source: KoiNetNode | None = None
    network_targets: set[KoiNetNode] = set()
```

The `normalized_event_type` is key: it represents how *this node* views the knowledge object, regardless of how it arrived. The `network_targets` determine which neighbors will hear about it. This separation of "what happened" from "what I think about it" from "who I'll tell" gives each node full autonomy in the pipeline.

### Event-Driven Communication: FUN

KOI-net replaces CRUD (Create, Read, Update, Delete) with **FUN** — three event types that represent state changes as *signals*, not commands:

| Event | Meaning | Analogy |
|-------|---------|---------|
| **NEW** | A previously unknown RID was cached locally | "I just learned about this" |
| **UPDATE** | A previously known RID was refreshed/modified | "I updated what I know about this" |
| **FORGET** | A previously known RID was deleted from cache | "I no longer track this" |

Events are **messages, not operations**. When Node A broadcasts an UPDATE event, Node B autonomously decides whether to care. Node B might fetch the full bundle, ignore it, or log it for audit. There is no forced synchronization — only signals and sovereign responses.

This design embodies the principle of **federation over consolidation**: nodes coordinate through alignment, not through shared databases or forced consensus.

### Node Types: Full and Partial

**Full Nodes** are web servers implementing the complete KOI-net protocol:

| Endpoint | Function |
|----------|----------|
| `POST /koi-net/events/broadcast` | Receive events via webhook |
| `POST /koi-net/events/poll` | Serve events to polling clients |
| `POST /koi-net/manifests/fetch` | Serve manifests by RID |
| `POST /koi-net/bundles/fetch` | Serve complete bundles |
| `POST /koi-net/rids/fetch` | Discovery — list available RIDs |
| `POST /koi-net/handshake` | Exchange metadata with peers |

Full nodes can receive events via webhooks, serve state queries, and call other full nodes. The RegenAI coordinator is a full node.

**Partial Nodes** are web clients without API endpoints. They receive events by polling full nodes and can broadcast events to them, but cannot be called directly. Sensors and lightweight clients are partial nodes.

**Proxy Nodes** sit at the boundary between a KOI network and the outside world. They expose a controlled subset of the network's internal knowledge — enabling inter-organizational collaboration without exposing everything. This is the key mechanism for knowledge sovereignty at the protocol level.

### The Handler Pipeline

Every knowledge object entering a KOI node passes through a five-phase processing pipeline (`koi_net/processor/handler.py`):

```
RID → Manifest → Bundle → Network → Final
```

**Phase 1 — RID Handler:** Receives the RID and source. Decides whether to validate the manifest (and fetch it if not provided). Can reject the knowledge with `STOP_CHAIN`. If the event type is FORGET, skips directly to cache deletion.

**Phase 2 — Manifest Handler:** Receives RID + Manifest. Validates the manifest and optionally fetches the full bundle from the network. Can reject with `STOP_CHAIN`.

**Phase 3 — Bundle Handler:** Receives the complete RID + Manifest + Contents. The **decision point**: sets `normalized_event_type` to NEW, UPDATE, FORGET, or None. This determines the cache action (write, delete, or skip). This is where domain logic lives — the node decides what knowledge to keep.

**Phase 4 — Network Handler:** Decides which neighbor nodes to broadcast to by populating `network_targets`. This is where **knowledge sovereignty is enacted**: the node controls what flows outward.

**Phase 5 — Final Handler:** Post-broadcast actions — logging, metrics, side effects. The pipeline is complete.

Handlers return one of three values:
- `None` — pass the knowledge object unmodified to the next handler
- A modified `KnowledgeObject` — transform and pass forward
- `STOP_CHAIN` — terminate the pipeline immediately

This architecture means each node can implement arbitrary logic at each phase — filtering by RID type, enriching bundles with local context, routing selectively to different neighbors, or blocking knowledge from propagation entirely.

### Edge Negotiation

Nodes discover each other through **edge negotiation**. When two nodes want to communicate, they exchange `KoiNetEdge` objects that define their relationship:

- Direction (incoming/outgoing)
- Status (active/inactive)
- Capabilities and permissions
- RID types of interest (what kinds of knowledge to exchange)

Edge profiles control **what RID types flow between nodes** — a bioregional agent might share Practice and Pattern entities with its regional coordinator but keep internal governance discussions private. This is knowledge sovereignty at the edge level.

---

## 4. The Holon Pattern

The most profound property of KOI-net is fractal composition. From the BlockScience research on ["A Language for Knowledge Networks"](https://blog.block.science/a-language-for-knowledge-networks/):

> "KOI-nets can have a fractal-like structure, insofar as a given KOI-net can also function as a single node in a larger KOI-net (if it is viewed from an external perspective)."

This is the **holon pattern**: a KOI network IS a KOI node, at the next scale up.

### How It Works

Internally, a KOI network might contain dozens of specialized nodes — sensors gathering data, processors enriching it, a coordinator routing events, actuators publishing results. This internal complexity is hidden behind a single external interface — typically the coordinator node, which acts as the proxy to the outside world.

From the outside, the entire network looks like one coherent agent: it receives events, responds to queries, and broadcasts its own discoveries. The internal architecture is invisible to peer networks.

```
┌─────────────────────────────────────────┐
│          Salish Sea KOI Network          │
│                                          │
│  [Sensors] → [Coordinator] → [Actuators]│
│      ↕            ↕                      │
│  [Processors]  [Entity DB]              │
│                                          │
└──────────────────┬───────────────────────┘
                   │
                   │  ← Appears as single node
                   │
┌──────────────────┴───────────────────────┐
│          Cascadia KOI Network            │
│                                          │
│  [Salish Sea]  [Puget Sound]  [Columbia] │
│       ↕             ↕            ↕       │
│            [Cascadia Coordinator]        │
│                                          │
└──────────────────────────────────────────┘
```

### Knowledge Sovereignty at Each Level

The holon pattern preserves autonomy at every scale. Each bioregional agent controls:

1. **What knowledge it ingests** — the RID handler can reject any incoming knowledge
2. **How it processes knowledge** — the bundle handler applies local logic
3. **What it shares outward** — the network handler selects targets and filters content
4. **Who it communicates with** — edge profiles define relationships

A Salish Sea agent might share its documented practices with the Cascadia coordinator but keep internal governance discussions, sacred knowledge references, and working notes private. The coordinator sees only what each sub-agent chooses to share.

This maps directly to the OCAP principles (Ownership, Control, Access, Possession) that govern Indigenous data sovereignty. The technical architecture doesn't just *allow* knowledge sovereignty — it **enforces it at the protocol level**. No node can access another node's knowledge without the source node actively choosing to share it.

### The Neuroscience Analogy

David Sisson's ["KOI Nodes as Neurons"](https://blog.block.science/koi-nodes-as-neurons/) provides a powerful framing through four levels of cognitive sophistication:

**Sensation** — Raw sensory input from the observed world, processed through a node to produce conceptual output. A sensor node detecting a new web page or document.

**Perception** — Sensor fusion: multiple sensory modalities (different data sources, different perspectives) aggregated into a unified representation. A coordinator node combining signals from multiple sensors into a coherent view.

**Cognition** — Internal model-building: the node maintains a world model and uses it for decision-making. An agent that understands relationships, resolves entities, and reasons about its knowledge graph.

**Metacognition** — The system reflects on how it thinks and deliberately reconfigures its own processes. As Michael Zargham frames it: organizations achieve metacognition when they "cognate about how we cognate, and even reconfigure that in an intentional way."

Octo is already operating at the cognition level — it maintains an internal knowledge graph, resolves entities, tracks relationships, and reasons about bioregional knowledge. The metacognitive step happens when the agent can reflect on its own knowledge organization and propose changes to its ontology, predicates, or processing pipeline.

In a holonic network, **each level adds a layer of cognitive sophistication**: individual sensors provide sensation, local networks provide perception, bioregional agents provide cognition, and the meta-network across bioregions enables metacognition — the global commons reflecting on how it organizes knowledge.

---

## 5. OpenClaw Agents as Holons

The concrete design pattern for a holonic bioregional agent:

### The Stack

Each bioregional agent is an **OpenClaw runtime + KOI backend + identity/soul files**:

```
┌─────────────────────────────────────────┐
│    OpenClaw Runtime                      │
│    (Telegram, Discord, CLI channels)     │
├─────────────────────────────────────────┤
│    Workspace Files (Agent Identity)      │
│    IDENTITY.md  SOUL.md  KNOWLEDGE.md   │
│    USER.md  AGENTS.md  HEARTBEAT.md     │
├─────────────────────────────────────────┤
│    bioregional-koi Plugin               │
│    (6 tools: resolve, search, vault...) │
├─────────────────────────────────────────┤
│    KOI API (FastAPI, port 8351)         │
│    Entity resolution (4 tiers)          │
│    Vault parser (27 predicates)         │
├─────────────────────────────────────────┤
│    PostgreSQL + pgvector + Apache AGE   │
│    Entity registry, relationships,      │
│    embeddings, document links           │
├─────────────────────────────────────────┤
│    KOI-net Protocol Layer (future)      │
│    Events, RIDs, signed envelopes       │
└─────────────────────────────────────────┘
```

### What Makes Each Agent Unique

The **workspace files** encode the bioregion's identity, values, and domain knowledge:

- **IDENTITY.md** — who the agent is, its creature metaphor, its role
- **SOUL.md** — foundational commitments, boundaries, how it shows up
- **KNOWLEDGE.md** — domain expertise, community of practice, key relationships
- **USER.md** — the human steward(s) and their context

For Octo, SOUL.md opens with: *"You are the Salish Sea, learning to see itself — through the practice of knowledge commoning."* A Portland agent would have its own grounding: the Willamette watershed, urban food forests, Indigenous land trusts. A Fraser Valley agent would be rooted in the agricultural commons, salmon restoration, and Sto:lo knowledge.

The workspace files are not configuration — they are the agent's **sense of place**. They determine how the agent interprets knowledge, what it pays attention to, and how it shows up in conversation. This is why identity can't be centralized: each bioregion has its own story, its own wounds, its own threads to track.

### The Knowledge Graph as Bioregional Memory

Each agent maintains its own knowledge graph:

- **Entity registry** — people, organizations, projects, practices, patterns, bioregions
- **Relationships** — 27 predicates connecting entities (affiliated_with, aggregates_into, practiced_in, etc.)
- **Document-entity links** — which documents mention which entities (bidirectional)
- **Pending relationships** — unresolved targets waiting for new entities to be registered

The vault parser (`vault_parser.py`) maps YAML frontmatter fields to canonical predicates with direction handling (outgoing vs. incoming), symmetric predicates (knows, collaborates_with create bidirectional links), and batch entity resolution to avoid N+1 queries.

This knowledge graph is the agent's memory of its bioregion — not just facts, but **relationships**. Who works with whom, which practices aggregate into which patterns, what case studies document what, which claims are supported by what evidence. The graph structure mirrors the relational ontology expressed in SOUL.md: *"The value is what flows through relationships."*

### Participating in KOI-net

When KOI-net protocol is integrated (see roadmap, Section 11), each agent becomes a **full node** in the network. The coordinator serves as its external interface:

- **Inbound events** — the agent receives NEW/UPDATE/FORGET events about knowledge from peer agents
- **RID handler** — filters events by type (only interested in Practices, Patterns, CaseStudies from peers)
- **Bundle handler** — decides whether to cache external knowledge locally
- **Network handler** — decides what to share with which peers
- **Entity resolution** — resolves incoming entities against local registry (cross-bioregional deduplication)

### Cross-Bioregional Entity Resolution

When a Puget Sound agent shares a Practice entity called "Community Salmon Monitoring," the Salish Sea agent's entity resolver tries to match it:

1. **Tier 1**: Exact match against local entities — no hit
2. **Tier 1.x**: Fuzzy match — finds "Salmon Spawning Surveys" at 0.72 similarity — below threshold
3. **Tier 2**: Semantic match — embedding similarity of 0.89 with "Community Marine Monitoring" — above threshold
4. **Decision**: Link as `related_to` rather than merge (they're related practices, not the same practice)

This graduated resolution prevents false merges while surfacing connections. The agent maintains its own entity registry with its own labels and relationships, linked via RIDs to the broader network.

---

## 6. A Cascadia Network

Cascadia is the natural first network — a bioregion defined by the Pacific watersheds from Northern California to Southeast Alaska, unified by salmon, cedar, and rain. It already has organizational infrastructure: Regenerate Cascadia (Brandon Letsinger & Clare Attwell) connects landscape groups across the region.

### The Agents

| Agent | Bioregion | Focus | Status |
|-------|-----------|-------|--------|
| **Octo** | Salish Sea / Greater Victoria | Marine commons, herring, orca, Indigenous knowledge | Deployed |
| **[Portland Metro]** | Willamette Valley | Urban ecology, food forests, houselessness, watershed restoration | Planned |
| **[Puget Sound]** | Seattle / Tacoma | Tech-meets-ecology, salmon recovery, tribal fisheries | Planned |
| **[Fraser Valley]** | Fraser River / Lower Mainland | Agricultural commons, Sto:lo knowledge, flood adaptation | Planned |
| **[Columbia Gorge]** | Columbia River | Energy transition, dam removal, tribal sovereignty | Planned |

Each agent would have:
- Its own VPS with KOI backend
- Its own OpenClaw runtime with community-specific channels
- Its own workspace files grounded in local place and practice
- Its own entity registry, knowledge graph, and vault
- KOI-net protocol integration for federation

### The Coordinator

A **Cascadia coordinator node** aggregates knowledge across sub-bioregional agents. It doesn't replace the agents — it provides a meta-view:

- Receives event streams from all Cascadia agents
- Maintains a Cascadia-scale entity registry (cross-linking entities across agents)
- Surfaces trans-bioregional patterns (practices that recur across multiple sub-bioregions)
- Serves as the proxy node when Cascadia participates in larger networks

The coordinator implements the same handler pipeline but with different logic:

- **RID handler**: Accepts Practices, Patterns, CaseStudies, Bioregions from all Cascadia agents
- **Bundle handler**: Caches cross-bioregional entities; runs pattern detection across accumulated practices
- **Network handler**: Shares aggregated patterns with all Cascadia agents; shares Cascadia-level patterns with the global network

### Shared Vocabulary, Local Autonomy

All Cascadia agents use the **BKC Ontology** as their shared vocabulary — 15 entity types and 27 predicates. This ensures interoperability: when Octo shares a Practice entity with `practiced_in: [[Bioregions/Salish Sea]]` and `aggregates_into: [[Patterns/Commons Resource Monitoring]]`, the Portland agent can parse those relationships because they share the same predicate definitions.

But the ontology is a **vocabulary, not a rulebook**. Each agent can:
- Add local entity types (Portland might track "Urban Commons" as a subclass of Bioregion)
- Extend predicates for local needs
- Maintain local relationship semantics
- Choose which predicates to expose to the network

The ontology's asymmetric predicate design supports this:
- `aggregates_into` (Practice → Pattern) is **observational**: practices aggregate into patterns through bottom-up discovery
- `suggests` (Pattern → Practice) is **prescriptive**: patterns suggest new practices through top-down application

These are intentionally **not inverses** — they represent different epistemological directions. A pattern that emerges from Salish Sea herring monitoring and Puget Sound salmon monitoring is discovered bottom-up; the same pattern *suggesting* new monitoring practices in the Fraser Valley is applied top-down. The ontology encodes this distinction.

---

## 7. Cross-Scale Pattern Mining

The killer application of a holonic bioregional knowledge network is **automated pattern discovery across places**.

### The Untested Hypothesis

The BKC CoIP's methodology is built on an assumption from Bollier & Helfrich's *Free, Fair & Alive*: that bioregional practices, when documented systematically, will aggregate into trans-bioregional patterns. This assumption has never been tested — no one has yet conducted systematic interviews across enough bioregions to validate whether patterns emerge.

A holonic KOI network provides the infrastructure to test this hypothesis at scale.

### How It Works

**Step 1: Local documentation.** Each bioregional agent documents practices from its community. Octo documents herring monitoring, camas restoration, community mapping. Portland documents urban food forests, watershed councils, houseless camp stewardship. Each practice is a vault note with `@type: bkc:Practice`, `practiced_in`, and relationship frontmatter.

**Step 2: Event propagation.** When a practice is documented, the agent broadcasts a NEW event with the practice's RID and manifest. The Cascadia coordinator receives it.

**Step 3: Pattern detection.** The coordinator accumulates practices from all agents. When multiple agents document semantically similar practices (detected via embedding similarity), the coordinator proposes a pattern:

```
Practices from Salish Sea:
  - Herring Monitoring (community-led species count)
  - Salmon Spawning Surveys (citizen science)

Practices from Puget Sound:
  - Orca Sighting Network (community reporting)
  - Beach Naturalist Program (tide pool monitoring)

Practices from Fraser Valley:
  - Sturgeon Watch (community fisheries monitoring)

Proposed Pattern:
  - "Commons Resource Monitoring" — community-led monitoring
    of keystone species as bioregional commons practice
```

**Step 4: Pattern broadcasting.** The coordinator creates a Pattern entity with `aggregates_into` relationships pointing back to the source practices, then broadcasts an UPDATE event to all Cascadia agents.

**Step 5: Pattern application.** Each agent receives the pattern and can use `suggests` to identify new practices inspired by it. The Portland agent might ask: "Given the Commons Resource Monitoring pattern, what species monitoring could Portland establish?" The pattern becomes prescriptive — guiding new practice development.

### The aggregates_into / suggests Cycle

This is the heart of the BKC methodology, encoded directly in the ontology:

```
                   ┌──────────────────┐
                   │     PATTERNS     │
                   │ (trans-local)    │
                   └────┬────────┬────┘
            suggests ↓          ↑ aggregates_into
                   ┌────┴────────┴────┐
                   │    PRACTICES     │
                   │ (place-specific) │
                   └──────────────────┘
```

The cycle is generative: practices aggregate into patterns, patterns suggest new practices, new practices refine patterns. In a holonic network, this cycle operates across scales:

- **Local**: Practices within one bioregion aggregate into local patterns
- **Regional**: Local patterns from multiple bioregions aggregate into regional patterns
- **Global**: Regional patterns aggregate into global patterns — the "meta knowledge commons"

Each level of aggregation produces patterns at a higher level of abstraction while maintaining provenance links back to the place-specific practices that generated them.

### Validating the Methodology

The BKC CoIP has identified 12+ bioregional groups across 6 continents for primary research interviews. If each interview produces documented practices, and those practices flow into a KOI network, the pattern mining can begin. For the first time, the hypothesis that trans-bioregional patterns exist can be tested computationally — not by one researcher reading all the interview notes, but by a network of agents collectively surfacing what recurs.

---

## 8. Knowledge Sovereignty at Every Scale

The holon pattern doesn't just enable federation — it **enforces sovereignty**. This is not an afterthought; it is the architecture itself.

### Protocol-Level Sovereignty

At the KOI-net protocol level, sovereignty is enacted through four mechanisms:

**1. Handler filtering.** Each node's RID handler, manifest handler, and bundle handler can reject any incoming knowledge. A node is never forced to accept knowledge it doesn't want.

**2. Network targeting.** Each node's network handler controls what flows outward. Knowledge stays local by default; sharing requires active selection.

**3. Edge profiles.** The edge negotiation between nodes specifies which RID types flow in which direction. A bioregional agent can configure: "Share Practices and Patterns with the coordinator. Do not share Meeting notes, People entries, or internal governance documents."

**4. Proxy nodes.** A network's external interface is a proxy that exposes only what the network collectively decides to share. Internal complexity is hidden.

### OCAP Principles in Architecture

The OCAP principles (Ownership, Control, Access, Possession) — developed for Indigenous data governance — map directly to the holon pattern:

| OCAP Principle | Holonic Implementation |
|----------------|----------------------|
| **Ownership** | Each agent owns its knowledge graph. Entity URIs are generated locally with deterministic algorithms. |
| **Control** | Handler pipeline gives each node complete control over what enters and exits. |
| **Access** | Edge profiles define who can access what. Proxy nodes mediate external access. |
| **Possession** | Knowledge is stored locally (PostgreSQL + vault). No central database holds everything. |

### Sacred and Restricted Knowledge

Eli Ingraham's critical framing applies directly:

> "Indigenous Knowledge Systems are very different from ours. There is secular knowledge and sacred knowledge. Each is accessed and shared via different protocols that involve age, gender, and role."

In a holonic network, sacred or restricted knowledge **never needs to leave the local node**. An agent serving Indigenous communities can:

- Store sacred knowledge in its local vault with no external predicates
- Tag restricted entities with access levels in frontmatter
- Configure its network handler to never broadcast certain entity types
- Maintain complete local autonomy while still participating in the broader network for secular knowledge

The architecture supports Eli's insight that *"the real knowledge lies within the minds and hands and hearts of those closest to the ground, not in discoverable databases."* The KOI network doesn't try to make all knowledge discoverable — it creates channels for knowledge that *wants* to flow while respecting knowledge that needs to stay rooted.

### Federation Over Consolidation

From SOUL.md: *"You are one node in a web, not the center of it."*

The holonic architecture embodies this. There is no master database, no central authority, no single schema that all agents must conform to. Each agent is sovereign. Each network is sovereign. They coordinate through:

- **Shared vocabulary** (ontology) without shared rules
- **Event signals** without forced synchronization
- **Cross-references** (RIDs) without shared identity systems
- **Pattern discovery** without centralized analysis

This is the cosmolocal pattern from SOUL.md: *"Design global, implement local. What is light is global and shared, what is heavy is local."* The ontology, the protocol, the pattern library — these are light, global, shared. The knowledge graphs, the entity registries, the place-specific practices — these are heavy, local, sovereign.

---

## 9. Ontological Architecture

> **Detailed treatment:** See [ontological-architecture.md](./ontological-architecture.md) for the full architectural specification including schema design, concrete mapping examples, and the ontology extension governance process.

The three foundational commitments — knowledge sovereignty, epistemic justice, and ontological pluriversality — are not just philosophical principles. They have direct architectural implications for how the knowledge commons handles diverse data sources.

### The BKC Ontology as Bridge Language

The BKC ontology (15 entity types, 27 predicates) is not a universal schema that all knowledge must conform to. It is a **bridge language** — the minimum shared vocabulary needed for cross-bioregional pattern mining. Like a natural language lingua franca, it enables communication across communities without requiring anyone to abandon their own way of organizing knowledge.

This distinction matters because the BKC CoIP will encounter knowledge from dozens of communities, each with their own schemas, categories, and organizing principles. The Salish Sea agent documents "Practices." A community in Devon might document "land-based activities." The BKC CoIP's own Obsidian vault uses `activities` and `patterns` as YAML fields with different naming conventions than the BKC ontology predicates. Forcing all of these into one schema would violate ontological pluriversality. Preserving all of them without any shared structure would make pattern mining impossible.

The bridge language resolves this: knowledge from any source can be mapped *into* the shared vocabulary for cross-bioregional discovery, while preserving its original structure alongside.

### Three-Layer Ingestion

Every piece of ingested knowledge exists in three layers:

1. **Source layer** — the complete original data, preserved in its own schema and vocabulary. Never modified by ingestion. Stored as `source_metadata` (JSONB) on each entity.

2. **Mapping layer** — explicit, human-reviewed correspondences between source schema and BKC ontology. Each mapping records its type (equivalent, narrower, broader, related, unmapped, proposed extension), who reviewed it, and when. Transparent and contestable.

3. **Commons layer** — the BKC ontology representation that participates in cross-bioregional pattern mining. An entity exists in this layer only through an explicit mapping from its source.

This architecture ensures that no knowledge is lost in translation. The original structure persists in the source layer. The mapping is documented and accountable. The commons layer provides the shared vocabulary for pattern discovery. All three layers coexist on each entity.

### The Agent's Ontology Skillset

Each bioregional agent has the capability to:

- **Detect** when incoming data has explicit structure (YAML, JSON-LD, RDF)
- **Profile** the schema (fields, types, example values, statistics)
- **Suggest** mappings from source schema to BKC ontology
- **Flag** gaps where source concepts don't map — surfacing them as ontology extension proposals
- **Preserve** original structure alongside any mapping
- **Track** full provenance: who contributed, from where, with what permissions

Critically, the agent **proposes mappings but never auto-applies them**. The mapping from one ontology to another is an interpretive act that should be explicit and human-reviewed. This is ontological pluriversality in practice: acknowledging that the translation between ways of knowing requires judgment, not automation.

### Ontological Pluriversality in the Holon Pattern

The holon architecture naturally supports multiple ontologies:

- **Each node declares its ontology** in its `NodeProfile` (`ontology_uri`, `ontology_version`)
- **Edge negotiation includes ontology compatibility** — nodes with shared ontology get full interop; nodes with different ontologies negotiate mapping rules
- **Knowledge that can't be translated stays local** — this is a feature, not a bug; genuine incommensurability is respected, not papered over
- **The shared bridge vocabulary is minimal** — just enough for pattern mining, not a comprehensive world model

This is **Three-Eyed Seeing** applied to knowledge architecture: Western scientific categorization (entity types, predicates), Indigenous ways of knowing (preserved in source metadata, protected by access controls), and the land itself as knowledge-holder (bioregional grounding, place-specific practices) — not collapsed into one view, but given channels to flow on their own terms while enabling connection where connection is wanted.

---

## 10. Interoperability Beyond KOI

Not every bioregional knowledge commoning group will use KOI — and they shouldn't have to. The BKC CoIP Practices & Patterns Project is the most immediate example: a collaborative research effort interviewing bioregional groups across six continents, documenting their practices in markdown, and mining for trans-bioregional patterns. They will build their own knowledge commons using tools that fit their community — likely Obsidian/markdown files, Notion databases, and whatever each participating learning network already uses.

This is not a problem to solve. It is the design working correctly.

### The BKC CoIP Approach

The Practices & Patterns Project has its own technical trajectory:

**Data format:** Markdown files with structured metadata — the most accessible, version-controllable, vendor-neutral choice. Compatible with Obsidian, Git, and any text editor.

**Databases:** Multiple, pluralistic. Andrea Farias is already supporting learning networks like Commonland and Bioregional Weaving Lab in creating their own databases (custom-built and Notion-based). The project's goal is explicitly *not* to create a single tool or approach, but to support "federated pluralistic knowledge bases, enabling cross-network discovery and learning."

**Interoperability:** The project is exploring protocols like **[Murmurations](https://murmurations.network/)** — a protocol that indexes and shares public data so it can be discovered and used across independent knowledge bases. This aligns with the same philosophy as KOI-net: federation over consolidation, shared discovery without shared databases.

**Advanced interfaces:** The project envisions input mechanisms for practitioners to contribute without technical expertise, and has experimented with an AI chatbot for navigating the knowledge base.

### How Octo Relates to the BKC CoIP Project

Octo's role isn't to replace the project's infrastructure — it's to **complement it** from the bioregional side. Several concrete relationships:

**1. Ingesting published results.** When the BKC CoIP publishes case studies, practice catalogs, or pattern libraries, Octo can ingest them as knowledge objects. A **sensor node** watches the published repository (Git, website, or API) and converts new or updated markdown files into KOI entities — resolving people, organizations, practices, and patterns against Octo's existing entity registry. This is the same sensor pattern used in RegenAI, where 15+ sensors already ingest from Discourse, GitHub, Notion, and other sources.

**2. Contributing documented practices.** Octo documents practices from the Salish Sea bioregion. These documented practices — structured with the BKC ontology's entity types and predicates — can be exported as markdown files compatible with the project's data schema. Octo doesn't need the project to use KOI; it just needs to speak markdown with the same vocabulary.

**3. The AI chatbot role.** The project has identified a need for an AI interface to help users navigate and query the knowledge base. Octo is already an AI agent grounded in BKC domain expertise (KNOWLEDGE.md), with entity resolution, semantic search, and relationship traversal. It could serve as this chatbot — or at least as a reference implementation — connecting to whatever database the project builds through a plugin layer similar to `bioregional-koi`.

**4. Cross-pollination with learning networks.** As the project connects with Commonland, BWL, and other learning networks that maintain their own databases, Octo's entity resolution can help link entities across these independent systems. When the same organization or practice appears in multiple databases, semantic matching can surface the connections without forcing anyone to change their tools.

### The Sensor Pattern: Ingesting Non-KOI Sources

The key technical pattern is the **sensor node** — a component that watches an external data source and converts its contents into KOI knowledge objects. For the BKC CoIP project:

```
BKC CoIP Published Data (markdown/Git/Notion)
         ↓
    [BKC Sensor Node]
    - Watches for new/updated files
    - Parses markdown frontmatter
    - Extracts entities (people, orgs, practices, patterns)
    - Maps to BKC ontology predicates
         ↓
    Octo's KOI Backend
    - Entity resolution against local registry
    - Relationship extraction
    - Cross-reference with existing knowledge
```

This sensor is a **partial node** in KOI-net terms — it doesn't need to implement the full protocol. It just monitors a data source and emits NEW/UPDATE events when content changes. The BKC project doesn't even need to know it exists.

### Murmurations and Discovery Protocols

The BKC CoIP project's interest in **Murmurations** — a protocol for indexing and sharing public data across independent databases — is complementary to KOI-net. They operate at different layers:

| Layer | Murmurations | KOI-net |
|-------|-------------|---------|
| **Purpose** | Discovery and indexing of public data | Full knowledge processing and federation |
| **Complexity** | Lightweight, schema-based profiles | Full protocol with events, handlers, signed envelopes |
| **Adoption barrier** | Low (publish a JSON profile) | Higher (run a KOI node) |
| **Best for** | Making your data findable | Deep knowledge integration |

A bioregional group could publish a Murmurations profile describing their knowledge base, making it discoverable. Octo could subscribe to Murmurations indices to discover new bioregional knowledge bases, then use its sensor architecture to ingest relevant content. The two protocols don't compete — they serve different needs on the spectrum from "make my work findable" to "deeply integrate knowledge across systems."

### The Pluralistic Principle

The BKC CoIP project's framing is exactly right: *"The aim is to create the conditions for federated pluralistic knowledge bases, enabling cross-network discovery and learning, without trying to create a single approach or tool."*

KOI is one approach. Notion databases are another. Obsidian vaults are another. Custom-built platforms are another. The holonic vision doesn't require everyone to use the same tool — it requires that tools can **interoperate at the edges**. This means:

- **Shared vocabulary** (the BKC ontology defines entity types and predicates that any tool can adopt)
- **Shared data format** (markdown with YAML frontmatter is universal)
- **Discovery protocols** (Murmurations, RSS, Git repositories)
- **Ingestion patterns** (sensors that can read from diverse sources)
- **Entity resolution** (matching the same entity across different databases)

The holon pattern applies here too: each group's knowledge commons is a whole unto itself. When they choose to make results public, those results can be ingested by any other system with a compatible sensor. The sovereignty is preserved — they control what they publish, and no one needs permission to read what's public.

---

## 11. Technical Roadmap

> **Detailed implementation plan:** See [implementation-plan.md](./implementation-plan.md) for specific files, migrations, configurations, and test criteria.

### Phase 1: BKC CoIP Interoperability

**Goal:** Enable Octo to ingest from and contribute to the BKC Practices & Patterns Project, regardless of what tools they use.

**Why first:** The BKC CoIP is the most immediate community Octo serves. This delivers value before any federation infrastructure is built.

**Tasks:**
- Build a markdown sensor that monitors the BKC project's published outputs (Git repo or shared directory)
- Parse markdown files with BKC-compatible frontmatter into KOI entities
- Resolve ingested entities against Octo's existing registry (avoid duplicates)
- Export Octo's documented Salish Sea practices in BKC-compatible markdown format
- Explore Murmurations profile publishing for discoverability

### Phase 2: Multi-Instance Infrastructure

**Goal:** Set up the database and configuration for running three KOI agents on one VPS — Greater Victoria, Octo (Salish Sea), and Cascadia.

**Architecture:** All agents share the existing PostgreSQL container with separate databases (`gv_koi`, `octo_koi`, `cascadia_koi`) and run separate KOI API instances on different ports (8352, 8351, 8353).

**Tasks:**
- Create additional databases with extensions in the shared PostgreSQL container
- Deploy Greater Victoria agent with its own workspace files, vault, and systemd service
- Seed GV vault with 2-3 local practice notes
- Verify independent operation (entity resolution, vault operations)

### Phase 3: KOI-net Protocol Layer

**Goal:** Add KOI-net protocol endpoints to the KOI API, enabling inter-agent communication.

**Tasks:**
- Implement Pydantic models matching BlockScience wire format (P1a/P1b)
- Add five protocol endpoints (`/koi-net/events/broadcast`, `/events/poll`, `/manifests/fetch`, `/bundles/fetch`, `/rids/fetch`)
- Implement signed envelope support (ECDSA P-256) — reference: `koi_net_interop_test.py`
- Implement event queue with persistence and delivery tracking
- Generate node identities (keypair + node RID) for each agent
- Add database tables for events, edges, and node registry

**Reference code:** RegenAI coordinator (`koi_coordinator.py`) for production patterns. BlockScience koi-net library (`koi_net/processor/`) for the handler pipeline.

### Phase 4: Federation (Greater Victoria ↔ Octo)

**Goal:** Prove two-node federation — GV documents a practice, Octo receives it.

**Tasks:**
- Configure edges between GV and Octo (manual initially, automated negotiation later)
- Bridge entity registration to event emission (register entity → emit NEW event)
- Implement polling client (background task that fetches events from peers)
- Implement cross-agent entity resolution (link via cross-references, not merge)
- End-to-end test: GV practice → event → Octo cross-reference

### Phase 5: Cascadia Coordinator

**Goal:** Third agent sees the Salish Sea network as a single node — proving the holon pattern.

**Tasks:**
- Deploy Cascadia agent with workspace files encoding the broader bioregional context
- Implement holon boundary: Octo re-broadcasts GV events as its own to Cascadia
- Configure edges: Octo → Cascadia (Practices and Patterns only)
- Test 3-hop propagation: GV → Octo → Cascadia
- Verify: Cascadia sees "Salish Sea" as source, not individual landscape groups

### Phase 6: Pattern Mining Across the Network

**Goal:** Automatically surface trans-bioregional patterns via the aggregates_into / suggests cycle.

**Tasks:**
- Implement practice clustering at the coordinator level (embedding similarity)
- Propose Pattern entities when practice clusters span 2+ sub-bioregions
- Create `aggregates_into` links back to source practices
- Broadcast proposed patterns to all agents
- Enable `suggests` relationships: patterns recommend practices to agents that lack them

---

## 12. The Global Vision

### Fractal Scaling

```
Individual agents
    → Bioregional networks (Salish Sea, Portland Metro, ...)
        → Regional networks (Cascadia, Great Lakes, ...)
            → Continental webs (North America, Europe, ...)
                → Global commons
```

Each level is a holon. The Salish Sea agent is a whole unto itself — with its own knowledge graph, identity, relationships, and community. It is also a part of Cascadia. Cascadia is a whole — with its own coordinator, pattern library, and cross-agent entity resolution. It is also a part of the North American bioregional web.

At the global level, the BKC CoIP's vision becomes technically realizable: a federated network of bioregional knowledge commons, each sovereign, each connected, each contributing to a shared pattern library that no single entity controls.

### The Interview Candidates as Potential Nodes

The BKC CoIP has identified bioregional groups across six continents:

- **Africa**: Great Lakes Bioregion (Kenya), Valley of Grace (South Africa)
- **Asia**: Forever Sabah (Philippines), South Asia Bioregionalism Working Group
- **Australia**: Regen Sydney, Regenerating Mornington Peninsula
- **Europe**: Devon / Bioregional Learning Centre (UK), High Po River Valley (Italy)
- **North America**: Regenerate Cascadia, Greater Tkaronto Bioregion, Northeast Woodlands
- **South America**: Barichara (Colombia), Colombia Regenerativa

Each of these groups could, in principle, run their own bioregional agent — with their own KOI backend, their own ontology extensions, their own knowledge graph rooted in their own place. Connected via KOI-net, they would form the first global bioregional knowledge network.

The interview methodology (Emergence Phase) would produce documented practices. Those practices, stored in each agent's vault, would flow through the network. Patterns would emerge — not imposed by researchers, but discovered by the network itself.

### The Cosmolocal Pattern

From SOUL.md: *"Knowledge is free. Sharing it costs nothing and creates compounding value. Design global, implement local."*

The holonic architecture implements the cosmolocal pattern:

**What is light (global and shared):**
- The BKC ontology (15 entity types, 27 predicates)
- The KOI-net protocol (events, RIDs, signed envelopes)
- The pattern library (trans-bioregional patterns that emerge from practice)
- The methodology (pattern mining, discourse graphs, three-eyed seeing)

**What is heavy (local and sovereign):**
- Each agent's knowledge graph (entities, relationships, document links)
- Each agent's identity (SOUL.md, workspace files, community relationships)
- Each agent's vault (practices documented in place, case studies, governance notes)
- Each community's decisions about what to share and what to keep

This mirrors how bioregions actually work. The salmon runs are local — they navigate specific rivers, spawn in specific gravel beds, feed specific forests. But the *pattern* of salmon as nutrient vector, as keystone species, as indicator of watershed health — this pattern is global. The knowledge commons should work the same way: local practices, global patterns, sovereignty at every scale.

---

*The octopus has nine brains — one central witness that coordinates, eight autonomous arms that sense and respond independently. A holonic bioregional knowledge network works the same way: many agents, many ways of knowing, coordinated through relationship rather than hierarchy. Each arm tastes its own water. Together, they dream the bioregion awake.*

---

## References

### BlockScience KOI Research
- Sisson, D. ["KOI Nodes as Neurons."](https://blog.block.science/koi-nodes-as-neurons/) BlockScience, 2025.
- Reed, O. ["Objects as Reference."](https://blog.block.science/objects-as-reference-toward-robust-first-principles-of-digital-organization/) BlockScience, 2025.
- ["A Language for Knowledge Networks."](https://blog.block.science/a-language-for-knowledge-networks/) BlockScience, 2025.
- ["Architecting KOI."](https://blog.block.science/architecting-knowledge-organization-infrastructure/) BlockScience, 2025.
- KOI-net reference implementation: [`koi-net`](https://github.com/BlockScience/koi-net)
- RID library: [`rid-lib`](https://github.com/BlockScience/rid-lib)

### BKC CoIP
- Farias, A. "Bioregional Knowledge Commons — A Meta Perspective." r3.0, 2025.
- Bollier, D. & Helfrich, S. *Free, Fair & Alive.* 2019.
- Alexander, C. *A Pattern Language.* 1977.
- Ostrom, E. *Governing the Commons.* 1990.

### Knowledge Sovereignty
- Flores, W. et al. ["A Framework for Kara-Kichwa Data Sovereignty."](https://arxiv.org/abs/2601.06634) arXiv:2601.06634.
- Yunkaporta, T. & Goodchild, M. "Protocols for Non-Indigenous People Working with Indigenous Knowledge."

### Technical
- Ontological Architecture: `docs/ontological-architecture.md`
- BKC Ontology: `ontology/bkc-ontology.jsonld`
- KOI API: `koi-processor/api/personal_ingest_api.py`
- Entity Resolution: `koi-processor/api/entity_schema.py`
- Vault Parser: `koi-processor/api/vault_parser.py`
- OpenClaw Plugin: `plugins/bioregional-koi/index.ts`
- KOI-net Interop Test: `RegenAI/koi-sensors/scripts/koi_net_interop_test.py`
- KOI Coordinator: `RegenAI/koi-sensors/koi_protocol/coordinator/koi_coordinator.py`

### Foundational
- Koestler, A. *The Ghost in the Machine.* 1967. (Origin of "holon" concept)
- Andreotti, V. Epistemic justice and modernity/coloniality.
- Escobar, A. & Kothari, A. Ontological pluriversality.
