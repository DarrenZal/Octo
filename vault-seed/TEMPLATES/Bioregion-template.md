---
# Bioregion Template — BKC Vault Note
#
# Field names are parser-recognized aliases from
# koi-processor/api/vault_parser.py (FIELD_TO_PREDICATE mapping).

"@type": "bkc:Bioregion"
name: "Your Bioregion Name"
description: "One-line description of the bioregion and its defining features"

# ── Relationships ──────────────────────────────────────────────────
broader:                                # → broader predicate (parent bioregion)
  - "[[Bioregions/Cascadia]]"

# ── Metadata ───────────────────────────────────────────────────────
tags:
  - bioregion
---

# Your Bioregion Name

Describe the bioregion: geographic boundaries, defining ecosystems, cultural context.

---

## Filled Example: Salish Sea

```yaml
---
"@type": "bkc:Bioregion"
name: Salish Sea
description: Inland sea shared between British Columbia and Washington State
broader:
  - "[[Bioregions/Cascadia]]"
tags:
  - bioregion
  - salish-sea
---
```
