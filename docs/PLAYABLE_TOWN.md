# V6.0 Playable town (first milestone)

> **V6.1: native on iPhone.** The iPhone's City tab is now the town as a native SpriteKit game
> (`apps/ios/AICiv/Game/`): a Swift port of the same map, rules, pixel art and characters, with native controls
> (joystick, Talk/Use, RPG dialogue, journal, character editor) and approvals in the Owner's Tower screen.
> It always shows: with the bundled cast (`packages/shared-types/seed/agents.json`) before you connect, labeled
> OFFLINE, and your live team once signed in. CI takes simulator screenshots and publishes them to the
> `ios-screenshots` branch. The web version below is still at `/play` for desktop.

A top-down pixel-art town you walk around as your own character. Your agents live and work in it, and talking to them
does real work through the same backend as the rest of the app. It runs in the browser at `/play` and is the iPhone
app's City tab. The 3D city is still at `/`, one tap away from the town's top bar.

## What's in this slice

| Milestone item | Where |
|---|---|
| Small outdoor town | `apps/web/lib/play/maps.ts` `buildTown()`: 8 buildings, roads, plaza, ponds, trees, conveyor loop, logistics depot |
| Controllable character | `components/play/runner.ts`: four directions, walk cycle, WASD/arrows, on-screen joystick, tap/click to walk (A* pathfinding), collision, camera follow |
| Three enterable buildings | Research Observatory, Nexus Spire, Code Forge (`buildInterior`), each with desks, props and objects you can use |
| General Manager, Researcher, Developer NPCs | Atlas and Vega (Nexus Spire), Lumen, Pip and Wren (Observatory), Kade and Orin (Code Forge) |
| RPG dialogue | `components/play/Dialogue.tsx` + `services/play/npc.py`, history kept per agent (`play_messages`) |
| One real authorized AI task | "Research …" (researchers, GM) runs the market-research mission; "Fix / build / change …" (developers, GM) runs the software-change mission; both through the regular endpoints |
| Persistent mission state | Missions live in the backend as before; the journal reads them. Your look and position persist (`play_players`) |
| Visible agent status | NPC animation and the bubble over their head follow the agent's execution state from backend events |
| Package handoff | Packages on the belt are `logistics_packages` records, positioned by their server route clock (`packagePoint`) |
| Owner approval screen | Bell or the Owner's Tower door: mission approvals, release decisions and financial requests (reuses the tested approval flows) |

The other buildings (Creative Studio, Sentinel Citadel, AI Central Bank, Memory Vault) are visible but closed; the
Owner's Tower door opens the approval screen.

## Rules the game keeps

- **Talking never changes anything.** An actionable request becomes a *proposal* (create mission, start research,
  cancel mission). It runs only when you tap Confirm, through the same functions and permission checks as
  `POST /api/missions`, `POST /api/research` and `POST /api/missions/{id}/cancel`. Proposals expire after 15 minutes.
  Walking away, closing the game or reconnecting never confirms one, and a confirmed proposal can't run twice
  (compare-and-set plus the mission idempotency key `play:<proposal id>`).
- **NPCs only say what the backend knows.** Replies are built from agent state, tasks, missions, approvals,
  opportunities, artifacts and estimated costs. Understanding is keyword-based on purpose: predictable and testable.
  Anything it can't map gets "here's what I can do", not a guess.
- **Animation isn't evidence.** NPC animations map from `execState` (`animFor`): EXECUTING becomes CODING,
  RESEARCHING, TESTING or WORKING by role; WAITING_* becomes WAITING; COMPLETED becomes CELEBRATING; MOVING with a
  package becomes DELIVERING. Idle agents stand still; there's no fake busy-work. A package arriving is a handoff
  record, not proof the work is done; the package card says so.
- **Simulation and demo are labeled.** The top bar shows LIVE, SIMULATION (no AI model connected, so runs are
  rehearsals), DEMO (no server: a scripted demo, not your team) or SIGN IN.
- **Approvals happen only on the approval screen**, by pressing Approve. Money still needs authenticator step-up.

## API (`services/api/play.py`)

| Route | Role | What |
|---|---|---|
| `GET /api/play/state` | member | your avatar, position and pending proposals |
| `PUT /api/play/state` | operator | save avatar and position (validated: maps, colors, ranges) |
| `GET /api/play/conversations/{agent_id}` | member | your conversation with one agent, with proposal states |
| `POST /api/play/talk` | operator | say something; returns the reply and maybe a proposal |
| `POST /api/play/proposals/{id}/confirm` | operator | run it |
| `POST /api/play/proposals/{id}/decline` | operator | drop it |

Tables `play_players`, `play_messages`, `play_proposals` (migration 0009). Each user sees only their own rows (RLS).

## Reconnecting

`/play` uses the same realtime hook as the 3D city: snapshot, then live events, then replay of any gap, keyed by
sequence number so nothing is applied twice. Missions keep running on the server's worker while the game is closed.
On return you get the current world, the journal and any pending approvals; only events after the game opened show
as notifications.

## Art

Everything is drawn from code (`lib/play/art.ts`, `lib/play/sprites.ts`): 16 px tiles, and 16×24 characters with
big heads in four directions with walk, work, read, talk, carry and celebrate frames. Agents use their seeded looks;
your character uses the look you pick (hair, colors, glasses). `/play/cast` shows every character in every pose.
The reference screenshots set the mood. The art is original, not copied from them.

## Still open

- Interiors for the other buildings, the Logistics Center, agents walking between buildings along real routes, and
  a free-text model for dialogue (with the same proposal gate).
- Claude Code / Codex: the game uses the existing plan adapters (D20: `claude -p` and `codex exec`, text-only). Session
  discovery, resume, job logs, cancellation and repo/branch isolation for those tools are not built. Before building
  them, check each tool's current auth, SDK and subscription terms. Never assume a consumer plan allows unlimited automation.
- Pixel-perfect testing on a physical iPhone.
