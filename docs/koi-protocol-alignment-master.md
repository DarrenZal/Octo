# Octo KOI Protocol Alignment: Master Reference Document

> **Purpose:** Authoritative reference for tracking Octo's alignment with BlockScience koi-net protocol compliance.
> **Status:** Living document — update as phases complete.
> **Created:** 2026-02-18 | **Author:** Darren Zal, with research from BlockScience source analysis
> **See also:** [`koi-alignment.md`](./koi-alignment.md) — original gap analysis and phase plan
> **Last session:** 2026-02-19 (commit 9ea1e11, session 36a1507d)

---

## 1. Executive Summary

### Status Dashboard

| Phase | Description | Status |
|-------|-------------|--------|
| **P0** | Interop/Security Hardening | **COMPLETE** |
| **P0.5** | Node RID Migration (b64_64) | **COMPLETE** |
| **P0.6** | Bootstrap Self-Introduction | **COMPLETE** |
| **P0.7** | Error Response Schema | **COMPLETE** |
| **P0.8** | POLL Edge Enforcement | **COMPLETE** |
| **P1** | Manifest Canonicalization (JCS via rid-lib) | **COMPLETE** |
| **P2** | Conformance Test Expansion | **COMPLETE** |
| **P3** | Handler Chain Pipeline | **COMPLETE** |
| **P4** | Protocol Surface Cleanup | **COMPLETE** |
| **P5** | NodeProfile Ontology Fields | **COMPLETE** |
| **P6** | UPDATE-Aware Cross-Ref Upsert | **COMPLETE** |
| **P7** | Resolution Primitives + Multi-Tier Federation | **COMPLETE** |
| **P8** | WEBHOOK Edge Push Delivery | **COMPLETE** |
| **P9** | Private Key Encryption | **COMPLETE** |

### Test Coverage Matrix

**98 pytest tests** (`test_koi_policy.py` 28 + `test_koi_conformance.py` 14 + `test_koi_pipeline.py` 39 + `test_resolution_primitives.py` 12 + `test_koi_conformance.py` 5 live-marked) + **11 interop checks** (`test_koi_interop.py`, script-based).

| Test Function | File | Capabilities Covered |
|---------------|------|---------------------|
| `test_node_rid_binding_accepts_legacy_and_der64_hashes` | test_koi_policy.py:31 | Node identity, legacy16 compat, b64_64 compat |
| `test_node_rid_binding_rejects_wrong_key` | test_koi_policy.py:41 | Node identity, key-RID binding rejection |
| `test_verify_envelope_enforces_expected_nodes` | test_koi_policy.py:52 | Signed envelope, target_node enforcement |
| `test_security_policy_defaults_to_strict_when_enabled` | test_koi_policy.py:79 | Security policy, strict mode defaults |
| `test_security_policy_allows_explicit_override` | test_koi_policy.py:92 | Security policy, fine-grained toggles |
| `test_manifest_hash_derived_when_missing` | test_koi_policy.py:105 | Manifest hashing, derivation fallback |
| `test_b64_64_matches_blockscience_canonical` | test_koi_policy.py:121 | Node identity, BlockScience `sha256_hash(pub_key.to_der())` alignment |
| `test_b64_64_is_default_hash_mode` | test_koi_policy.py:137 | Node identity, default hash mode |
| `test_node_rid_matches_b64_64` | test_koi_policy.py:146 | Node identity, b64_64 RID matching |
| `test_legacy16_is_prefix_of_b64_64` | test_koi_policy.py:153 | Node identity, legacy16↔b64_64 relationship |
| `test_error_type_map_covers_identity_errors` | test_koi_policy.py:166 | Error schema, BlockScience ErrorType mapping |
| `test_pre_auth_errors_do_not_map_to_unknown_node` | test_koi_policy.py:174 | Error schema, handshake-retry safety |
| `test_default_error_type_is_not_unknown_node` | test_koi_policy.py:187 | Error schema, fallback safety |
| `test_extract_bootstrap_key_succeeds_with_valid_payload` | test_koi_policy.py:224 | Bootstrap, FORGET+NEW extraction, key-RID binding |
| `test_extract_bootstrap_key_rejects_wrong_key` | test_koi_policy.py:239 | Bootstrap, forged key rejection |
| `test_extract_bootstrap_key_returns_none_for_non_bootstrap` | test_koi_policy.py:272 | Bootstrap, non-bootstrap payload handling |
| `test_strict_mode_enables_require_approved_edge_for_poll` | test_koi_policy.py:288 | POLL edge enforcement, strict mode auto-enable |
| `test_poll_edge_enforcement_can_be_explicit` | test_koi_policy.py:296 | POLL edge enforcement, independent config |
| `test_manifest_hash_uses_jcs_not_json_dumps` | test_koi_policy.py:310 | JCS canonicalization, rid-lib dependency |
| `test_manifest_hash_matches_blockscience_reference` | test_koi_policy.py:321 | JCS canonicalization, frozen reference vector |
| `test_manifest_hash_deterministic_across_key_order` | test_koi_policy.py:334 | JCS canonicalization, key-order independence |
| `test_node_profile_ontology_fields` | test_koi_policy.py | P5: NodeProfile ontology fields serialize correctly |
| `test_node_profile_ontology_optional` | test_koi_policy.py | P5: Ontology fields are optional (backward compat) |
| `test_save_and_load_encrypted_key` | test_koi_policy.py | P9: Encrypted key round-trip (save → load → sign → verify) |
| `test_load_unencrypted_key_still_works` | test_koi_policy.py | P9: Unencrypted key backward compatibility |
| `test_encrypted_key_derives_same_rid` | test_koi_policy.py | P9: Encryption preserves public key → same node RID |
| `test_encrypted_key_wrong_password_fails` | test_koi_policy.py | P9: Wrong password raises clear error |
| `test_encrypted_key_no_password_fails` | test_koi_policy.py | P9: Encrypted key without password raises error |

#### Pipeline Tests (test_koi_pipeline.py)

| Test Function | File | Capabilities Covered |
|---------------|------|---------------------|
| `test_1_handler_chain_executes_in_order` | test_koi_pipeline.py | Pipeline infrastructure, handler ordering |
| `test_2_stop_chain_halts_and_returns_none` | test_koi_pipeline.py | STOP_CHAIN semantics |
| `test_3_handler_returning_none_passes_kobj_unchanged` | test_koi_pipeline.py | Passthrough semantics |
| `test_4_handler_returning_modified_kobj_propagates` | test_koi_pipeline.py | KnowledgeObject mutation propagation |
| `test_5_rid_types_filtering_skips_nonmatching` | test_koi_pipeline.py | Handler rid_types filtering |
| `test_6_event_types_filtering_skips_nonmatching` | test_koi_pipeline.py | Handler event_types filtering |
| `test_7_phases_execute_in_order` | test_koi_pipeline.py | 5-phase ordering (RID→Manifest→Bundle→Network→Final) |
| `test_8_stop_chain_in_rid_skips_all_later_phases` | test_koi_pipeline.py | Cross-phase STOP_CHAIN propagation |
| `test_9_forget_sets_flag_and_deletes` | test_koi_pipeline.py | FORGET handler parity (flag + DELETE + STOP_CHAIN) |
| `test_10_forget_event_never_reaches_cross_reference_resolver` | test_koi_pipeline.py | FORGET early-exit semantics preservation |
| `test_11_new_event_matching_entity` | test_koi_pipeline.py | Cross-ref resolution parity (same_as, confidence 1.0) |
| `test_12_new_event_no_match` | test_koi_pipeline.py | Unresolved cross-ref creation parity |
| `test_13_upgrade_unresolved_cross_ref` | test_koi_pipeline.py | Cross-ref upgrade parity (unresolved → same_as) |
| `test_14_extract_entity_type_strips_bkc_prefix` | test_koi_pipeline.py | Entity type extraction, bkc: prefix stripping |
| `test_14b_extract_entity_type_no_prefix` | test_koi_pipeline.py | Entity type extraction, no prefix |
| `test_14c_extract_entity_type_fallback_to_entity_type_key` | test_koi_pipeline.py | Entity type extraction, fallback key |
| `test_async_handler_is_awaited` | test_koi_pipeline.py | Async handler support (inspect.isawaitable) |
| `test_knowledge_object_defaults` | test_koi_pipeline.py | KnowledgeObject dataclass defaults |
| `test_extract_rid_type_is_public` | test_koi_pipeline.py | extract_rid_type public API promotion |
| `test_20_block_self_referential_external` | test_koi_pipeline.py | P3b: block external self-referential events (STOP_CHAIN) |
| `test_21_block_self_referential_source_none` | test_koi_pipeline.py | P3b: local events (source=None) pass through |
| `test_22_block_self_referential_source_is_self` | test_koi_pipeline.py | P3b: self-originated events pass through |
| `test_23_block_self_referential_different_rid` | test_koi_pipeline.py | P3b: different RID from external peer passes through |
| `test_24_block_self_referential_before_forget_delete` | test_koi_pipeline.py | P3b: block fires before forget_delete (no DELETE issued) |
| `test_25_entity_type_validator_unknown` | test_koi_pipeline.py | P3b: unknown entity type passes through, debug logged |
| `test_26_entity_type_validator_known` | test_koi_pipeline.py | P3b: known entity type passes silently |
| `test_29_update_event_reresolved` | test_koi_pipeline.py | P6: UPDATE event triggers cross-ref re-resolution |
| `test_30_update_event_same_resolution` | test_koi_pipeline.py | P6: UPDATE with same match is a no-op |
| `test_31_new_event_still_upgrades_unresolved` | test_koi_pipeline.py | P6: NEW event still upgrades unresolved cross-refs |
| `test_32_crossref_resolver_alias_match` | test_koi_pipeline.py | P7: Alias-based entity matching in cross-ref resolution |
| `test_33_crossref_resolver_exact_still_works` | test_koi_pipeline.py | P7: Exact match still works with alias support |
| `test_34_crossref_resolver_no_match_still_unresolved` | test_koi_pipeline.py | P7: No match creates unresolved cross-ref |
| `test_35_event_queue_peek_does_not_mark` | test_koi_pipeline.py | P8: peek_undelivered is side-effect free |
| `test_36_event_queue_mark_delivered` | test_koi_pipeline.py | P8: mark_delivered updates tracking, excludes from peek |
| `test_37_mark_delivered_idempotent` | test_koi_pipeline.py | P8: Idempotent delivery marking |
| `test_38_webhook_push_failure_preserves_events` | test_koi_pipeline.py | P8: Failed push preserves events for retry |
| `test_39_event_insert_dedup` | test_koi_pipeline.py | P8: Duplicate event_id insertion is idempotent |
| `test_40_webhook_key_refresh_on_missing` | test_koi_pipeline.py | P8: Missing peer key triggers _learn_peer_public_key refresh |
| `test_41_webhook_key_refresh_on_stale` | test_koi_pipeline.py | P8: Stale peer key triggers refresh and retry |

#### Interop Checks (test_koi_interop.py — script-based, run against live instance)

| Check | Description | Capabilities Covered |
|-------|-------------|---------------------|
| [0] | Health check (`GET /koi-net/health`) | Node identity, health endpoint |
| [1] | Generate test keypair (b64_64) | Key generation, hash mode |
| [2] | Handshake (register test node) | Handshake endpoint, peer registration |
| [3] | Signed poll request | Signed envelope, poll endpoint |
| [4] | Fetch RIDs | RID listing endpoint |
| [5] | Fetch manifests (if events exist) | Manifest endpoint, Z-suffix timestamps |
| [6] | Fetch bundles (if events exist) | Bundle endpoint |
| [7] | Unsigned poll | Unsigned fallback (non-strict mode) |
| [8] | Verify b64_64 matches BlockScience canonical hash | Node identity, cross-implementation hash |
| [9] | Error response schema (`type: "error_response"`) | Error schema, BlockScience ErrorType |
| [10] | Broadcast bootstrap (self-introduction) | Bootstrap, FORGET+NEW pattern |

---

## 2. Protocol Reference (BlockScience koi-net Spec)

### 2.1 Endpoints

All endpoints live under the `/koi-net` base path. Every request and response is wrapped in `SignedEnvelope[T]`.

| Endpoint | Method | Request Type | Response Type |
|----------|--------|-------------|---------------|
| `/koi-net/events/broadcast` | POST | `SignedEnvelope[EventsPayload]` | varies (async) |
| `/koi-net/events/poll` | POST | `SignedEnvelope[PollEvents]` | `SignedEnvelope[EventsPayload]` |
| `/koi-net/rids/fetch` | POST | `SignedEnvelope[FetchRids]` | `SignedEnvelope[RidsPayload]` |
| `/koi-net/manifests/fetch` | POST | `SignedEnvelope[FetchManifests]` | `SignedEnvelope[ManifestsPayload]` |
| `/koi-net/bundles/fetch` | POST | `SignedEnvelope[FetchBundles]` | `SignedEnvelope[BundlesPayload]` |

### 2.2 FUN Event Model

Three event types defined in `EventType` (StrEnum):
- **NEW** — First appearance of a resource
- **UPDATE** — Resource contents changed
- **FORGET** — Resource removed (manifest=None in wire format)

### 2.3 Edge Protocol

Edge types: `POLL` (target polls source) and `WEBHOOK` (source pushes to target).

Orientation: `source_node` = provider, `target_node` = consumer.

For POLL edges: the poller is the target, the provider is the source. The poller sends `POST /koi-net/events/poll` to the source's `base_url`.

### 2.4 Handler Chain (BlockScience Reference)

BlockScience's `KnowledgePipeline.process()` runs a 5-phase pipeline:
1. **RID phase** — RID type routing and validation
2. **Manifest phase** — Manifest hash verification
3. **Bundle phase** — Content extraction and validation
4. **Network phase** — Peer discovery, edge updates
5. **Final phase** — Application-level processing

### 2.5 Node Identity

Node RID format: `orn:koi-net.node:{name}+{hash_suffix}`

Hash derivation (BlockScience canonical):
```python
# config.py: sha256_hash(pub_key.to_der())
der_bytes = public_key.public_bytes(DER, SubjectPublicKeyInfo)
der_b64 = base64.b64encode(der_bytes).decode()
hash_suffix = hashlib.sha256(der_b64.encode()).hexdigest()  # 64 hex chars
```

### 2.6 Signed Envelope

- **Algorithm:** ECDSA P-256 (secp256r1)
- **Signature format:** Raw `r||s` (64 bytes), base64-encoded
- **Signing input:** `UnsignedEnvelope.model_dump_json(exclude_none=True)` encoded as UTF-8
- **Validation order:** (1) resolve sender key, (2) verify `target_node == self`, (3) verify signature, (4) verify key-RID binding

### 2.7 RID Types and Manifests

RIDs are references (not the resource itself). Manifests contain `{rid, timestamp, sha256_hash}`. The `sha256_hash` is computed via JCS (JSON Canonicalization Scheme) — `rid-lib` provides `sha256_hash_json()`.

### 2.8 Error Types

BlockScience defines `ErrorType` enum (snake_case values):
- `unknown_node` — triggers handshake retry in clients
- `invalid_key` — key-RID binding failure
- `invalid_signature` — signature verification failure
- `invalid_target` — target_node mismatch

---

## 3. Current State Assessment (Octo)

### 3.1 Protocol Endpoints

8 routes (5 core + 3 extensions) in `koi_net_router.py`:

| Route | Type | Line | Description |
|-------|------|------|-------------|
| `POST /handshake` | Extension | :532 | Exchange NodeProfile, establish edges |
| `POST /events/broadcast` | Core | :588 | Receive events from peers |
| `POST /events/poll` | Core | :629 | Serve queued events to polling nodes |
| `POST /events/confirm` | Extension | :710 | Acknowledge receipt of events |
| `POST /manifests/fetch` | Core | :734 | Serve manifests by RID |
| `POST /bundles/fetch` | Core | :771 | Serve bundles by RID |
| `POST /rids/fetch` | Core | :814 | List available RIDs |
| `GET /health` | Extension | :854 | Node identity, peers, capabilities |

### 3.2 Signed Envelopes

**File:** `koi_envelope.py`

- ECDSA P-256 with raw `r||s` base64 signatures (`koi_envelope.py:77-98`)
- `UnsignedEnvelope` model with `exclude_none=True` (`koi_envelope.py:49-55`)
- `EnvelopeError` with typed error codes (`koi_envelope.py:35-40`)
- Key loading from DER-encoded base64 strings (`koi_envelope.py:117-122`)
- Graceful degradation when `cryptography` not installed (`koi_envelope.py:20-32`)

### 3.3 Wire Format

**File:** `koi_protocol.py`

- `WireEvent` with `extra="forbid"` (`koi_protocol.py:39-47`) — strict field set
- `WireManifest` with `{rid, timestamp, sha256_hash}` (`koi_protocol.py:32-36`)
- Z-suffix timestamps via `timestamp_to_z_format()` (`koi_protocol.py:172-180`)
- `type` discriminator fields on all request/response models (matches BlockScience `api_models.py`)
- `EventType` as `StrEnum` (`koi_protocol.py:22-25`)

### 3.4 Node Identity

**File:** `node_identity.py`

- Default hash mode: `b64_64` = `sha256(base64(DER(pubkey)))` — BlockScience canonical (`node_identity.py:85-99`)
- Legacy `legacy16` = first 16 chars of b64_64 hash (`node_identity.py:100-102`)
- `node_rid_matches_public_key()` accepts b64_64, legacy16, and der64 with per-mode allow flags (`node_identity.py:113-133`)
- Key storage: `/root/koi-state/{node_name}_private_key.pem` — password encryption via `PRIV_KEY_PASSWORD` env var (matches BlockScience `secure.py`)

### 3.5 Event Queue

**File:** `event_queue.py`

- Database-backed (PostgreSQL) per-node delivery tracking (`event_queue.py:26-131`)
- `delivered_to` and `confirmed_by` as PostgreSQL `TEXT[]` arrays (`039_koi_net_events.sql:15-16`)
- TTL-based expiration with `expires_at` column (default 24h, remote 72h) (`event_queue.py:22-23`)
- RID type filtering via `_extract_rid_type()` from RID string format (`event_queue.py:180-201`)

### 3.6 Manifest Hashing

**File:** `koi_net_router.py:168-185`

- JCS-canonical hashing via `rid-lib` — hard dependency, no fallback (`koi_net_router.py:69`)
- `_canonical_sha256_json()` delegates to `rid_sha256_hash_json()` from `rid_lib.ext.utils` (`koi_net_router.py:168-170`)
- `_manifest_sha256_hash()` derives hash from contents when `sha256_hash` field is absent (`koi_net_router.py:173-185`)

**Design decision — fail-fast on hash errors:** `_canonical_sha256_json()` failures are **not** caught by the endpoint-level exception handlers (which only catch `EnvelopeError` from `_unwrap_request`). This is intentional — a hash failure means corrupt data in the database, not a recoverable protocol condition. The resulting HTTP 500 surfaces in server logs for diagnosis. This is documented as a design decision, not a gap.

### 3.7 Poller

**File:** `koi_poller.py`

- Async background task with `asyncio.create_task()` (`koi_poller.py:80`)
- Time-based exponential backoff with retry windows:
  - `min(30 * 2^(failures-1), 600)` seconds
  - tracked per peer as `next_retry_at` (POLL and WEBHOOK separately)
  - automatic recovery once retry window elapses and peer becomes reachable (no restart required)
- Self-healing handshake: on "No public key for" error, sends handshake then retries once (`koi_poller.py:272-284`)
- Peer key learning from `/koi-net/health` endpoint (`koi_poller.py:262-310`)
- Signed request/response support with policy enforcement (`koi_poller.py:47-54`)
- WEBHOOK push delivery: `_push_webhook_peers()` pushes events to WEBHOOK subscribers (`koi_poller.py:173-270`)
- Key-refresh fallback on both poll and webhook flows: stale/missing peer keys trigger `_learn_peer_public_key()` before giving up

### 3.8 Bootstrap

**File:** `koi_net_router.py:331-399`

- Unknown nodes self-introduce via `/events/broadcast` with FORGET+NEW events carrying `NodeProfile` + `public_key`
- Key-RID binding verified before trust: checks suffix against both b64_64 and legacy16 hashes (`koi_net_router.py:383-389`)
- Two-phase: `_extract_bootstrap_key()` (pure logic, no DB write) → signature verification → `_persist_bootstrap_peer()` (DB upsert)
- Persisted only after envelope signature verification succeeds (`koi_net_router.py:514-516`)

### 3.9 Error Schema

**File:** `koi_net_router.py:114-157`

- `_ERROR_TYPE_MAP` maps Octo error codes → BlockScience `ErrorType` values (`koi_net_router.py:120-134`)
- All protocol errors include `type: "error_response"` + `error: <ErrorType>` + `error_code` + `message` (`koi_net_router.py:141-157`)
- Pre-auth/parse errors map to `invalid_signature` (not `unknown_node`) to prevent false handshake retries (`koi_net_router.py:127-133`)
- Default fallback: `invalid_signature` (`koi_net_router.py:138`)

### 3.10 Cross-References

**File:** `koi_poller.py:357-449`, Schema: `041_cross_references.sql`

- Local↔remote entity linking via `koi_net_cross_refs` table
- Tier 1 exact-match resolution against `entity_registry` (`koi_poller.py:396-406`)
- Relationship types: `same_as` (confidence 1.0), `related_to`, `unresolved` (confidence 0.0)
- Upgrade path: unresolved cross-refs auto-upgrade when local match appears (`koi_poller.py:424-431`)
- FORGET events delete cross-references (`koi_poller.py:368-377`)

---

## 4. Gap Analysis

| Gap | Severity | Phase | Status | Notes |
|-----|----------|-------|--------|-------|
| Handler chain pipeline | Medium | P3 | **COMPLETE** | 5-phase pipeline in `api/pipeline/`, feature-flagged via `KOI_USE_PIPELINE` |
| Conformance tests vs koi-net package | Medium | P2 | **COMPLETE** | 14 offline + 5 live tests in `test_koi_conformance.py` |
| Poller semantic resolution | Low | P7 | **COMPLETE** | Multi-tier resolution primitives (exact, alias, fuzzy) in `resolution_primitives.py` |
| WEBHOOK edge type | Low | P8 | **COMPLETE** | Full push delivery with key-refresh fallback in `koi_poller.py` |
| UPDATE differential logic | Low | P6 | **COMPLETE** | UPDATE-aware cross-ref upsert with re-resolution |
| NodeProfile ontology fields | Low | P5 | **COMPLETE** | `ontology_uri`, `ontology_version` in NodeProfile + migration 046 |
| Protocol surface docs | Low | P4 | **COMPLETE** | Core vs extension documented in health endpoint and master doc |
| Private key encryption | Low | P9 | **COMPLETE** | `PRIV_KEY_PASSWORD` env var support, `BestAvailableEncryption`, migration script |

---

## 5. Production Federation Topology

| Node | RID (truncated) | Host | Peer-Reachable URL | Status |
|------|-----------------|------|-------------------|--------|
| **Octo** | `octo-salish-sea+50a3c9ea...` | `45.132.245.30` | `http://45.132.245.30:8351` (nginx gateway) | Live, coordinator |
| **GV** | `greater-victoria+81ec47d8...` | `37.27.48.12` (poly) | `http://37.27.48.12:8351` | Live, leaf (remote) |
| **Regen** | `koi-coordinator-main+c5ca332d...` | BlockScience | `https://regen.gaiaai.xyz/api/koi/coordinator` | Live, federated |
| **Front Range** | `front-range+b5429ae7...` | `45.132.245.30` (local) | `http://127.0.0.1:8355` (localhost-only) | Live, peer |
| **Cowichan** | `cowichan-valley+52ae5cd1...` | `202.61.242.194` | `http://202.61.242.194:8351` | Live, leaf |

**Notes:**
- Peer-reachable URL is what's stored in `koi_net_nodes.base_url` and returned via `GET /koi-net/health`.
- The nginx gateway at `45.132.245.30:8351` proxies only `/koi-net/*` and `/health` paths to the internal Octo API.
- GV migrated from Octo-local (`127.0.0.1:8352`) to remote on poly (`37.27.48.12:8351`) on 2026-02-18. Same keypair, RID preserved.
- Port 8351 on poly is firewalled via iptables `KOI_FEDERATION` chain — only Octo (`45.132.245.30`) and CV (`202.61.242.194`) are allowed.
- FR runs on the same host as Octo (localhost:8355), federates bidirectionally with Octo only. External nodes reach FR knowledge through Octo (peer-through-coordinator topology).

---

## 6. Implementation Phases (Detail)

### Phase P0: Interop/Security Hardening — COMPLETE

**Goal:** Make Octo's protocol surface reject malformed and forged requests without rewriting internals.

**Delivered:**
- `KOI_STRICT_MODE` flag with fine-grained toggles (`koi_net_router.py:88-111`)
- Unsigned-envelope rejection controls (handshake exception preserved) (`koi_net_router.py:460-466`)
- Explicit `target_node == self` enforcement (`koi_net_router.py:473-477`)
- Sender RID/public-key binding checks (`koi_net_router.py:492-504`)

**Validation:**
- [x] `test_security_policy_defaults_to_strict_when_enabled`
- [x] `test_security_policy_allows_explicit_override`
- [x] `test_verify_envelope_enforces_expected_nodes`
- [x] `test_node_rid_binding_accepts_legacy_and_der64_hashes`
- [x] `test_node_rid_binding_rejects_wrong_key`

### Phase P0.5: Node RID Migration (b64_64) — COMPLETE

**Goal:** Migrate from legacy16 (16-char truncated) to b64_64 (64-char BlockScience canonical) node RIDs.

**Delivered:**
- `derive_node_rid_hash()` with `b64_64` as default mode (`node_identity.py:85-105`)
- `node_rid_matches_public_key()` with multi-mode accept logic (`node_identity.py:113-133`)
- `KOI_ALLOW_LEGACY16_NODE_RID=true` for migration compatibility (`koi_net_router.py:96`)
- Same keypairs, full SHA-256 hash suffix — no key regeneration needed

**Validation:**
- [x] `test_b64_64_matches_blockscience_canonical`
- [x] `test_b64_64_is_default_hash_mode`
- [x] `test_node_rid_matches_b64_64`
- [x] `test_legacy16_is_prefix_of_b64_64`
- [x] Interop check [8]: b64_64 cross-implementation hash verification

### Phase P0.6: Bootstrap Self-Introduction — COMPLETE

**Goal:** Allow unknown nodes to self-introduce via broadcast, matching BlockScience's `handshake_with` pattern.

**Delivered:**
- `_extract_bootstrap_key()` extracts and validates key from FORGET+NEW payload (`koi_net_router.py:331-399`)
- `_persist_bootstrap_peer()` upserts to `koi_net_nodes` only after signature verification (`koi_net_router.py:402-443`)
- Key-RID binding verified for both b64_64 and legacy16 hash modes

**Validation:**
- [x] `test_extract_bootstrap_key_succeeds_with_valid_payload`
- [x] `test_extract_bootstrap_key_rejects_wrong_key`
- [x] `test_extract_bootstrap_key_returns_none_for_non_bootstrap`
- [x] Interop check [10]: broadcast bootstrap against live instance

### Phase P0.7: Error Response Schema — COMPLETE

**Goal:** Protocol errors include `type: "error_response"` with BlockScience `ErrorType` values.

**Delivered:**
- `_ERROR_TYPE_MAP` covering all four BlockScience ErrorType values plus pre-auth errors (`koi_net_router.py:120-134`)
- `_protocol_error()` helper emitting `{type, error, error_code, message}` (`koi_net_router.py:141-157`)
- Safe fallback: `_DEFAULT_ERROR_TYPE = "invalid_signature"` (won't trigger handshake retries) (`koi_net_router.py:138`)

**Validation:**
- [x] `test_error_type_map_covers_identity_errors`
- [x] `test_pre_auth_errors_do_not_map_to_unknown_node`
- [x] `test_default_error_type_is_not_unknown_node`
- [x] Interop check [9]: error response schema against live instance

### Phase P0.8: POLL Edge Enforcement — COMPLETE

**Goal:** Unapproved peers receive empty event lists when polling.

**Delivered:**
- `KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL` flag, auto-enabled with strict mode (`koi_net_router.py:99-101`)
- Edge lookup in `events_poll` endpoint returns empty `EventsPayloadResponse` for unapproved peers (`koi_net_router.py:656-679`)

**Validation:**
- [x] `test_strict_mode_enables_require_approved_edge_for_poll`
- [x] `test_poll_edge_enforcement_can_be_explicit`

### Phase P1: Manifest Canonicalization — COMPLETE

**Goal:** All manifest hashing uses JCS (JSON Canonicalization Scheme) via `rid-lib`, not `json.dumps(sort_keys=True)`.

**Delivered:**
- Hard dependency on `rid-lib` — `from rid_lib.ext.utils import sha256_hash_json` (`koi_net_router.py:69`)
- `_canonical_sha256_json()` delegates to `rid_sha256_hash_json()` (`koi_net_router.py:168-170`)
- No fallback path — if rid-lib is unavailable, the import fails at module load time
- 3 JCS-specific conformance tests with frozen reference vector from rid-lib 3.2.14

**Validation:**
- [x] `test_manifest_hash_uses_jcs_not_json_dumps` — proves JCS ≠ json.dumps for floats
- [x] `test_manifest_hash_matches_blockscience_reference` — frozen hash vector
- [x] `test_manifest_hash_deterministic_across_key_order`
- [x] `test_manifest_hash_derived_when_missing` — fallback derivation

### Phase P2: Conformance Test Expansion — COMPLETE

**Goal:** Use the `koi-net` PyPI package as a conformance oracle to validate Octo's protocol behavior against the reference implementation.

**Delivered:**
- `requirements-conformance.txt` with `koi-net>=1.2.4` (separate from runtime deps to avoid resolver conflicts with Octo's fastapi pin)
- `tests/conftest.py` with `--live-url` option, `live` marker, and shared fixtures
- `tests/test_koi_conformance.py` with 19 tests across 4 groups:
  - **Group 1: Wire Format Roundtrip** (8 tests) — Octo JSON ↔ koi-net model parsing for all payload types
  - **Group 2: Signed Envelope Cross-Verification** (4 tests) — Sign with Octo → verify with koi-net and vice versa; semantic equivalence; FORGET event null-field handling
  - **Group 3: Node Identity Cross-Verification** (2 tests) — Same keypair → same RID hash from both implementations; KoiNetNode type acceptance
  - **Group 4: Live Endpoint Conformance** (5 tests, `--live-url`) — HTTP requests to live instance, responses validated against koi-net Pydantic models
- Dedicated `venv-conformance/` virtualenv (koi-net 1.2.4 + Octo deps, not modifying runtime requirements)

**Key finding:** Octo's wire format is **byte-identical** to koi-net's for unsigned envelope signing input. `UnsignedEnvelope.model_dump_json(exclude_none=True)` produces identical bytes from both implementations.

**Validation:**
- [x] All 14 offline conformance tests pass
- [x] All 5 core endpoints pass koi-net model roundtrip tests (wire format + live)
- [x] Signed envelope cross-verification passes (both directions)
- [x] Error responses parse as koi-net `ErrorResponse` with valid `ErrorType`
- [x] Existing 21 `test_koi_policy.py` tests still pass (no regressions)

### Phase P3: Handler Chain Pipeline — COMPLETE

**Goal:** Extract monolithic `_process_event()` logic into a structured 5-phase pipeline matching BlockScience's `KnowledgePipeline`.

**Scope:** Poller event processing path only. Broadcast path (`events_broadcast()`) stays as-is (queues raw events to DB). DB-backed event queue preserved.

**Delivered (P3a — strict parity extraction):**
- `api/pipeline/` package: `KnowledgePipeline`, `KnowledgeObject`, `OctoHandlerContext`, `Handler`/`HandlerType`/`StopChain` types
- 5 handlers extracted 1:1 from `koi_poller.py:357-449`:
  - **RID phase:** `set_forget_flag`, `forget_delete_and_stop` (STOP_CHAIN), `extract_entity_type`
  - **Bundle phase:** `cross_reference_resolver` (Tier 1 exact-match, cross-ref upsert/upgrade)
  - **Final phase:** `log_processing_result`
- Manifest and Network phases are empty no-ops (by design — matching plan scope)
- Feature-flagged via `KOI_USE_PIPELINE=true` (env var); pipeline module only imported when flag is on
- FORGET early-exit semantics preserved: `forget_delete_and_stop` returns STOP_CHAIN in RID phase, preventing `cross_reference_resolver` from ever seeing FORGET events
- `event_queue.py`: `_extract_rid_type()` promoted to public `extract_rid_type()`
- `koi_poller.py`: `pipeline`/`use_pipeline` constructor params, dispatch at top of `_process_event()`
- `koi_net_router.py`: Lazy pipeline construction in `setup_koi_net()` — pipeline module imported only when flag is on
- Async pipeline supports mixed sync/async handlers via `inspect.isawaitable()`

**Delivered (P3b — new handlers beyond parity):**
- `block_self_referential` (RID phase, first in chain): Drops events where `kobj.rid == ctx.node_rid` from external sources. Matches BlockScience's `basic_rid_handler` (`default_handlers.py:20-27`). Guards against external peers overwriting our own node identity.
- `entity_type_validator` (Bundle phase, before `cross_reference_resolver`): Logs debug message with RID context for unknown entity types. Permissive — no STOP_CHAIN. Complements existing WARNING in `get_schema_for_type()` with pipeline-specific context.
- `broadcast_target_selector` (Network phase): **Deferred at P3 time** — WEBHOOK push was later implemented directly in `koi_poller.py` (P8) rather than as a pipeline handler. A pipeline-native Network phase handler remains a future cleanup option but is not functionally needed.
- Updated DEFAULT_HANDLERS: 7 handlers total (4 RID, 2 Bundle, 1 Final)

**Validation:**
- [x] 26/26 pipeline tests pass (`test_koi_pipeline.py`)
- [x] 21/21 existing policy tests pass (zero regressions)
- [x] 11/11 interop tests pass with flag off (safe baseline)
- [x] 11/11 interop tests pass with flag on (pipeline active)
- [x] 19/19 conformance tests pass with flag on (live endpoint validation)
- [x] Cross-ref DB state identical before/after enabling pipeline (364 rows, 1 same_as, 363 unresolved)
- [x] Live soak: both Octo and GV running with pipeline enabled, no errors
- [x] Handler registration API matches BlockScience's `Handler` dataclass pattern

### Phase P4: Protocol Surface Cleanup — COMPLETE

**Goal:** Clearly document core vs extension endpoints; report pipeline runtime state.

**Delivered:**
- `pipeline_enabled` field in `GET /koi-net/health` response — computed from runtime state (`_poller.use_pipeline and _poller.pipeline is not None`), not env var text
- Health endpoint already lists core vs extension endpoint sets (`koi_net_router.py:902-913`)
- Master doc and koi-alignment.md updated with final status
- Gap matrix: "Protocol surface docs" marked resolved

**Validation:**
- [x] Health endpoint reports `pipeline_enabled: true` on both Octo and GV
- [x] Core endpoints listed: 5 (broadcast, poll, manifests/fetch, bundles/fetch, rids/fetch)
- [x] Extension endpoints listed: 3 (handshake, events/confirm, health)
- [x] All 5 Definition of Done criteria met

### Phase P5: NodeProfile Ontology Fields — COMPLETE

**Goal:** Add `ontology_uri` and `ontology_version` to NodeProfile, enabling peers to discover each other's ontology commitments.

**Delivered:**
- `ontology_uri` and `ontology_version` optional fields on `NodeProfile` (`koi_protocol.py`)
- Migration `046_node_ontology_fields.sql` adds columns to `koi_net_nodes`
- Health endpoint includes ontology fields when present
- 2 new policy tests validating field presence/absence

**Validation:**
- [x] `test_node_profile_ontology_fields` — verifies fields serialize correctly
- [x] `test_node_profile_ontology_optional` — verifies fields are optional (backward compat)

### Phase P6: UPDATE-Aware Cross-Ref Upsert — COMPLETE

**Goal:** UPDATE events should trigger cross-reference re-resolution instead of being treated identically to NEW.

**Delivered:**
- `cross_reference_resolver` in pipeline handles UPDATE events: re-resolves and updates existing cross-refs if match changes
- Same-resolution case is a no-op (no unnecessary DB writes)
- NEW events still upgrade unresolved cross-refs as before

**Validation:**
- [x] `test_29_update_event_reresolved` — UPDATE triggers re-resolution
- [x] `test_30_update_event_same_resolution` — same match is a no-op
- [x] `test_31_new_event_still_upgrades_unresolved` — NEW upgrade path preserved

### Phase P7: Resolution Primitives + Multi-Tier Federation — COMPLETE

**Goal:** Extract entity resolution logic into reusable primitives supporting exact, alias, and fuzzy matching.

**Delivered:**
- `api/resolution_primitives.py` — standalone module with `normalize_entity_text()`, `jaro_winkler_similarity()`, `compute_token_overlap()`, `resolve_entity_match()`
- Alias-based matching in cross-reference resolver (wikilink-style aliases)
- 12 unit tests covering all resolution tiers

**Validation:**
- [x] 12/12 `test_resolution_primitives.py` tests pass
- [x] `test_32_crossref_resolver_alias_match` — alias matching in pipeline
- [x] `test_33_crossref_resolver_exact_still_works` — no regression
- [x] `test_34_crossref_resolver_no_match_still_unresolved` — graceful fallback

### Phase P8: WEBHOOK Edge Push Delivery — COMPLETE

**Goal:** Implement WEBHOOK edge type — source pushes events to subscriber's `/events/broadcast` endpoint.

**Delivered:**
- `_push_webhook_peers()` in `koi_poller.py` — queries WEBHOOK edges, pushes pending events, marks delivered on success
- Signed envelope support (uses same `sign_envelope()` as poll flow)
- Exponential backoff on failures (shared `MAX_BACKOFF` with poll flow)
- `peek_undelivered()` / `mark_delivered()` on event queue — side-effect-free peek, then mark on success
- Event dedup migration `047_event_dedup.sql`
- **Key-refresh fallback:** When response verification fails (missing or stale peer key), calls `_learn_peer_public_key()` from peer's `/koi-net/health` and retries verification once. Mirrors the poll flow pattern.

**Validation:**
- [x] `test_35_event_queue_peek_does_not_mark` — peek is side-effect free
- [x] `test_36_event_queue_mark_delivered` — mark updates tracking
- [x] `test_37_mark_delivered_idempotent` — idempotent delivery marking
- [x] `test_38_webhook_push_failure_preserves_events` — failed push preserves events
- [x] `test_39_event_insert_dedup` — duplicate insertion idempotent
- [x] `test_40_webhook_key_refresh_on_missing` — missing key triggers refresh
- [x] `test_41_webhook_key_refresh_on_stale` — stale key triggers refresh and retry

### Phase P9: Private Key Encryption — COMPLETE

**Goal:** Encrypt private keys at rest using `PRIV_KEY_PASSWORD` env var, matching BlockScience's `secure.py` pattern.

**Delivered:**
- `get_key_password()` reads `PRIV_KEY_PASSWORD` env var (`node_identity.py`)
- `save_private_key()` accepts optional `password` param, uses `BestAvailableEncryption` when set (`node_identity.py`)
- `load_private_key()` accepts optional `password` param, passes bytes to `load_pem_private_key` (`node_identity.py`)
- `load_or_create_identity()` threads password through from env var (`node_identity.py`)
- `koi_envelope.py` already had password support in `load_private_key_from_file()` — no changes needed
- Migration script `scripts/encrypt_private_key.py` — encrypts existing PEM, creates `.unencrypted.bak`, verifies public key unchanged
- Backward compatible: no `PRIV_KEY_PASSWORD` → `NoEncryption` (existing behavior preserved)

**Deployment:**
1. Deploy code with password support to all nodes (no key changes yet)
2. Encrypt keys one node at a time: set `PRIV_KEY_PASSWORD` in env, run `encrypt_private_key.py`, restart service
3. Rollback: `cp key.pem.unencrypted.bak key.pem`, remove env var, restart

**Validation:**
- [x] `test_save_and_load_encrypted_key` — encrypted round-trip with signing verification
- [x] `test_load_unencrypted_key_still_works` — backward compat
- [x] `test_encrypted_key_derives_same_rid` — encryption preserves node RID
- [x] `test_encrypted_key_wrong_password_fails` — wrong password raises error
- [x] `test_encrypted_key_no_password_fails` — missing password raises error

---

## 7. File Reference Tables

### BlockScience Reference (koi-research/sources/blockscience/)

| File | Role |
|------|------|
| `koi-net/README.md` | Endpoint set, FUN model, edge protocol |
| `koi-net/src/koi_net/protocol/envelope.py` | SignedEnvelope model, source/target as KoiNetNode RID |
| `koi-net/src/koi_net/protocol/secure.py` | Key validation, signature verification, password-protected keys |
| `koi-net/src/koi_net/protocol/edge.py` | EdgeProfile with RIDType lists |
| `koi-net/src/koi_net/protocol/node.py` | NodeProfile (no node_rid/node_name fields) |
| `koi-net/src/koi_net/protocol/event.py` | Event model (no event_id field in spec) |
| `koi-net/src/koi_net/protocol/api_models.py` | Request/response types with `type` discriminators, ErrorType enum |
| `koi-net/src/koi_net/protocol/consts.py` | Path constants (`/events/broadcast`, etc.) |
| `koi-net/src/koi_net/protocol/errors.py` | ErrorType values (snake_case) |
| `koi-net/src/koi_net/config.py` | Node RID generation: `sha256_hash(pub_key.to_der())` |
| `koi-net/src/koi_net/processor/knowledge_pipeline.py` | 5-phase pipeline (RID → Manifest → Bundle → Network → Final) |
| `koi-net/src/koi_net/processor/handler.py` | Handler dataclass, StrEnum for handler types |
| `rid-lib/README.md` | RID semantics, manifest/bundle concepts |
| `rid-lib/src/rid_lib/ext/utils.py` | `sha256_hash_json()` — JCS canonical hash utility |
| `rid-lib/src/rid_lib/core.py` | RIDType metaclass, Pydantic integration |

### Octo Implementation

| File | Role | Lines |
|------|------|-------|
| `koi-processor/api/koi_net_router.py` | Protocol endpoints, envelope unwrapping, security policy | 903 |
| `koi-processor/api/koi_envelope.py` | ECDSA P-256 sign/verify, envelope models | 213 |
| `koi-processor/api/koi_protocol.py` | Wire format models (Pydantic), request/response types | 181 |
| `koi-processor/api/node_identity.py` | Keypair management, RID derivation, key-RID matching, password encryption | 195 |
| `koi-processor/scripts/encrypt_private_key.py` | Migration script: encrypt existing PEM with backup + verification | — |
| `koi-processor/api/koi_poller.py` | Background polling, cross-reference resolution, WEBHOOK push, key-refresh fallback | 658 |
| `koi-processor/api/event_queue.py` | DB-backed event queue, per-node delivery tracking | 202 |
| `koi-processor/api/pipeline/__init__.py` | Pipeline package exports, lazy handler import | — |
| `koi-processor/api/pipeline/knowledge_object.py` | KnowledgeObject dataclass (data carrier through pipeline) | — |
| `koi-processor/api/pipeline/handler.py` | Handler, HandlerType (5 phases), StopChain sentinel | — |
| `koi-processor/api/pipeline/context.py` | OctoHandlerContext (pool, node_rid, node_profile, event_queue) | — |
| `koi-processor/api/pipeline/pipeline.py` | KnowledgePipeline — async 5-phase handler chain | — |
| `koi-processor/api/pipeline/handlers/__init__.py` | DEFAULT_HANDLERS list (7 handlers in registration order) | — |
| `koi-processor/api/pipeline/handlers/rid_handlers.py` | block_self_referential, set_forget_flag, forget_delete_and_stop, extract_entity_type | — |
| `koi-processor/api/pipeline/handlers/bundle_handlers.py` | entity_type_validator, cross_reference_resolver (Tier 1 exact-match + cross-ref upsert) | — |
| `koi-processor/api/pipeline/handlers/final_handlers.py` | log_processing_result | — |
| `koi-processor/api/personal_ingest_api.py` | Main API — mounts koi-net router at `/koi-net` prefix | — |
| `koi-processor/migrations/039_koi_net_events.sql` | Events, edges, nodes tables | 52 |
| `koi-processor/migrations/041_cross_references.sql` | Cross-reference table | 18 |
| `koi-processor/migrations/046_node_ontology_fields.sql` | NodeProfile ontology columns on koi_net_nodes | — |
| `koi-processor/migrations/047_event_dedup.sql` | Event deduplication index | — |
| `koi-processor/tests/conftest.py` | Shared pytest config: `--live-url` option, `live` marker | 22 |
| `koi-processor/api/resolution_primitives.py` | Entity resolution primitives (exact, alias, fuzzy) | — |
| `koi-processor/tests/test_koi_policy.py` | 23 pytest tests (unit/integration) | — |
| `koi-processor/tests/test_koi_pipeline.py` | 39 pipeline + webhook tests (P3–P8) | — |
| `koi-processor/tests/test_resolution_primitives.py` | 12 resolution primitive tests | — |
| `koi-processor/tests/test_koi_conformance.py` | 19 conformance tests (14 offline + 5 live) using koi-net as oracle | 340 |
| `koi-processor/tests/test_koi_interop.py` | 11 interop checks (script-based, run against live instance) | 451 |

---

## 8. Appendices

### A. Timeline

| Date | Event |
|------|-------|
| 2026-02-08 | Sprint 1-3: Initial KOI-net federation (Octo ↔ GV), event queue, cross-refs |
| 2026-02-09 | Cleanup sprint: event confirmation e2e, 70 entities seeded, interop tests 8/8 |
| 2026-02-12 | P0 hardening: strict mode, signed envelopes, target/source binding |
| 2026-02-12 | PyPI review: rid-lib 3.2.14, koi-net 1.2.4 assessed |
| 2026-02-17 | P0.5: Node RID migration to b64_64 (BlockScience canonical) |
| 2026-02-17 | P0.6: Bootstrap self-introduction (FORGET+NEW) |
| 2026-02-17 | P0.7: Error response schema (BlockScience ErrorType) |
| 2026-02-17 | P0.8: POLL edge enforcement |
| 2026-02-17 | P1: rid-lib hard dependency, JCS canonical hashing, 3 conformance tests |
| 2026-02-17 | Regen federation live: bidirectional event polling verified |
| 2026-02-18 | Master document created |
| 2026-02-18 | P2: Conformance test suite (14 offline + 5 live) using koi-net 1.2.4 as oracle |
| 2026-02-18 | P3a: Handler chain pipeline — 5-phase pipeline extracted from `_process_event()`, feature-flagged, deployed to production |
| 2026-02-18 | P3b: New handlers — `block_self_referential` (RID phase), `entity_type_validator` (Bundle phase), 7 new tests |
| 2026-02-18 | P4: Protocol surface cleanup — `pipeline_enabled` in health endpoint, docs finalized, all Definition of Done criteria met |
| 2026-02-18 | P5: NodeProfile ontology fields (`ontology_uri`, `ontology_version`), migration 046 |
| 2026-02-18 | P6: UPDATE-aware cross-ref upsert with re-resolution |
| 2026-02-18 | P7: Resolution primitives module (exact, alias, fuzzy matching) |
| 2026-02-18 | P8: WEBHOOK edge push delivery with key-refresh fallback, event dedup migration 047 |
| 2026-02-18 | GV migrated from Octo-local (127.0.0.1:8352) to remote on poly (37.27.48.12:8351). 3-node topology verified. iptables firewall added on poly. |
| 2026-02-18 | KOI Tool Contract v1.1.1 verified (76/76 contract tests, 8/8 manual checks, personal-koi-mcp pushed) |
| 2026-02-18 | personal-koi-mcp extended to support all 14 BKC entity types in extraction/schema |
| 2026-02-18 | Stabilization commit `05ee778` tagged `koi-gv-remote-stable` (Octo plugin fixes + GV remote migration) |
| 2026-02-19 | Old GV decommissioned from Octo server: service, DB, cron removed. Final backups retained. |
| 2026-02-19 | Automated GV backups on poly: `gv-backup.timer` (daily 3am) + `gv-backup-offhost.timer` (weekly Sun 4am → Octo). Restore tested. |
| 2026-02-19 | P9: Private key encryption — `PRIV_KEY_PASSWORD` env var, `BestAvailableEncryption`, migration script, 5 tests |
| 2026-02-20 | `/koi-net/edges` read-only endpoint added to `koi_net_router.py`, deployed to Octo. Returns approved federation edges for dashboard visualization. |
| 2026-02-20 | Web dashboard forked (`BioregionalKnowledgeCommons/bioregional-commons-web`). Next.js BFF proxies all 4 KOI nodes server-side. Live node markers (health-colored), federation arcs, entity browser, rate-limited search. Designed to run on Octo server (Option A). |
| 2026-02-19 | Documented dual-implementation tool architecture (OpenClaw plugin + MCP server) and planned commoning-koi-mcp repo split |
| 2026-02-19 | P9 key encryption deployed to production — GV (poly) and Octo keys encrypted at rest |
| 2026-02-19 | Front Range agent deployed on Octo server (port 8355, localhost-only). `fr_koi` DB, bidirectional federation with Octo, 4 seed entities |
| 2026-02-19 | `test-federation.sh` parameterized for multi-source testing (SOURCE_URL, SOURCE_SSH, SOURCE_DB, dynamic node RID filtering) |
| 2026-02-19 | Commit `9ea1e11`: P9 key encryption deployed to all 3 nodes (Octo, GV, FR). Front Range agent fully deployed (DB, edges, seeded, key encrypted, federation verified). `test-federation.sh` parameterized for multi-source. All docs updated. |
| 2026-02-19 | `gv.env` completed with KOI-net federation vars (previously worked because server env had them, but repo file was incomplete) |
| 2026-02-19 | Phase 5.7: GitHub sensor activated on Octo server — 4 repos (Octo, openclaw, koi-net, personal-koi-mcp), 35k+ code artifacts, tree-sitter Python/TS extraction, vault notes in Sources/GitHub/ |

### B. Tool Integration Architecture

The KOI backend exposes a REST API that agent frameworks consume via tool adapters. To ensure behavioral parity across frameworks, tool interfaces are specified in a framework-agnostic **koi-tool-contract** (`koi-processor/docs/koi-tool-contract.md`) — 15 tools covering entity resolution, web content curation, vault operations, relationship sync, and federation queries.

Two implementations of this contract exist:

```
┌──────────────────────────────────┐     ┌──────────────────────────────────┐
│  bioregional-koi plugin          │     │  personal-koi-mcp                │
│  (OpenClaw / TypeScript)         │     │  (MCP server / TypeScript)       │
│                                  │     │                                  │
│  15 contract tools               │     │  15 contract tools               │
│  Deployed on Octo server         │     │  + 27 personal-only tools        │
│  plugins/bioregional-koi/        │     │  ~/projects/personal-koi-mcp/    │
│  index.ts                        │     │  (email, sessions, vault ETL)    │
└──────────┬───────────────────────┘     └──────────┬───────────────────────┘
           │                                        │
           │  HTTP calls                            │  HTTP calls
           ▼                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     KOI Processor API (uvicorn)                         │
│                     Same endpoints, same behavior                       │
└──────────────────────────────────────────────────────────────────────────┘
```

- **`bioregional-koi` plugin** (`plugins/bioregional-koi/index.ts`): Production integration for OpenClaw agents. 15 tools only. Deployed on the Octo server.
- **`personal-koi-mcp`** (`~/projects/personal-koi-mcp/`): MCP server for Claude Code, Cursor, and other MCP-compatible hosts. Implements the same 15 contract tools plus 27 personal-only tools (email search, session search, vault entity extraction, meeting prep, etc.). Forked from `gaiaaiagent/regen-koi-mcp`. Currently a hybrid personal+BKC system — see "Future: commoning-koi-mcp" below.

Both implementations call the same KOI API endpoints. The contract + 76 contract tests ensure behavioral parity regardless of which framework consumes the tools.

### C. Future: commoning-koi-mcp

When a second node operator needs MCP access to their node (e.g., Front Range), the personal-koi-mcp should be split:

```
personal-koi-mcp (stays as-is, Darren's personal use)
├── 15 KOI contract tools (via shared contract spec)
├── 27 personal tools (email, sessions, meeting prep, entity extraction, etc.)
└── Personal config (vault path, backend URL)

commoning-koi-mcp (NEW — clean BKC node MCP server)
├── 15 KOI contract tools only
├── BKC entity types (15 types from ontology, loaded from backend /entity-types)
├── Configurable: KOI_API_ENDPOINT, VAULT_PATH, node identity
└── Deployable on any BKC node (Octo, GV, CV, Front Range)
```

**Key design decisions:**
1. **Shared contract, not shared code** — both MCP servers implement `koi-tool-contract.md` independently (same pattern as OpenClaw plugin). No shared npm package needed initially.
2. **commoning-koi-mcp scope** — only the 15 contract tools. No email, no sessions, no Claude-specific tools.
3. **Entity types** — loaded dynamically from backend `/entity-types` endpoint (already works this way).
4. **Configuration** — same 2 env vars: `KOI_API_ENDPOINT` + `VAULT_PATH`. Node identity handled by KOI API, not MCP server.
5. **When to split** — when a second node operator needs MCP access. Not urgent while only Darren uses MCP.

### E. Architecture Comparison

```
BlockScience koi-net                    Octo
┌─────────────────────────┐    ┌─────────────────────────────┐
│ In-memory cache/store   │    │ PostgreSQL (koi_net_events)  │
│ Effector pipeline       │    │ DB-backed event queue        │
│ Handler chain (5-phase) │    │ Handler chain (5-phase, P3)  │
│ Cache-backed state      │    │ entity_registry + cross-refs │
│ rid-lib first-class     │    │ rid-lib hard dep (hashing)   │
│ Key storage: encrypted  │    │ Key storage: encrypted PEM   │
└─────────────────────────┘    └─────────────────────────────┘
```

Key architectural difference: Octo uses a **durable database-backed event queue** with per-node delivery tracking (`delivered_to`, `confirmed_by` arrays), while BlockScience uses an in-memory cache with effector pipeline. Octo's approach provides crash-resilient delivery at the cost of additional DB round-trips.

### F. Deployment Commands Reference

```bash
# Run pytest tests (policy + pipeline + resolution)
cd ~/koi-processor && venv/bin/python -m pytest tests/test_koi_policy.py tests/test_koi_pipeline.py tests/test_resolution_primitives.py -v

# Run conformance tests (offline, uses koi-net package as oracle)
cd ~/koi-processor && venv-conformance/bin/python -m pytest tests/test_koi_conformance.py -v

# Run conformance tests (with live endpoint validation)
cd ~/koi-processor && venv-conformance/bin/python -m pytest tests/test_koi_conformance.py -v --live-url http://127.0.0.1:8351

# Run interop tests against live instance
cd ~/koi-processor && venv/bin/python tests/test_koi_interop.py --url http://127.0.0.1:8351

# Check federation health
curl -s http://127.0.0.1:8351/koi-net/health | python3 -m json.tool

# Run full federation test
bash ~/scripts/test-federation.sh

# Deploy updated code (Octo + FR + GV)
rsync -avz --delete koi-processor/api/ root@45.132.245.30:/root/koi-processor/api/
rsync -avz --delete koi-processor/api/ root@37.27.48.12:/home/koi/koi-processor/api/
ssh root@37.27.48.12 "chown -R koi:koi /home/koi/koi-processor"
ssh root@45.132.245.30 "systemctl restart koi-api"
ssh root@45.132.245.30 "systemctl restart fr-koi-api"
ssh root@37.27.48.12 "systemctl restart gv-koi-api"

# Stamp version on both servers after deploy
git -C koi-processor rev-parse --short HEAD | ssh root@45.132.245.30 "cat > /root/koi-processor/.version"
git -C koi-processor rev-parse --short HEAD | ssh root@37.27.48.12 "cat > /home/koi/koi-processor/.version"

# Check FR federation health
ssh root@45.132.245.30 "curl -s http://127.0.0.1:8355/koi-net/health | python3 -m json.tool"

# Run federation test against FR
ssh root@45.132.245.30 "SOURCE_URL=http://127.0.0.1:8355 SOURCE_DB=fr_koi bash ~/scripts/test-federation.sh"

# --- Cowichan Valley (CV) ---
# SSH to CV node
ssh root@202.61.242.194

# CV KOI health check
ssh root@202.61.242.194 "curl -s http://127.0.0.1:8351/koi-net/health | python3 -m json.tool"

# Deploy code to CV
rsync -avz --delete koi-processor/api/ root@202.61.242.194:/home/koi/koi-processor/api/
ssh root@202.61.242.194 "systemctl restart cv-koi-api"
```

### G. PyPI Package Adoption Status

| Package | Version | Usage | Status |
|---------|---------|-------|--------|
| `rid-lib` | `>=3.2.12` (floor) | Hard runtime dependency — JCS hashing | **Active** |
| `koi-net` | `>=1.2.4` (conformance) | Conformance oracle in `venv-conformance/` — not in runtime deps | **Active (test only)** |

### H. Definition of Done for "Aligned Enough"

The system is considered aligned for production federation when all are true:

1. Strict signed-envelope mode is available and enabled for internet-facing peers
2. Node identity derivation and key binding are compatible with reference semantics (with compatibility bridge during migration)
3. Manifest/hash canonicalization is backed by rid-lib JCS
4. Conformance tests pass against both Octo peers and BlockScience reference behavior for core 5 endpoints
5. Extension endpoints are clearly documented as non-core protocol conveniences

**Current status:** All 5 criteria met. P0–P9 complete. 98 pytest tests + 11 interop checks passing.

---

## 9. Next Steps (as of 2026-02-19, commit 9ea1e11)

### Completed Through This Commit

- [x] **P0–P9 all complete** — 98 pytest tests + 11 interop checks passing
- [x] **P9 key encryption deployed to all 3 nodes** (Octo, GV, FR) — `.unencrypted.bak` files exist for rollback
- [x] **Front Range agent fully deployed** — `fr_koi` DB, `fr-koi-api.service` on port 8355, workspace (IDENTITY.md, SOUL.md), 4 seed entities, bidirectional federation with Octo verified, key encrypted at rest
- [x] **`test-federation.sh` parameterized** for multi-source testing (SOURCE_URL, SOURCE_SSH, SOURCE_DB, dynamic node RID filtering)
- [x] **All docs updated** — CLAUDE.md, README.md, agents.conf reflect FR deployment and P9 completion
- [x] **Old GV decommissioned** from Octo server — service, DB, cron removed; final backups retained
- [x] **Automated GV backups** on poly — daily + weekly off-host to Octo
- [x] **Cowichan Valley SSH access** obtained — `ssh root@202.61.242.194` (Shawn's node)
- [x] **gv.env completed** with KOI-net federation vars (KOI_NET_ENABLED, KOI_STATE_DIR, KOI_BASE_URL, security flags)
- [x] **Phase 5.7: GitHub sensor activated** — 4 repos (Octo, openclaw, koi-net, personal-koi-mcp), 35k+ code artifacts, tree-sitter extraction, vault notes in Sources/GitHub/
- [x] **Bioregion onboarding kit** — `docs/new-bioregion-quickstart.md`, `vault-seed/TEMPLATES/` (Practice + Bioregion templates), fixed `involves_organization` → `parentOrg` in `join-the-network.md`

### Active Next Steps (priority order)

1. **Phase 0.5: BKC CoIP vault audit** — Blocked on access from Andrea Farias / Vincent Arena
2. **Phase 5: Cascadia coordinator** — After CV is fully operational, proves holon pattern
3. **commoning-koi-mcp split** — When a second node operator needs MCP access (see §8C)
4. **PicoClaw pilot evaluation (exploratory)** — Assess feasibility for ultra-light edge/sensor leaf nodes; no committed integration path yet
