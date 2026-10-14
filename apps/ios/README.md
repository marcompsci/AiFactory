# AI Civ for iPhone (native)

A SwiftUI client for the AI Civilization server.

| Tab | What it does |
|---|---|
| **City** | The live 3D city (the web app) full-screen |
| **Company** | Send researchers out, follow opportunities through the workflow, see the chain of command and each agent's model |
| **Owner** | The Owner's Tower, native: manager recommendation, sandboxed prototype preview (network blocked), exact bundle digest, tests on that digest, 12-category checklist, cited research with fixture labels, costs and risks. **Approve requires Face ID or your passcode** and sends the digest you are looking at |
| **Activity** | Live event feed over Server-Sent Events, ordered and deduplicated, with gap replay |
| **Settings** | Server and city addresses; the access token is stored in the iOS Keychain (this device only) |

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
  `AICIV_API_TOKEN` and `--host 0.0.0.0`, then enter `http://<your-mac-ip>:8000`, the city address and the token in Settings.

## Tests

`xcodebuild -project AICiv.xcodeproj -scheme AICiv -destination 'platform=iOS Simulator,name=iPhone 16' test`

The test fixtures in `AICivTests/Fixtures` are real responses captured from the server (snapshot, events, an Owner's Tower
dossier), so decoding is tested against what the API actually sends. CI builds and tests on macOS (`.github/workflows/ios.yml`)
and also does an unsigned device build.
