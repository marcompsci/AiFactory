# V4.0 acceptance run

Recorded 2026-10-14 15:51:56 PDT by tests/integration/test_v4_acceptance.py.
Research data: **labeled fixtures** (no marketplace credentials or network in the test environment).

1. Research: **Steady Focus — productivity app** scored 0.76 (medium), data_mode `fixture`.
2. Packages: research_brief (data-observatory→nexus-spire) → product_proposal (nexus-spire→code-forge) → code_artifact (code-forge→sentinel-citadel) → test_report (sentinel-citadel→nexus-spire) → release_package (nexus-spire→owners-tower)
3. Manager decisions: [('opportunity_review', 'route'), ('routing', 'route:app_studio'), ('acceptance', 'accepted'), ('drift_check', 'on_track'), ('release_review', 'APPROVED_FOR_OWNER_REVIEW')]
4. QA: 8 passed in 0.02s on bundle `e85a715bda6ee707`; manager checklist accessibility=pass, cost=pass, documentation=pass, functional=pass, known_limitations=warn, market_rationale=warn, performance=pass, privacy=pass, requirements=pass, security=pass, store_requirements=warn, tests=pass
5. Release attempted without owner approval: **refused** at the tool boundary (`submit_release` DENIED), nothing written.
6. Owner approved digest `e85a715bda6ee707` → authorization `9f2a5d1a` (a wrong digest was rejected first).
7. Released to `releases/93b400fd-8e6f-4078-b4b9-356e92ce8724/e85a715bda6ee707.zip` (local release channel).
8. Bundle file tampered after release: approval `9f2a5d1a` **invalidated**; App Studio rebuilt a new artifact `539e7967` from the template (identical bytes rebuild to the same digest `e85a715bda6ee707`, but approvals are tied to the artifact, so QA retested it, the manager re-reviewed it, and the owner must decide again).
9. Replaying the old approval: **refused**.

## Event log

| # | event | agent | mode | detail |
|---|---|---|---|---|
| 1 | mission.created |  | simulation | Research 'productivity' on apple charts |
| 2 | manager.decision_recorded | Atlas | live | assigned:research_apps |
| 3 | manager.goal_assigned | Atlas | live | assigned:research_apps |
| 4 | mission.status_changed |  | simulation | VALIDATING |
| 5 | agent.message | Vega | simulation | Permissions validated for market research: 2 tools within project policy. |
| 6 | mission.status_changed |  | simulation | PLANNING |
| 7 | task.assigned | Pip | simulation | Research the market |
| 8 | agent.message | Vega | simulation | Plan: research the market. |
| 9 | mission.status_changed |  | simulation | QUEUED |
| 10 | mission.started |  | simulation | RUNNING |
| 11 | task.started | Pip | simulation | Research the market |
| 12 | agent.status_changed | Pip | simulation | ASSIGNED |
| 13 | agent.movement_requested | Pip | simulation |  |
| 14 | agent.arrived | Pip | simulation |  |
| 15 | agent.status_changed | Pip | simulation | EXECUTING |
| 16 | report.submitted | Pip | simulation | Started: Research the market |
| 17 | tool.started | Pip | simulation | query_market_source |
| 18 | research.started | Pip | live |  |
| 19 | research.finding_created | Pip | live | 'productivity' in apple app store top charts (US) |
| 20 | tool.completed | Pip | simulation | ok |
| 21 | artifact.created | Pip | simulation | Research brief — Steady Focus |
| 22 | research.opportunity_identified | Pip | simulation | Steady Focus |
| 23 | agent.movement_requested | Pip | simulation |  |
| 24 | agent.arrived | Pip | simulation |  |
| 25 | package.dispatched | Pip | live | research_brief |
| 26 | package.in_transit |  | live | research_brief |
| 27 | research.completed | Pip | simulation |  |
| 28 | report.submitted | Pip | live | Opportunity 'Steady Focus' scored 0.76 (medium); brief dispatched to the General Manager. |
| 29 | report.submitted | Pip | simulation | Done: Research the market |
| 30 | task.completed | Pip | simulation | Research the market |
| 31 | agent.status_changed | Pip | simulation | COMPLETED |
| 32 | mission.completed |  | simulation | COMPLETED |
| 33 | agent.status_changed | Pip | simulation | IDLE |
| 34 | package.arrived |  | live | research_brief |
| 35 | agent.movement_requested | Atlas | live |  |
| 36 | agent.arrived | Atlas | live |  |
| 37 | package.received | Atlas | live | research_brief |
| 38 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 39 | manager.review_started | Atlas | live |  |
| 40 | manager.decision_recorded | Atlas | live | route |
| 41 | manager.review_completed | Atlas | live | route |
| 42 | manager.decision_recorded | Atlas | live | route:app_studio |
| 43 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 44 | package.dispatched | Atlas | live | product_proposal |
| 45 | package.in_transit |  | live | product_proposal |
| 46 | package.arrived |  | live | product_proposal |
| 47 | agent.movement_requested | Orin | live |  |
| 48 | agent.arrived | Orin | live |  |
| 49 | package.received | Orin | live | product_proposal |
| 50 | manager.decision_recorded | Orin | live | accepted |
| 51 | opportunity.status_changed | Orin | simulation | Steady Focus — productivity app |
| 52 | mission.created |  | simulation | Build Steady Focus |
| 53 | manager.goal_assigned | Atlas | live |  |
| 54 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 55 | mission.status_changed |  | simulation | VALIDATING |
| 56 | agent.message | Vega | simulation | Permissions validated for build prototype: 4 tools within project policy. |
| 57 | mission.status_changed |  | simulation | PLANNING |
| 58 | task.assigned | Kade | simulation | Build the prototype from the approved spec |
| 59 | task.assigned | Kade | simulation | Package a release bundle |
| 60 | agent.message | Vega | simulation | Plan: build the prototype from the approved spec, package a release bundle. |
| 61 | mission.status_changed |  | simulation | QUEUED |
| 62 | mission.started |  | simulation | RUNNING |
| 63 | task.started | Kade | simulation | Build the prototype from the approved spec |
| 64 | agent.status_changed | Kade | simulation | ASSIGNED |
| 65 | agent.movement_requested | Kade | simulation |  |
| 66 | agent.arrived | Kade | simulation |  |
| 67 | agent.status_changed | Kade | simulation | EXECUTING |
| 68 | report.submitted | Kade | simulation | Started: Build the prototype from the approved spec |
| 69 | tool.started | Kade | simulation | scaffold_prototype |
| 70 | tool.completed | Kade | simulation | ok |
| 71 | tool.started | Kade | simulation | read_file |
| 72 | tool.completed | Kade | simulation | ok |
| 73 | report.submitted | Kade | simulation | Done: Build the prototype from the approved spec |
| 74 | task.completed | Kade | simulation | Build the prototype from the approved spec |
| 75 | agent.status_changed | Kade | simulation | COMPLETED |
| 76 | task.started | Kade | simulation | Package a release bundle |
| 77 | agent.status_changed | Kade | simulation | ASSIGNED |
| 78 | agent.status_changed | Kade | simulation | EXECUTING |
| 79 | report.submitted | Kade | simulation | Started: Package a release bundle |
| 80 | tool.started | Kade | simulation | build_release_bundle |
| 81 | artifact.created | Kade | simulation | bundle e85a715bda |
| 82 | tool.completed | Kade | simulation | ok |
| 83 | report.submitted | Kade | simulation | Done: Package a release bundle |
| 84 | task.completed | Kade | simulation | Package a release bundle |
| 85 | agent.status_changed | Kade | simulation | COMPLETED |
| 86 | mission.completed |  | simulation | COMPLETED |
| 87 | agent.status_changed | Kade | simulation | IDLE |
| 88 | package.dispatched | Kade | live | code_artifact |
| 89 | package.in_transit |  | live | code_artifact |
| 90 | manager.decision_recorded | Atlas | live | on_track |
| 91 | package.arrived |  | live | code_artifact |
| 92 | agent.movement_requested | Sentry | live |  |
| 93 | agent.arrived | Sentry | live |  |
| 94 | package.received | Sentry | live | code_artifact |
| 95 | mission.created |  | simulation | QA Steady Focus |
| 96 | opportunity.status_changed | Sentry | simulation | Steady Focus — productivity app |
| 97 | mission.status_changed |  | simulation | VALIDATING |
| 98 | agent.message | Vega | simulation | Permissions validated for qa prototype: 4 tools within project policy. |
| 99 | mission.status_changed |  | simulation | PLANNING |
| 100 | task.assigned | Sentry | simulation | Test the exact release bundle |
| 101 | agent.message | Vega | simulation | Plan: test the exact release bundle. |
| 102 | mission.status_changed |  | simulation | QUEUED |
| 103 | mission.started |  | simulation | RUNNING |
| 104 | task.started | Sentry | simulation | Test the exact release bundle |
| 105 | agent.status_changed | Sentry | simulation | ASSIGNED |
| 106 | agent.movement_requested | Sentry | simulation |  |
| 107 | agent.arrived | Sentry | simulation |  |
| 108 | agent.status_changed | Sentry | simulation | EXECUTING |
| 109 | report.submitted | Sentry | simulation | Started: Test the exact release bundle |
| 110 | tool.started | Sentry | simulation | stage_bundle |
| 111 | tool.completed | Sentry | simulation | ok |
| 112 | tool.started | Sentry | simulation | run_build |
| 113 | tool.completed | Sentry | simulation | ok |
| 114 | tool.started | Sentry | simulation | run_tests |
| 115 | tool.completed | Sentry | simulation | 8 passed in 0.02s |
| 116 | tool.started | Sentry | simulation | create_artifact |
| 117 | artifact.created | Sentry | simulation | QA on bundle e85a715bda — 8 passed in 0.02s |
| 118 | tool.completed | Sentry | simulation | ok |
| 119 | agent.message | Sentry | simulation | Tested bundle e85a715bda: 8 passed in 0.02s. |
| 120 | report.submitted | Sentry | simulation | Done: Test the exact release bundle |
| 121 | task.completed | Sentry | simulation | Test the exact release bundle |
| 122 | agent.status_changed | Sentry | simulation | COMPLETED |
| 123 | mission.completed |  | simulation | COMPLETED |
| 124 | agent.status_changed | Sentry | simulation | IDLE |
| 125 | package.dispatched | Sentry | live | test_report |
| 126 | package.in_transit |  | live | test_report |
| 127 | package.arrived |  | live | test_report |
| 128 | package.received | Atlas | live | test_report |
| 129 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 130 | manager.review_started |  | live |  |
| 131 | artifact.created | Atlas | live | Manager review |
| 132 | manager.decision_recorded | Atlas | live | APPROVED_FOR_OWNER_REVIEW |
| 133 | manager.review_completed | Atlas | live | APPROVED_FOR_OWNER_REVIEW |
| 134 | release.manager_approved | Atlas | live |  |
| 135 | package.dispatched | Atlas | live | release_package |
| 136 | package.in_transit |  | live | release_package |
| 137 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 138 | package.arrived |  | live | release_package |
| 139 | package.received |  | live | release_package |
| 140 | release.owner_approval_requested |  | live | Steady Focus — productivity app |
| 141 | mission.created |  | simulation | Unauthorized release attempt |
| 142 | mission.status_changed |  | simulation | VALIDATING |
| 143 | agent.message | Vega | simulation | Permissions validated for release: 2 tools within project policy. |
| 144 | mission.status_changed |  | simulation | PLANNING |
| 145 | task.assigned | Vega | simulation | Release the owner-approved bundle |
| 146 | agent.message | Vega | simulation | Plan: release the owner-approved bundle. |
| 147 | mission.status_changed |  | simulation | QUEUED |
| 148 | mission.started |  | simulation | RUNNING |
| 149 | task.started | Vega | simulation | Release the owner-approved bundle |
| 150 | agent.status_changed | Vega | simulation | ASSIGNED |
| 151 | agent.movement_requested | Vega | simulation |  |
| 152 | agent.arrived | Vega | simulation |  |
| 153 | agent.status_changed | Vega | simulation | EXECUTING |
| 154 | report.submitted | Vega | simulation | Started: Release the owner-approved bundle |
| 155 | tool.failed | Vega | simulation | submit_release |
| 156 | report.submitted | Vega | simulation | Release the owner-approved bundle: permission denied: release refused: no owner release au |
| 157 | task.failed | Vega | simulation | Release the owner-approved bundle |
| 158 | agent.status_changed | Vega | simulation | FAILED |
| 159 | mission.failed |  | simulation | FAILED |
| 160 | agent.status_changed | Vega | simulation | IDLE |
| 161 | release.owner_approved |  | live |  |
| 162 | release.authorized |  | live |  |
| 163 | opportunity.status_changed |  | simulation | Steady Focus — productivity app |
| 164 | mission.created |  | simulation | Release Steady Focus |
| 165 | mission.status_changed |  | simulation | VALIDATING |
| 166 | agent.message | Vega | simulation | Permissions validated for release: 2 tools within project policy. |
| 167 | mission.status_changed |  | simulation | PLANNING |
| 168 | task.assigned | Vega | simulation | Release the owner-approved bundle |
| 169 | agent.message | Vega | simulation | Plan: release the owner-approved bundle. |
| 170 | mission.status_changed |  | simulation | QUEUED |
| 171 | mission.started |  | simulation | RUNNING |
| 172 | task.started | Vega | simulation | Release the owner-approved bundle |
| 173 | agent.status_changed | Vega | simulation | ASSIGNED |
| 174 | agent.status_changed | Vega | simulation | EXECUTING |
| 175 | report.submitted | Vega | simulation | Started: Release the owner-approved bundle |
| 176 | tool.started | Vega | simulation | submit_release |
| 177 | release.executed | Vega | simulation |  |
| 178 | tool.completed | Vega | simulation | ok |
| 179 | agent.message | Vega | simulation | Released bundle e85a715bda to the local release channel. |
| 180 | report.submitted | Vega | simulation | Done: Release the owner-approved bundle |
| 181 | task.completed | Vega | simulation | Release the owner-approved bundle |
| 182 | agent.status_changed | Vega | simulation | COMPLETED |
| 183 | mission.completed |  | simulation | COMPLETED |
| 184 | agent.status_changed | Vega | simulation | IDLE |
| 185 | release.invalidated |  | live |  |
| 186 | opportunity.status_changed |  | simulation | Steady Focus — productivity app |
| 187 | manager.decision_recorded | Atlas | live | REVIEW_REQUIRED |
| 188 | manager.escalation_created | Atlas | live | REVIEW_REQUIRED |
| 189 | manager.decision_recorded | Atlas | live | revise |
| 190 | manager.revision_requested | Atlas | live | revise |
| 191 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 192 | package.dispatched | Atlas | live | revision_request |
| 193 | package.in_transit |  | live | revision_request |
| 194 | report.submitted | Atlas | live | Revision requested for Steady Focus — productivity app: stored bundle does not match its r |
| 195 | package.arrived |  | live | revision_request |
| 196 | package.received | Orin | live | revision_request |
| 197 | mission.created |  | simulation | Build Steady Focus |
| 198 | manager.goal_assigned | Atlas | live |  |
| 199 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 200 | mission.status_changed |  | simulation | VALIDATING |
| 201 | agent.message | Vega | simulation | Permissions validated for build prototype: 4 tools within project policy. |
| 202 | mission.status_changed |  | simulation | PLANNING |
| 203 | task.assigned | Kade | simulation | Build the prototype from the approved spec |
| 204 | task.assigned | Kade | simulation | Package a release bundle |
| 205 | agent.message | Vega | simulation | Plan: build the prototype from the approved spec, package a release bundle. |
| 206 | mission.status_changed |  | simulation | QUEUED |
| 207 | mission.started |  | simulation | RUNNING |
| 208 | task.started | Kade | simulation | Build the prototype from the approved spec |
| 209 | agent.status_changed | Kade | simulation | ASSIGNED |
| 210 | agent.status_changed | Kade | simulation | EXECUTING |
| 211 | report.submitted | Kade | simulation | Started: Build the prototype from the approved spec |
| 212 | tool.started | Kade | simulation | scaffold_prototype |
| 213 | tool.completed | Kade | simulation | ok |
| 214 | tool.started | Kade | simulation | read_file |
| 215 | tool.completed | Kade | simulation | ok |
| 216 | report.submitted | Kade | simulation | Done: Build the prototype from the approved spec |
| 217 | task.completed | Kade | simulation | Build the prototype from the approved spec |
| 218 | agent.status_changed | Kade | simulation | COMPLETED |
| 219 | task.started | Kade | simulation | Package a release bundle |
| 220 | agent.status_changed | Kade | simulation | ASSIGNED |
| 221 | agent.status_changed | Kade | simulation | EXECUTING |
| 222 | report.submitted | Kade | simulation | Started: Package a release bundle |
| 223 | tool.started | Kade | simulation | build_release_bundle |
| 224 | artifact.created | Kade | simulation | bundle e85a715bda |
| 225 | tool.completed | Kade | simulation | ok |
| 226 | manager.decision_recorded | Atlas | live | on_track |
| 227 | report.submitted | Kade | simulation | Done: Package a release bundle |
| 228 | task.completed | Kade | simulation | Package a release bundle |
| 229 | agent.status_changed | Kade | simulation | COMPLETED |
| 230 | mission.completed |  | simulation | COMPLETED |
| 231 | agent.status_changed | Kade | simulation | IDLE |
| 232 | package.dispatched | Kade | live | code_artifact |
| 233 | package.in_transit |  | live | code_artifact |
| 234 | package.arrived |  | live | code_artifact |
| 235 | agent.movement_requested | Sentry | live |  |
| 236 | agent.arrived | Sentry | live |  |
| 237 | package.received | Sentry | live | code_artifact |
| 238 | mission.created |  | simulation | QA Steady Focus |
| 239 | opportunity.status_changed | Sentry | simulation | Steady Focus — productivity app |
| 240 | mission.status_changed |  | simulation | VALIDATING |
| 241 | agent.message | Vega | simulation | Permissions validated for qa prototype: 4 tools within project policy. |
| 242 | mission.status_changed |  | simulation | PLANNING |
| 243 | task.assigned | Sentry | simulation | Test the exact release bundle |
| 244 | agent.message | Vega | simulation | Plan: test the exact release bundle. |
| 245 | mission.status_changed |  | simulation | QUEUED |
| 246 | mission.started |  | simulation | RUNNING |
| 247 | task.started | Sentry | simulation | Test the exact release bundle |
| 248 | agent.status_changed | Sentry | simulation | ASSIGNED |
| 249 | agent.movement_requested | Sentry | simulation |  |
| 250 | agent.arrived | Sentry | simulation |  |
| 251 | agent.status_changed | Sentry | simulation | EXECUTING |
| 252 | report.submitted | Sentry | simulation | Started: Test the exact release bundle |
| 253 | tool.started | Sentry | simulation | stage_bundle |
| 254 | tool.completed | Sentry | simulation | ok |
| 255 | tool.started | Sentry | simulation | run_build |
| 256 | tool.completed | Sentry | simulation | ok |
| 257 | tool.started | Sentry | simulation | run_tests |
| 258 | tool.completed | Sentry | simulation | 8 passed in 0.02s |
| 259 | tool.started | Sentry | simulation | create_artifact |
| 260 | artifact.created | Sentry | simulation | QA on bundle e85a715bda — 8 passed in 0.02s |
| 261 | tool.completed | Sentry | simulation | ok |
| 262 | agent.message | Sentry | simulation | Tested bundle e85a715bda: 8 passed in 0.02s. |
| 263 | report.submitted | Sentry | simulation | Done: Test the exact release bundle |
| 264 | task.completed | Sentry | simulation | Test the exact release bundle |
| 265 | agent.status_changed | Sentry | simulation | COMPLETED |
| 266 | mission.completed |  | simulation | COMPLETED |
| 267 | agent.status_changed | Sentry | simulation | IDLE |
| 268 | package.dispatched | Sentry | live | test_report |
| 269 | package.in_transit |  | live | test_report |
| 270 | package.arrived |  | live | test_report |
| 271 | package.received | Atlas | live | test_report |
| 272 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 273 | manager.review_started |  | live |  |
| 274 | artifact.created | Atlas | live | Manager review |
| 275 | manager.decision_recorded | Atlas | live | APPROVED_FOR_OWNER_REVIEW |
| 276 | manager.review_completed | Atlas | live | APPROVED_FOR_OWNER_REVIEW |
| 277 | release.manager_approved | Atlas | live |  |
| 278 | package.dispatched | Atlas | live | release_package |
| 279 | package.in_transit |  | live | release_package |
| 280 | opportunity.status_changed | Atlas | simulation | Steady Focus — productivity app |
| 281 | package.arrived |  | live | release_package |
| 282 | package.received |  | live | release_package |
| 283 | release.owner_approval_requested |  | live | Steady Focus — productivity app |
| 284 | mission.created |  | simulation | Replay old approval |
| 285 | mission.status_changed |  | simulation | VALIDATING |
| 286 | mission.failed |  | simulation | FAILED |
