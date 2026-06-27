# Helix Blockchain — Helm chart

Deploys an HA validator set as a StatefulSet with stable per-pod identities,
liveness/readiness probes, anti-affinity, a PodDisruptionBudget, hardened
containers (non-root, read-only FS, dropped caps) and persistent storage.

## Quick start

```bash
# 1. Generate N keypairs (one per replica).
python -m helix_blockchain.tools.keygen helix-0 helix-0.<release>-helix:8000
# ...repeat per ordinal, collecting private keys and the peer specs.

# 2. Provide the secret out-of-band (SealedSecrets / External Secrets / Vault CSI),
#    with keys "keys/0".."keys/N-1" and "cluster_token".

# 3. Install, passing the peers list (same on every pod; the node dedups itself).
helm install helix ./deploy/helm/helix \
  --set replicas=4 \
  --set-json 'peers=["helix-0@helix-0.helix-helix:8000|<pub0>","helix-1@..."]'
```

## Notes
- **Keys per pod:** the entrypoint selects `/secrets/keys/$ORDINAL` from the pod
  hostname, so each validator has its own key without per-pod templating.
- **HA:** `podAntiAffinity` (soft/hard) spreads validators across nodes; the PDB
  caps voluntary disruptions. Use ≥4 replicas for Byzantine tolerance (f=1).
- **Observability:** set `serviceMonitor.enabled=true` with the Prometheus
  Operator to scrape `/metrics`.
- **Secrets:** `secret.create=true` is for quick tests only; never commit keys.
