# KOI-net Federation Handoff (Darren <-> Shawn + Commons Intake)

## Scope Completed On This Branch
- Branch: `feature/koi-net-slice3-commons-intake`
- Backend: `koi-processor`
- Implemented:
  - Recipient-scoped event delivery (`target_node`) support in queue logic.
  - Handshake hardening:
    - key pinning (reject silent key rotation),
    - inbound/outbound edge creation,
    - peer alias auto-create (best-effort).
  - Local admin endpoint for outbound edge approval: `POST /koi-net/edges/approve`.
  - Sharing/intake APIs:
    - `POST /koi-net/share`
    - `GET /koi-net/shared-with-me`
    - `GET /koi-net/commons/intake`
    - `POST /koi-net/commons/intake/decide`
  - Poller share persistence updates already present in this branch are compatible with above.

## Status Update (2026-02-25)
- Tunnel-free federation over WireGuard validated across Darren, Octo, Front Range, and Cowichan.
- Commons intake flow validated live (`staged -> approved/rejected`) on Octo and Cowichan.
- Poller hardening applied:
  - replaced failure-threshold skip behavior with time-based retry windows,
  - automatic peer recovery after outage without requiring service restart,
  - deployed to Octo/FR/Cowichan runtime nodes.

## New Migrations Added
- `048_event_target_node.sql`
- `049_peer_aliases.sql`
- `050_shared_documents.sql`
- `051_shared_documents_intake.sql`
- `052_outbound_share_ledger.sql`

## Repos Relevant To Continue
- `BioregionKnwoledgeCommons/Octo`: bioregional commons node backend + federation protocol runtime.
- `personal-koi-mcp`: Claude tool UX (`share_document`, dependency/context pack behavior).
- `RegenAI/koi-processor`: reference implementation used for parity checks.

## Next Session Bring-Up Checklist
1. Ensure migrations 048-052 are applied in the target DB.
2. Ensure env flags:
   - `KOI_NET_ENABLED=true`
   - `KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL=true`
   - `KOI_ENFORCE_SOURCE_KEY_RID_BINDING=true`
   - `KOI_COMMONS_INTAKE_ENABLED=true` (for commons mode)
3. Restart API/poller after deployment.
4. Smoke:
   - `GET /koi-net/health`
   - handshake between peers
   - `POST /koi-net/edges/approve` (localhost + admin token)
   - `POST /koi-net/share` (`recipient_type=peer` then `commons`)
   - `GET /koi-net/shared-with-me`
   - `GET /koi-net/commons/intake` and decision endpoint

## Notes
- `share` writes to `koi_outbound_shares` as best-effort; if migration 052 is not applied, share still queues.
- Alias resolution falls back to node name/full node RID if alias table is unavailable.
- Commons intake routes return explicit schema errors until migration 051 is applied.
