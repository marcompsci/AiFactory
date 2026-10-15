# AI Civ for iPhone (native)

A SwiftUI client for the AI Civilization server.

Same pixel-art look as the web dashboard: dark panels with neon rims, monospaced caps, district colours.

| Tab | What it does |
|---|---|
| **Home** | The dashboard frame, native: stats bar (cash, agents working, tasks, projects, 30-day revenue, decisions waiting), a live pixel-art map of the city (tap a district to see who's there), live agent activity, conveyor flow, active projects, financial overview. Figures come from `/api/overview`; money only for the owner and admins, and labeled when simulated |
| **City** | The live 3D city (the web app) full-screen |
| **Arena** | The money game: leaderboard on verified money (realized savings, avoided cost, attributed revenue), simulated scores shown apart |
| **Owner** | The Owner's Tower: finance decisions, release reviews and **App Lab proposals**. Approving needs **Face ID or your passcode**, then the server's step-up (authenticator code) for App Lab and payments |
| **More** | App Lab (repositories, cycles, proposals with the diff and the General Manager's review), Factories (Claude Code sessions, finished tasks and shared memory; GitHub pull requests and workflow runs), Company, Activity, Settings |

**Sign in with Google or GitHub** (Settings → Account): opens the provider in a secure browser sheet
(`ASWebAuthenticationSession`, PKCE). The app never sees your password; the Supabase session lives in the iOS Keychain and is
refreshed before it expires. The app reads the Supabase address and publishable key from the server's `/api/public-config`, so
there's nothing to type. In Supabase, add `aiciv://auth-callback` under Authentication → URL Configuration → Redirect URLs.

Notifications: a local notification fires when a release reaches the Owner's Tower, both while the app is open (live stream)
and in the background (BGAppRefresh checks about every 15 minutes, when iOS allows). Instant remote push needs an APNs key on
the server, which is not set up yet.

## Run it

Requires a Mac with Xcode 16+.

```bash
brew install xcodegen
cd apps/ios
xcodegen generate
open AICiv.xcodeproj
```

- Simulator: pick an iPhone and Run. Point Settings at `http://localhost:8000` (API) and `http://localhost:3000` (city).
- Your iPhone: set your team in *Signing & Capabilities* (or `DEVELOPMENT_TEAM` in `project.yml`), start the server with
  `AICIV_HOST=0.0.0.0 bash scripts/run-local.sh`, enter `http://<your-mac-ip>:8000` and the city address in Settings, then sign in.

## Tests

`xcodebuild -project AICiv.xcodeproj -scheme AICiv -destination 'platform=iOS Simulator,name=iPhone 16' test`

The test fixtures in `AICivTests/Fixtures` are real responses captured from the server (snapshot, events, an Owner's Tower
dossier), so decoding is tested against what the API actually sends. CI builds and tests on macOS (`.github/workflows/ios.yml`)
and also does an unsigned device build.
