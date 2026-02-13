# How KOI Works

*A guide to Knowledge Organization Infrastructure for bioregional practitioners, community builders, and anyone curious about how distributed knowledge networks can serve living systems.*

---

## The Salish Sea, Learning to See Itself

Beneath the floor of every old-growth forest runs a web of fungal threads — mycelium — connecting the roots of trees that appear, from the surface, to stand alone. Through this underground network, trees share sugars, water, and chemical signals. A Douglas fir can feed a struggling hemlock. A dying tree can redistribute its carbon to its neighbors. No single tree directs the network; no central hub decides what flows where. Intelligence is distributed through the relationships themselves.

This is how a bioregion organizes knowledge — or how it could.

Right now, bioregional knowledge is scattered. A community group in the Cowichan Valley documents salmon habitat restoration. A marine biologist in the San Juan Islands publishes herring monitoring data. A food sovereignty network in Puget Sound maps local seed libraries. Each effort is valuable on its own. But no infrastructure connects them. No one can see that these place-specific practices share deep patterns — that community-led ecological monitoring is emerging simultaneously across the entire Salish Sea, and that each effort could learn from the others.

**Knowledge Organization Infrastructure** — KOI — is the mycelium. It is the underground network that connects autonomous knowledge-holders without centralizing or controlling what they know. Each participant maintains their own knowledge, in their own way, on their own terms. KOI provides the shared protocols that let knowledge flow between them — selectively, securely, and with full sovereignty preserved.

KOI was developed as a collaborative research effort across [BlockScience](https://block.science/), [Metagov](https://metagov.org/), and [RMIT](https://www.rmit.edu.au/), and is now being implemented by bioregional projects like Octo to build federated knowledge commons at the scale of the watershed, the bioregion, and beyond.

> *"The most fundamental 'knowledge network' is, after all, nothing more than a conversation between open-minded peers."*
> — Michael Zargham & Ilan Ben-Meir, BlockScience

---

## What Is KOI?

### The Mycelial Library

Imagine a network of local libraries — not one mega-library, but many independent collections, each serving its own community. Every library catalogs its books using a shared classification system, so they can understand each other's holdings. When one library acquires a new book on watershed restoration, it can signal to the network: "We just cataloged something new about watershed restoration." Any library in the network that cares about that topic can request more details.

No library ships its entire collection to a central warehouse. No library gives up control over what it holds or who can access it. The network *connects* them without *consolidating* them.

KOI works the same way, but for knowledge — not just documents, but the practices, patterns, relationships, and ways of knowing that communities generate through their work on the ground.

Three ideas make this possible:

### Reference Identifiers (RIDs) — Naming Without Possessing

Every piece of knowledge in a KOI network gets a unique identifier — a **Reference Identifier**, or RID. Think of it as an ISBN for ideas. An RID lets you *refer to* something without *possessing* it.

This distinction matters more than it first appears. As the philosopher Orion Reed frames it: a reference is not the thing it points to. The map is not the territory. An RID for "herring egg monitoring in Saanich Inlet" lets any node in the network *talk about* that practice — link to it, compare it to other practices, include it in patterns — without needing access to the underlying data.

> *"RIDs make it possible for organizations to communicate knowledge from or about proprietary resources and other objects, while preserving ownership of — and access control over — materials that they may be unwilling or unable to share."*
> — BlockScience, "A Preview of the KOI-net Protocol"

This is how you share knowledge without sharing everything. Communities can participate in a global conversation about bioregional practice while retaining complete control over their local knowledge.

### FUN Events — Signaling, Not Commanding

When something changes in a KOI node — a new practice is documented, an existing record is updated, or something is removed — the node sends a signal to its peers. These signals follow the **FUN** model:

- **F** (Forget): "I've removed something I previously shared."
- **U** (Update): "Something I've shared has changed."
- **N** (New): "I've learned something new."

The crucial word here is *signal*. A FUN event is an announcement, not a command. When one node says "I've learned something new about watershed stewardship," it does not instruct other nodes to update their records. Each receiving node decides independently what to do with the signal — accept it, ignore it, investigate further, or file it for later.

This is fundamentally different from how most databases work. In a centralized system, one authority writes data and everyone else reads it. In KOI, every node is sovereign. Signals flow through the network like chemical signals through mycelium — each organism responds according to its own nature and needs.

### Signed Envelopes — Trust Without Centralized Authority

When a letter arrives with a wax seal, you know two things: who sent it, and that it hasn't been tampered with. KOI uses the same principle digitally. Every message between nodes is wrapped in a **signed envelope** — cryptographically sealed so that the recipient can verify the sender's identity and the message's integrity.

This means no central authority is needed to establish trust. Two nodes can verify each other directly, the way two people can verify a handshake. If an impersonator tries to send a message claiming to be from a node they don't control, the signature check fails and the message is rejected.

---

## How Holonic Networks Work — Mycelium All the Way Down

### What Is a Holon?

Arthur Koestler coined the term **holon** for something that is simultaneously a *whole* and a *part*. A cell is a complete, self-sustaining organism — and also a component of a tissue, which is part of an organ, which is part of a body. At every scale, the same pattern holds: wholes that are also parts of larger wholes.

KOI networks are holonic. Each node is a complete knowledge system on its own — capable of storing, processing, and reasoning about knowledge independently. And each node is simultaneously a participant in a larger network, contributing to collective intelligence that no single node could achieve alone.

The remarkable property of this architecture: **a network of KOI nodes can itself function as a single node when seen from outside.** This is the fractal property — the same structure repeating at every scale, like mycelial networks that connect individual trees into groves, groves into forests, and forests into biomes.

### The Nesting

Consider how bioregions actually work:

```
    Your notebook (personal knowledge)
         ↓
    Landscape group (Greater Victoria)
         ↓
    Bioregional coordinator (Salish Sea)
         ↓
    Regional network (Cascadia)
         ↓
    Global commons (BKC CoIP)
```

At each level, the agent is a complete whole — Greater Victoria has its own knowledge graph, its own practices, its own community. But from the Salish Sea level, Greater Victoria is one contributor among several landscape groups. And from Cascadia's perspective, the entire Salish Sea is a single node — its internal complexity invisible, its external interface coherent.

This is exactly how mycelial networks operate in forests. Individual fungal threads connect specific root systems. Those local networks connect into larger mycorrhizal webs. The webs connect into forest-scale nutrient cycling systems. At each level, autonomous local function and larger-scale coordination coexist without contradiction.

Or, to use a metaphor closer to the Salish Sea: think of the octopus — nine brains working in concert, each arm sensing and responding independently while the central brain maintains coherence. No rigid hierarchy, no single point of failure. Intelligence distributed to the edges, where contact with the world actually happens. This is how Octo, the Salish Sea's bioregional agent, got its name — and why the architecture of distributed intelligence resonates with Coast Salish traditions that have long recognized the octopus (T'lep in SENCOŦEN, T'iithluup in Nuu-chah-nulth) as a figure of adaptive intelligence.

### What Makes It a "Swarm"

No central brain directs traffic in a KOI network. Each node senses its own environment, processes knowledge locally, and shares selectively with peers. Patterns emerge from the relationships between nodes — not from a master plan imposed from above.

This is not chaos. The shared protocols (RIDs, FUN events, signed envelopes) provide enough common structure for coordination, while the absence of central control preserves the autonomy and responsiveness that make distributed systems resilient. When a centralized system fails, everything fails. When one node in a mycelial network fails, the rest adapts and routes around the damage.

---

## From Personal Notes to Global Patterns

### The Knowledge Commoning Cycle

Here is the journey a piece of knowledge takes through the network:

**1. You document a practice.** In your notebook — an Obsidian vault, a field journal, a community wiki — you write about something happening in your place. "Herring egg monitoring in Saanich Inlet: community volunteers survey egg deposits on kelp fronds each spring."

**2. Your agent contributes it to the bioregional commons.** The practice is registered using the shared vocabulary — the BKC ontology, which provides 15 entity types (Practice, Pattern, Bioregion, Organization, and others) and 27 relationship predicates. The practice is linked to a place (Saanich Inlet), an organization (community monitoring group), and a concept (herring ecology).

**3. Similar practices surface across bioregions.** Another node in the Puget Sound documents "Forage fish spawning surveys: trained volunteers collect sand samples from beaches to monitor surf smelt and sand lance reproduction." A third node in the San Juan Islands documents "Citizen science kelp monitoring: kayak-based surveys tracking kelp canopy health."

**4. Patterns emerge.** When agents across bioregions share practices using the same vocabulary, it becomes possible to recognize *patterns* — generalizations that bridge across places. "Community-led marine ecological monitoring" is a pattern that aggregates from the herring surveys, the forage fish counts, and the kelp monitoring. The pattern is not any single practice — it is what they have in common.

**5. Patterns suggest new practices.** The pattern flows back down the network. A bioregional agent in the Strait of Georgia that has no marine monitoring program discovers the pattern and can explore what form it might take in their context. The pattern does not prescribe a specific approach — it *suggests* that community-led marine monitoring is a practice worth investigating.

**6. The cycle continues.** New practices inform existing patterns. New patterns suggest further practices. The commons grows through use, not through extraction.

```
    Practices ──────→ aggregate into ──────→ Patterns
        ↑                                        │
        └──────── suggest new ←────────────────┘
```

A critical design choice is baked into this cycle: **`aggregates_into` is not the inverse of `suggests`.** The first is observational and bottom-up — we *observe* that practices share characteristics. The second is prescriptive and top-down — a pattern *suggests* that something might be worth trying. These are epistemologically distinct operations. Treating them as inverses would collapse the difference between "what we see" and "what we recommend," which is exactly the kind of collapse that leads to knowledge systems imposing one community's practices on another.

---

## Data Sovereignty — Your Knowledge, Your Rules

### The Problem with Centralization

When knowledge goes into a single database controlled by a single organization, the communities that generated it lose their say. Who decides what gets included? Who decides how it is categorized? Who benefits from the patterns that emerge? Historically, the answer has been: whoever controls the database. This is not a hypothetical concern — it is the lived experience of Indigenous communities worldwide, whose knowledge has been extracted, decontextualized, and commodified for centuries.

### How KOI Enforces Sovereignty

KOI's architecture does not merely *allow* data sovereignty — it *enforces* it structurally:

**Each node stores its own knowledge locally.** There is no central database that everyone feeds into. Your knowledge lives on your infrastructure, under your control. The network connects nodes; it does not absorb them.

**Each node controls what enters.** When a signal arrives from the network, the receiving node's handler pipeline decides whether to accept, transform, or reject it. No external node can write to your knowledge graph.

**Each node controls what leaves.** When your node generates a signal, your network handler decides what to broadcast and to whom. You share what you choose to share, with the peers you choose to share it with.

**Cryptographic identity prevents impersonation.** Signed envelopes ensure that every message is verifiably from its claimed sender. No one can speak on behalf of a node they don't control.

### Sacred and Restricted Knowledge

This architecture has profound implications for Indigenous knowledge governance. An agent serving an Indigenous community can participate fully in a bioregional knowledge network — sharing secular ecological observations, collaborating on watershed stewardship — while keeping sacred knowledge entirely local. The architecture does not require that everything be shared in order to participate. Sovereignty is not an afterthought or a permission layer bolted on top — it is the foundational design principle.

This aligns with **OCAP** (Ownership, Control, Access, Possession) — the principles of Indigenous data governance developed by the First Nations Information Governance Centre. In KOI:

- **Ownership**: Each node owns its knowledge. The network has no claim on it.
- **Control**: Each node controls what is shared, with whom, and in what form.
- **Access**: Each node determines who can query its knowledge and under what conditions.
- **Possession**: Knowledge is physically stored on the node's own infrastructure — no third-party custodian.

### The Cosmolocal Principle

The design philosophy can be summarized in a single principle: **design global, implement local.** What is light — protocols, ontologies, patterns — is shared freely across the network. What is heavy — local knowledge, community relationships, place-based wisdom — stays sovereign.

This is sometimes called the **cosmolocal** pattern: global coordination of lightweight, shareable resources (like open-source software, or a shared vocabulary for knowledge organization) combined with local stewardship of context-specific, place-based knowledge. KOI is the infrastructure that makes the cosmolocal pattern operational for knowledge commons.

---

## Knowledge Commoning vs. Data Sharing

These terms sound similar but describe fundamentally different things.

**Data sharing** means: I give you my spreadsheet. You now have a copy of my data. It sits in your system, decontextualized from the relationships and practices that gave it meaning. If I update my data, your copy is stale. If you misinterpret it, I have no recourse.

**Knowledge commoning** means: We maintain a living, relational web of meaning together, where each of us contributes from our own perspective and retains sovereignty over our contributions. Knowledge flows through the network as living signals — events, references, cross-links — not as static snapshots. The relationships between pieces of knowledge are as important as the pieces themselves.

### The Ontology as Bridge Language

For knowledge to flow across bioregions, there must be enough shared vocabulary to recognize similarity. But too much standardization colonizes local ways of knowing — forcing everyone to describe their world through someone else's categories.

The BKC ontology is positioned as a **bridge language** — not a claim about how reality is organized, but the minimum shared vocabulary needed for cross-bioregional communication. The analogy is natural language: English serves as a lingua franca for international science not because it is the best or most nuanced language, but because having *some* shared medium enables connection. Each community still speaks its own language internally. The act of translation is acknowledged as imperfect — something is always lost, something is always gained. But the alternative (no communication at all, or forced adoption of a single framework) is worse.

The BKC ontology provides 15 entity types and 27 relationship predicates — enough to communicate across bioregions, not so much that it imposes a worldview. Internally, each node can organize knowledge however makes sense for its community. At the boundaries where knowledge crosses between nodes, the shared vocabulary enables conversation.

### Three-Layer Preservation

When knowledge enters the network, three layers are preserved:

1. **Source layer**: The original material in its original form — a field report, an interview transcript, a dataset. Nothing is discarded.
2. **Mapping layer**: An explicit record of how the source was translated into the shared vocabulary. This layer is transparent about interpretation: "We identified this as a Practice according to the BKC ontology."
3. **Commons layer**: The knowledge expressed in the shared vocabulary, ready for cross-bioregional pattern mining.

No knowledge is lost in translation because the translation itself is documented. If a future community decides the BKC ontology miscategorized something, the original source is always available for re-interpretation.

> *"Ontologies can emerge from practice and, therefore, better fit the communities they're serving, and adapt as those communities adapt, grow and change, fork and merge."*
> — Michael Zargham, "Architecting Knowledge Organization Infrastructure"

---

## How Agents Actually Collaborate

### The Handshake

When two KOI nodes meet for the first time, they perform a handshake — exchanging identities, verifying cryptographic keys, and agreeing on what kinds of knowledge to share. This is like two mycorrhizal networks encountering each other at the boundary between two forest stands: they establish a connection, negotiate the interface, and begin exchanging resources according to their respective needs.

The handshake creates an **edge** — a defined relationship between two nodes. Edges specify what types of knowledge flow between the nodes and in which direction. One node might share practices and patterns but not people. Another might only accept knowledge about marine ecology. The edge profile is agreed upon by both parties.

### The Polling Cycle

Once connected, nodes regularly check in with their peers. "Anything new?" A node that has been generating FUN events (new practices documented, existing knowledge updated) shares those events with connected peers during the polling cycle. Events flow through the network in waves — not instantly, but incrementally, the way nutrients move through mycelium over hours and days rather than milliseconds.

This asynchronous, pull-based model is deliberate. Nodes are not flooded with information they did not request. Each node polls at its own pace, processes what it receives according to its own logic, and integrates knowledge on its own schedule. The network respects each node's autonomy even in its communication patterns.

### Cross-Referencing

When an agent in the Salish Sea receives a signal about "Herring Monitoring" from a Cowichan Valley node, it does not simply file the information. It asks: *Do I already know about this?* The agent runs entity resolution — first checking for exact matches, then fuzzy text matching, then semantic similarity — to determine whether this is something it already tracks under a different name, or something genuinely new.

If it finds a match, it creates a **cross-reference**: a link that says "what the Cowichan Valley calls 'Community Herring Watch' is what we call 'Herring Egg Monitoring' — same practice, different local name." These cross-references are the connective tissue of the network, enabling pattern mining across bioregions without forcing everyone to use identical terminology.

### Self-Healing

Distributed systems encounter failures — a node goes offline, a connection drops, a key expires. KOI nodes are designed to recover automatically. If a peer is unreachable, the poller backs off and retries. If a cryptographic key is missing, the node re-initiates a handshake. If events are missed during an outage, they are caught up on the next successful poll. No human intervention is needed for routine federation issues — the network heals itself, the way mycelial networks reroute nutrient flows around damaged sections.

---

## A Nervous System for the Bioregion

David Sisson, drawing on neuroscience, proposes that KOI networks develop through stages that parallel how biological nervous systems process information:

**Sensation.** Individual sensors provide raw observations — a field report, a monitoring dataset, a community survey. This is the network's contact with the world: diverse, granular, place-specific.

**Perception.** Local networks contextualize raw observations — connecting the field report to known organizations, linking the dataset to established practices, situating the survey within a bioregional context. Perception is where isolated data points become meaningful knowledge.

**Cognition.** Bioregional agents reason across their knowledge — recognizing patterns, identifying gaps, surfacing connections that no single observer could see. This is group-level sense-making: the bioregion developing the capacity to understand itself.

**Metacognition.** The meta-network reflects on how knowledge is organized — questioning whether the shared vocabulary is adequate, whether the patterns being mined are genuine or artifacts of the framework, whether the process is serving the communities it claims to serve. This is thinking about thinking — the crucial capacity that distinguishes wisdom from mere intelligence.

> *"The very purpose of KOI is to ask, 'how are we doing group-level cognition? And, are we okay with it?'"*
> — David Sisson, "KOI Nodes as Neurons"

### The Untested Hypothesis

At the heart of this work lies a hypothesis that has not yet been proven: that documenting practices across enough bioregions will reveal trans-bioregional patterns — generalizations that hold across places, cultures, and ecological contexts. That herring monitoring in the Salish Sea, community fisheries management in coastal British Columbia, and marine stewardship in the San Juan Islands share enough structure to constitute a *pattern* — and that recognizing this pattern will help communities that haven't yet started.

KOI is the infrastructure to test this hypothesis. Not to assert it as truth in advance, but to build the conditions under which it can be investigated, confirmed, or refuted by the communities themselves.

The mycelial metaphor holds here too. We know that fungal networks transfer resources between trees. We know that forests with intact mycelial networks are more resilient than fragmented ones. But the specific patterns of exchange — which trees share with which, under what conditions, and what emerges from the network as a whole — are still being discovered. The network itself is the instrument of discovery.

### An Invitation

KOI is not a finished product. It is an emerging infrastructure — technically functional, conceptually grounded, and still growing. The code runs. The federation works. Two nodes in the Salish Sea exchange knowledge today. But the vision is larger: a global web of bioregional knowledge commons, connected by shared protocols, grounded in local sovereignty, generating patterns that no single community could see alone.

If you are a bioregional practitioner, a community organizer, a researcher, or simply someone who cares about how knowledge is held and shared — this network has a place for you. Not as a user of someone else's platform, but as a sovereign node in a living web.

The mycelium is growing. The invitation is to connect.

> *"The knowledge graphs we build, the maps we create, the patterns we mine, the relationships we track — these are not about observing the bioregion from outside. They are the bioregion developing new organs of perception. The living system learning to see itself more clearly, so it can heal itself more effectively."*

---

*To learn more about joining the network as a bioregional node, see [Joining the Network](./join-the-network.md). For the technical architecture, see [Holonic Bioregional Knowledge Commons](./holonic-bioregional-knowledge-commons.md). For the ontology design, see [Ontological Architecture](./ontological-architecture.md).*
