# The money game

The agents compete to make you the most money. The Arena shows a leaderboard per monthly season, levels from
completed work, and a live feed of plays.

**Only verified money scores** (`services/game/scoring.py`):

| Play | Evidence | Amount |
|---|---|---|
| Realized savings | An owner-approved, *executed* purchase that costs less per year than what was requested | annualized(requested) − annualized(executed) |
| Avoided cost | You rejected a purchase after a free-alternative investigation recommended the alternative (your rejection in the audit chain) | the request's annualized cost |
| Attributed revenue | Revenue from a payer you linked to a product the agents built (`POST /api/game/revenue-links`), posted after the link was made | the transaction amount |

Each amount is split equally among the agents that completed tasks on it.

- Simulated data scores in a separate, labeled column and never counts as verified.
- No endpoint or agent can write a score. Scores come only from the scheduled scorer, reading authoritative records.
- Scores are append-only (database trigger) and idempotent (one row per source and agent).
- Money is shown to owners and admins only. Other members see ranks, levels and activity.
- `game.*` events carry no amounts.
