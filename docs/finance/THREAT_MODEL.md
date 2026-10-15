# AI Central Bank: financial permissions and threat model

This is the first step of V5. The rest of the Financial District is built to the rules on this page, and each
rule names the test that enforces it.

## What we protect

| Asset | Why it matters |
|---|---|
| Money movement: purchases, payments, transfers, payout or banking changes | Irreversible loss |
| Official submissions: tax filings, regulatory forms | Legal consequences; they can't be withdrawn |
| Credentials for financial connections (API keys, OAuth/Plaid tokens) | They give ongoing access to accounts |
| Ledger data: balances, transactions, payees, tax documents | Privacy; also helps social engineering |
| Integrity of approvals and the audit trail | Without it nobody can tell who authorized what |

## Who could attack

1. **A model behaving badly.** Prompt injection in research text or transaction descriptions; a confused agent;
   an over-eager agent "saving money" by cancelling something.
2. **A compromised or buggy agent tool.** It calls financial tools it shouldn't, or replays an approval.
3. **A low-privilege human user.** In Supabase mode, a viewer or operator reading ledger data or deciding approvals.
4. **Someone with a stolen session token.** They try to approve a payment.
5. **Tampering between approval and execution.** The amount, recipient or account changes after the owner looked.
6. **Data from external feeds.** Hostile or malformed CSVs or API responses; duplicate imports inflating figures.

## The rules

| # | Rule | Enforced in | Tested by |
|---|---|---|---|
| F1 | **No agent can spend, transfer, file, publish or change banking on its own.** Every such action is a `financial_approvals` row that the owner must approve. | `services/finance/approvals.py`, `execute_financial_action` tool | `test_execution_refused_without_owner_approval` |
| F2 | **An approval covers exactly one action.** Its hash covers action type, amount in minor units, currency, recipient, account reference and the packet. Any difference is refused. | `approvals.payload_hash`, re-checked at execution | `test_modified_amount_or_recipient_is_refused` |
| F3 | **Approvals expire and work once.** `expires_at` is checked when the owner decides and again at execution. An executed approval can't be used again. | `approvals.decide`, `approvals.authorize_execution` | `test_expired_approval_refused`, `test_replay_refused` |
| F4 | **Revalidate right before acting.** Inside the same transaction that records execution: approval state, expiry, hash, packet state, emergency stop, the agent's financial capability, and that the deciding user still holds the owner role. | `registry._check_permissions` → `finance_gate` | `test_emergency_stop_blocks_financial_execution` |
| F5 | **Approving needs step-up authentication.** Approving any financial action needs a fresh second factor: a TOTP code, or a Supabase `aal2` session. The step-up token lasts 5 minutes and is bound to the user. Rejecting, deferring or asking for more research needs no step-up, because those directions are safe. | `services/finance/stepup.py` | `test_approve_requires_step_up`, `test_step_up_token_bound_to_user_and_expires` |
| F6 | **Only owners and admins see financial data.** Every `/api/finance/*` route requires the owner or admin role. Only the owner can decide approvals, authorize connections or export. | `permissions.require_finance` | `test_viewer_and_operator_cannot_read_finance` |
| F7 | **Financial tools belong to the finance department.** A financial tool needs (a) the capability, (b) the agent's department to be `finance`, and (c) the task to permit it. Other agents can only file a *purchase request*, which reads nothing. | `registry._check_permissions` → `finance_gate` | `test_non_finance_agent_cannot_read_ledger` |
| F8 | **Models see as little as possible.** Prompts get categories, rounded amounts and vendor names. They never get account numbers, card numbers, raw descriptions or balances. Untrusted text is fenced. | `finance/redaction.py`, the research and finance handlers | `test_model_prompts_never_contain_account_data` |
| F9 | **The event stream stays non-sensitive.** `finance.*` and financial `package.*` events carry ids, statuses and labels, never amounts, balances or account data. Details come only from owner/admin endpoints. | `finance/events.py` | `test_finance_events_carry_no_amounts_or_accounts` |
| F10 | **Integrations are read-only and explicitly authorized.** A connection starts as `PENDING_AUTHORIZATION`. Only the owner, after step-up, activates it by submitting a credential. Nothing is picked up from the environment or from any assistant's own connections. Adapters declare read-only scopes, and a write-capable adapter is refused. | `finance/connectors.py`, `POST /api/finance/connections/{id}/authorize` | `test_connection_requires_explicit_owner_authorization`, `test_write_scopes_refused` |
| F11 | **Secrets are encrypted at rest.** Connection credentials are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using `AICIV_FINANCE_KEY`. Full account numbers are never stored, only the last 4 digits and a keyed HMAC for matching. | `finance/crypto.py` | `test_credentials_encrypted_at_rest` |
| F12 | **Every financial change is audited in a tamper-evident log.** `financial_audit_events` is append-only (database triggers) and hash-chained. | `finance/audit.py`, migration 0003 | `test_audit_chain_detects_tampering`, `test_audit_is_append_only` |
| F13 | **No fabricated data.** Every row carries `data_mode` (`simulated`, `upload` or `live`). Simulated data is labeled in the API, in the UI and in exports. Missing data shows up as a coverage gap, never as zero. | `finance/dashboard.py`, `finance/sync.py` | `test_dashboard_reports_gaps_not_zeros`, `test_simulated_data_is_labeled_everywhere` |
| F14 | **Never silently cancel or miss a deadline.** No tool cancels a service. Bills inside their reminder window always produce a reminder. Cancelling or switching is a recommendation for the owner. | `finance/bills.py` | `test_due_bills_always_raise_reminders` |
| F15 | **No tax filing without an authorized filing integration,** even with an approval. None exists in this build, so filing is always refused. Tax figures are labeled estimates. | `finance/tax.py`, `execute_financial_action` | `test_tax_filing_always_refused_without_integration` |
| F16 | **Retention and deletion.** The owner can delete a connection's synced data. Audit events stay, with a "data deleted" entry. Raw uploads are kept 90 days by default (`AICIV_FINANCE_UPLOAD_RETENTION_DAYS`). | `finance/retention.py` | `test_delete_connection_data_keeps_audit` |
| F17 | **Imports are idempotent.** A deterministic key per connection and external id makes re-syncing or re-uploading the same file insert nothing new. | `finance/sync.py` | `test_resync_is_idempotent` |

## Residual risks (open)

- There are no payment, transfer or filing rails. An approved purchase on live data becomes a checklist the owner
  completes by hand. Executing an approved action is only automated for simulated data, where it is recorded as
  simulated.
- TOTP secrets live in the server's data directory (or env). A hardware key (WebAuthn) would be stronger.
- In dev mode, anyone on localhost is the owner (unchanged from V3). Step-up still applies to financial approvals.
- Database-level RLS gives finance tables owner/admin-only read policies for direct client access. The API still
  connects as the service role, so organization scoping in the API is by query.
