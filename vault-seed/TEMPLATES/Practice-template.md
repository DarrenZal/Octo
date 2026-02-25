---
# Practice Template — BKC Vault Note
#
# All field names below are parser-recognized aliases defined in
# koi-processor/api/vault_parser.py (FIELD_TO_PREDICATE mapping).
# Use these exact field names — they are mapped to ontology predicates
# when ingested by the KOI API.

"@type": "bkc:Practice"
name: "Your Practice Name"
description: "One-line summary of what this practice is and where it happens"

# ── Relationships ──────────────────────────────────────────────────
# Each field maps to a predicate in the BKC ontology.
# Values are wikilinks to other vault notes.

bioregion:                              # → practiced_in predicate
  - "[[Bioregions/Your Bioregion]]"

aggregatesInto:                         # → aggregates_into (links to a Pattern)
  - "[[Patterns/Related Pattern]]"

people:                                 # → involves_person
  - "[[People/Key Person]]"

parentOrg:                              # → involves_organization
  - "[[Organizations/Steward Org]]"

documentedBy:                           # → documents (incoming from CaseStudy)
  - "[[CaseStudies/Your Case Study]]"

inspiredBy:                             # → inspired_by
  - "[[Practices/Related Practice]]"

# ── Metadata ───────────────────────────────────────────────────────
activityStatus: alive                   # alive | dormant | historical
tags:
  - your-tags-here
---

# Your Practice Name

Describe the practice: what it is, who does it, where, and why it matters to the bioregion.

---

## Filled Example: Herring Monitoring

```yaml
---
"@type": "bkc:Practice"
name: Herring Monitoring
description: Community-led monitoring of Pacific herring spawning in the Salish Sea
bioregion:
  - "[[Bioregions/Salish Sea]]"
aggregatesInto:
  - "[[Patterns/Commons Resource Monitoring]]"
people:
  - "[[People/Eli Ingraham]]"
documentedBy:
  - "[[CaseStudies/Salish Sea Herring Case]]"
inspiredBy:
  - "[[Practices/Indigenous Fisheries Management]]"
activityStatus: alive
tags:
  - herring
  - monitoring
  - community-science
---
```
