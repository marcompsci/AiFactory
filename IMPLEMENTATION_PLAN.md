# Implementation plan

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | monorepo, contracts, migrations, API, auth, Docker, CI | done (Postgres path unverified) |
| 2 3D world | city, six districts, cameras, avatars, navigation, interiors (focus + see-through) | done for the slice; GLB assets not used yet |
| 3 Live operations | event store, outbox, SSE, reconciliation, world sync, inspector, feed | done |
| 4 AI orchestration | model adapters, durable missions, delegation, checkpoints, memory | done with the D3 substitution; LangGraph + model-planned graphs pending |
| 5 Real execution | sandboxed repo tools, worktrees, tests, artifacts, approvals | done for the local sample repo; GitHub App adapter implemented, untested |
| 6 Hardening | security tests, budgets, recovery, responsive, deployment | partially done; see PROGRESS.md |

## Next milestones, in order

1. **Native iOS shell** (Capacitor wrapping the PWA, then native widgets/notifications for approvals).
2. **Deploy**: Supabase project, apply migration, run API on a small VM with `AICIV_SANDBOX=docker`, web on Vercel.
3. **Push notifications for approvals** (Web Push now, APNs with the native shell).
4. **Connect a real GitHub repository** through the GitHub App and open draft PRs.
5. **LangGraph planner** for model-planned missions beyond "fix the failing test".
6. **Redis** for the mission queue and rate limits; multiple API instances.
7. GLB agent models and richer interiors.
