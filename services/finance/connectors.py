"""Financial data adapters (spec §4). Every adapter is read-only, declares its scopes, and runs only on a
connection the owner explicitly authorized in this app (THREAT_MODEL F10). Nothing is read from the environment
or from any assistant's own account connections.

Built: simulated (labeled), CSV statement upload, Stripe (restricted read-only key), Plaid (transactions product),
App Store Connect (sales reports). Not built yet: accounting systems, marketplace payouts, billing services. They
are listed, show up as coverage gaps, and cannot be authorized.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx


class AdapterError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # auth | rate_limit | unavailable | bad_input


@dataclass
class RawAccount:
    external_id: str
    name: str
    account_type: str
    currency: str = "USD"
    current_balance_minor: int | None = None
    available_balance_minor: int | None = None
    mask: str | None = None


@dataclass
class RawTxn:
    posted_at: str
    amount_minor: int
    description: str
    currency: str = "USD"
    external_id: str | None = None
    account_external_id: str | None = None
    merchant: str | None = None
    kind_hint: str | None = None
    category_hint: str | None = None


@dataclass
class SyncBatch:
    data_mode: str
    accounts: list[RawAccount] = field(default_factory=list)
    transactions: list[RawTxn] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rejected: int = 0
    covered_from: str | None = None
    covered_to: str | None = None
    extras: dict = field(default_factory=dict)   # simulated adapter only: bills, subscriptions, revenue sources, invoices
    cursor: str | None = None


@dataclass(frozen=True)
class Provider:
    key: str
    kind: str
    label: str
    scopes: tuple[str, ...]
    credential_hint: str
    built: bool = True
    read_only: bool = True


PROVIDERS: dict[str, Provider] = {p.key: p for p in [
    Provider("simulated", "bank_feed", "Simulated business ledger (labeled test data)", ("read:simulated",), "none"),
    Provider("csv_upload", "upload", "Bank or card statement (CSV upload)", ("read:uploaded_file",), "upload a CSV"),
    Provider("stripe", "payment_processor", "Stripe", ("balance_transactions:read", "balance:read"),
             "a restricted key (rk_…) with read access to Balance and Balance transactions only"),
    Provider("plaid", "bank_feed", "Bank and card accounts via Plaid", ("transactions:read", "balance:read"),
             'JSON {"client_id", "secret", "access_token", "env"}; the access token comes from Plaid Link with the transactions product'),
    Provider("app_store_connect", "app_store", "App Store Connect sales and proceeds", ("sales_reports:read",),
             'JSON {"issuer_id", "key_id", "private_key", "vendor_number"}: an API key with the Finance or Sales role'),
    Provider("quickbooks", "accounting", "QuickBooks Online", ("accounting:read",), "", built=False),
    Provider("xero", "accounting", "Xero", ("accounting.transactions.read",), "", built=False),
    Provider("etsy_payments", "marketplace", "Etsy shop payments ledger", ("transactions_r",), "", built=False),
    Provider("paddle", "billing", "Paddle billing", ("transactions:read",), "", built=False),
]}
SOURCE_KINDS = ("bank_feed", "card_feed", "payment_processor", "app_store", "marketplace", "accounting", "billing", "upload")
WRITE_SCOPE = re.compile(r"(?i)(write|:w\b|_w\b|payments:create|transfer|payout)")


def check_read_only(provider: Provider, requested_scopes: list[str] | None = None) -> None:
    for s in list(provider.scopes) + list(requested_scopes or []):
        if WRITE_SCOPE.search(s) and not s.endswith(":read"):
            raise AdapterError("bad_input", f"scope {s!r} would allow writes; only read-only access is allowed")


def _iso(d: date | datetime) -> str:
    if isinstance(d, datetime):
        return d.astimezone(timezone.utc).isoformat()
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


# ---------------------------------------------------------------------------------------------- simulated
def simulated_batch(anchor: str) -> SyncBatch:
    """Six months of a small app business's money, deterministic for a given anchor month. Every row is labeled
    simulated and descriptions say SIM. Nothing here describes a real account."""
    a = date.fromisoformat(anchor)
    rnd = random.Random(f"aiciv-sim-{anchor}")
    start = (a.replace(day=1) - timedelta(days=150)).replace(day=1)
    today = datetime.now(timezone.utc).date()
    end = min(today, a + timedelta(days=60))
    txns: list[RawTxn] = []
    accts = {
        "sim-checking": RawAccount("sim-checking", "SIM Business Checking", "checking", mask="0001"),
        "sim-card": RawAccount("sim-card", "SIM Business Card", "credit_card", mask="4242"),
        "sim-stripe": RawAccount("sim-stripe", "SIM Stripe balance", "processor_balance", mask="STRP"),
        "sim-appstore": RawAccount("sim-appstore", "SIM App Store proceeds", "store_proceeds", mask="ASC1"),
    }

    def add(day: date, acct: str, cents: int, desc: str, merchant: str | None = None, kind: str | None = None, cat: str | None = None) -> None:
        if day > end:
            return
        txns.append(RawTxn(posted_at=_iso(day), amount_minor=cents, description=f"SIM {desc}", external_id=f"sim:{acct}:{day}:{desc}:{cents}",
                           account_external_id=acct, merchant=merchant, kind_hint=kind, category_hint=cat))

    d = start
    month_index = 0
    while d <= end:
        first = d.replace(day=1)
        # Stripe: weekly gross, fees, payouts
        for wk in range(4):
            day = first + timedelta(days=3 + wk * 7)
            gross = rnd.randint(55_000, 92_000)
            fee = round(gross * 0.029) + 30 * rnd.randint(18, 30)
            add(day, "sim-stripe", gross, "Stripe charges (weekly)", "Stripe", "revenue", "revenue")
            add(day, "sim-stripe", -fee, "Stripe processing fee", "Stripe", "fee", "payment_fees")
            add(day + timedelta(days=2), "sim-stripe", -(gross - fee), "Payout to checking", "Stripe", "transfer", "transfers")
            add(day + timedelta(days=2), "sim-checking", gross - fee, "Online transfer from Stripe", "Stripe", "transfer", "transfers")
        if rnd.random() < 0.8:
            add(first + timedelta(days=17), "sim-stripe", -999, "Customer refund", "Stripe", "refund", "refunds")
        # App Store: monthly proceeds, commission shown separately
        sales = rnd.randint(48_000, 81_000)
        commission = round(sales * 0.15)
        add(first + timedelta(days=27), "sim-appstore", sales, "App Store sales (month)", "Apple", "revenue", "revenue")
        add(first + timedelta(days=27), "sim-appstore", -commission, "App Store commission", "Apple", "fee", "store_commission")
        # Subscriptions on the card
        for dd, cents, name in ((2, -400, "GitHub Team"), (5, -2000, "Vercel Pro"), (8, -1500, "Figma Professional"),
                                (9, -1000, "Notion Plus"), (11, -1400, "Google Workspace")):
            add(first + timedelta(days=dd), "sim-card", cents, name, name.split()[0])
        add(first + timedelta(days=14), "sim-card", -rnd.randint(2_800, 6_400), "Anthropic API usage", "Anthropic")
        if month_index == 1:
            add(first + timedelta(days=20), "sim-card", -9_900, "Apple Developer Program (annual)", "Apple Developer")
        # Bank: bills and fees
        add(first + timedelta(days=1), "sim-checking", -25_000, "Cowork Collective membership", "Cowork Collective")
        add(first + timedelta(days=15), "sim-checking", -4_500, "Verizon phone", "Verizon")
        add(first + timedelta(days=18), "sim-checking", -7_000, "Comcast internet", "Comcast")
        add(first + timedelta(days=27), "sim-checking", -1_500, "Monthly maintenance fee", "SIM Bank", "fee", "bank_fees")
        if month_index == 2:
            add(first + timedelta(days=12), "sim-checking", -2_500, "Outgoing wire fee", "SIM Bank", "fee", "bank_fees")
            add(first + timedelta(days=12), "sim-checking", -60_000, "Wire to contractor (design)", "Contractor", "expense", "contractors")
        if month_index == 3:
            add(first + timedelta(days=6), "sim-card", -237, "Foreign transaction fee", "SIM Card", "fee", "bank_fees")
        if first.month in (4, 6, 9, 1):
            add(first + timedelta(days=14), "sim-checking", -80_000, "IRS USATAXPYMT estimated tax", "IRS", "tax", "taxes")
        card_payment = 12_000 + rnd.randint(0, 4_000)
        add(first + timedelta(days=25), "sim-checking", -card_payment, "Card payment to SIM Card", "SIM Card", "transfer", "transfers")
        add(first + timedelta(days=25), "sim-card", card_payment, "Payment received, thank you", "SIM Card", "transfer", "transfers")
        d = (first + timedelta(days=32)).replace(day=1)
        month_index += 1

    opening = {"sim-checking": 1_250_000, "sim-card": 0, "sim-stripe": 50_000, "sim-appstore": 0}
    for k, acct in accts.items():
        bal = opening[k] + sum(t.amount_minor for t in txns if t.account_external_id == k)
        acct.current_balance_minor = bal
        acct.available_balance_minor = bal if k != "sim-stripe" else max(0, bal - 25_000)  # processor reserve held back
    soon = today
    extras = {
        "bills": [
            {"payee": "Comcast internet", "amount_minor": 7_000, "due_at": _iso(soon + timedelta(days=3)), "recurrence": "monthly", "autopay": 0},
            {"payee": "Verizon phone", "amount_minor": 4_500, "due_at": _iso(soon + timedelta(days=9)), "recurrence": "monthly", "autopay": 1},
            {"payee": "Cowork Collective", "amount_minor": 25_000, "due_at": _iso(soon + timedelta(days=16)), "recurrence": "monthly", "autopay": 0},
        ],
        "subscriptions": [
            {"vendor": "GitHub", "plan": "Team", "amount_minor": 400, "interval": "month", "category_key": "software"},
            {"vendor": "Vercel", "plan": "Pro", "amount_minor": 2_000, "interval": "month", "category_key": "software"},
            {"vendor": "Figma", "plan": "Professional", "amount_minor": 1_500, "interval": "month", "category_key": "software"},
            {"vendor": "Notion", "plan": "Plus", "amount_minor": 1_000, "interval": "month", "category_key": "software"},
            {"vendor": "Google Workspace", "plan": "Business Starter", "amount_minor": 1_400, "interval": "month", "category_key": "software",
             "contract_terms": "annual commitment, billed monthly"},
            {"vendor": "Apple Developer", "plan": "Program", "amount_minor": 9_900, "interval": "year", "category_key": "software"},
        ],
        "revenue_sources": [{"name": "Web subscriptions", "platform": "stripe"}, {"name": "iOS app", "platform": "app_store"}],
        "invoices": [
            {"direction": "receivable", "counterparty": "SIM Client Co.", "amount_minor": 120_000, "due_at": _iso(soon + timedelta(days=20))},
            {"direction": "payable", "counterparty": "SIM Design Studio", "amount_minor": 45_000, "due_at": _iso(soon + timedelta(days=25))},
        ],
    }
    return SyncBatch(data_mode="simulated", accounts=list(accts.values()), transactions=txns, covered_from=_iso(start), covered_to=_iso(end),
                     extras=extras)


# ---------------------------------------------------------------------------------------------- CSV upload
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y")


def _parse_date(s: str) -> str:
    s = s.strip()
    for f in _DATE_FORMATS:
        try:
            return _iso(datetime.strptime(s, f).date())
        except ValueError:
            continue
    raise ValueError(f"unrecognized date {s!r}")


def _cents(s: str) -> int:
    s = s.strip().replace("$", "").replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", s):
        raise ValueError(f"unrecognized amount {s!r}")
    v = round(float(s) * 100)
    return -v if neg else v


def csv_batch(data: bytes, max_rows: int = 20_000) -> SyncBatch:
    """Columns (case-insensitive): Date, Description, and either Amount (negative = money out) or Debit/Credit.
    Bad rows are counted and reported, never guessed."""
    if len(data) > 5_000_000:
        raise AdapterError("bad_input", "file is larger than 5 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AdapterError("bad_input", "file is not UTF-8 text") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise AdapterError("bad_input", "no header row")
    cols = {c.lower().strip(): c for c in reader.fieldnames}
    date_c = cols.get("date") or cols.get("posted date") or cols.get("transaction date")
    desc_c = cols.get("description") or cols.get("memo") or cols.get("payee")
    amt_c = cols.get("amount")
    debit_c, credit_c = cols.get("debit"), cols.get("credit")
    if not (date_c and desc_c and (amt_c or (debit_c and credit_c))):
        raise AdapterError("bad_input", "need Date, Description and Amount (or Debit and Credit) columns")
    out = SyncBatch(data_mode="upload")
    seen: dict[tuple, int] = {}
    for i, row in enumerate(reader, start=2):
        if i - 1 > max_rows:
            out.errors.append(f"stopped after {max_rows} rows")
            break
        try:
            posted = _parse_date(row[date_c])
            if amt_c:
                cents = _cents(row[amt_c])
            else:
                debit = _cents(row[debit_c]) if (row.get(debit_c) or "").strip() else 0
                credit = _cents(row[credit_c]) if (row.get(credit_c) or "").strip() else 0
                cents = credit - abs(debit)
            desc = (row[desc_c] or "").strip()
            if not desc:
                raise ValueError("empty description")
        except (ValueError, KeyError) as exc:
            out.rejected += 1
            if len(out.errors) < 20:
                out.errors.append(f"row {i}: {exc}")
            continue
        key = (posted, cents, desc)
        seen[key] = seen.get(key, 0) + 1   # identical rows on the same day are distinct transactions, numbered in file order
        out.transactions.append(RawTxn(posted_at=posted, amount_minor=cents, description=desc,
                                       external_id=f"csv:{posted[:10]}:{cents}:{desc}:{seen[key]}"))
    if out.transactions:
        out.covered_from = min(t.posted_at for t in out.transactions)
        out.covered_to = max(t.posted_at for t in out.transactions)
    return out


# ---------------------------------------------------------------------------------------------- Stripe
def stripe_batch(credential: str, since: str | None, client: httpx.Client | None = None, max_pages: int = 20) -> SyncBatch:
    key = credential.strip()
    if not key.startswith("rk_"):
        raise AdapterError("auth", "use a restricted key (rk_…) with read-only Balance access; secret keys can move money")
    c = client or httpx.Client(base_url="https://api.stripe.com", timeout=20)
    auth = {"Authorization": f"Bearer {key}"}
    out = SyncBatch(data_mode="live")
    r = c.get("/v1/balance", headers=auth)
    _raise_for(r, "stripe")
    bal = r.json()
    avail = sum(x["amount"] for x in bal.get("available", []) if x.get("currency") == "usd")
    pend = sum(x["amount"] for x in bal.get("pending", []) if x.get("currency") == "usd")
    out.accounts.append(RawAccount("stripe-balance", "Stripe balance", "processor_balance", "USD", avail + pend, avail, "STRP"))
    params: dict = {"limit": 100}
    if since:
        params["created[gte]"] = int(datetime.fromisoformat(since).timestamp())
    for _ in range(max_pages):
        r = c.get("/v1/balance_transactions", headers=auth, params=params)
        _raise_for(r, "stripe")
        body = r.json()
        for t in body.get("data", []):
            when = _iso(datetime.fromtimestamp(t["created"], tz=timezone.utc))
            cur = t.get("currency", "usd").upper()
            typ = t.get("type")
            if typ in ("charge", "payment"):
                out.transactions.append(RawTxn(when, t["amount"], f"Stripe charge {t['id']}", cur, f"stripe:{t['id']}", "stripe-balance",
                                               "Stripe", "revenue", "revenue"))
                if t.get("fee"):
                    out.transactions.append(RawTxn(when, -t["fee"], f"Stripe processing fee {t['id']}", cur, f"stripe:{t['id']}:fee",
                                                   "stripe-balance", "Stripe", "fee", "payment_fees"))
            elif typ in ("refund", "payment_refund"):
                out.transactions.append(RawTxn(when, t["amount"], f"Stripe refund {t['id']}", cur, f"stripe:{t['id']}", "stripe-balance",
                                               "Stripe", "refund", "refunds"))
            elif typ == "payout":
                out.transactions.append(RawTxn(when, t["amount"], f"Stripe payout {t['id']}", cur, f"stripe:{t['id']}", "stripe-balance",
                                               "Stripe", "transfer", "transfers"))
            elif typ == "stripe_fee":
                out.transactions.append(RawTxn(when, t["amount"], f"Stripe account fee {t['id']}", cur, f"stripe:{t['id']}", "stripe-balance",
                                               "Stripe", "fee", "payment_fees"))
            else:
                out.transactions.append(RawTxn(when, t["amount"], f"Stripe {typ} {t['id']}", cur, f"stripe:{t['id']}", "stripe-balance",
                                               "Stripe", "other", "uncategorized"))
        if not body.get("has_more") or not body.get("data"):
            break
        params["starting_after"] = body["data"][-1]["id"]
    else:
        out.errors.append(f"stopped after {max_pages} pages; the next sync continues")
    if out.transactions:
        out.covered_from = min(t.posted_at for t in out.transactions)
        out.covered_to = max(t.posted_at for t in out.transactions)
    return out


def _raise_for(r: httpx.Response, provider: str) -> None:
    if r.status_code in (401, 403):
        raise AdapterError("auth", f"{provider} refused the credential ({r.status_code})")
    if r.status_code == 429:
        raise AdapterError("rate_limit", f"{provider} rate limit; retry later")
    if r.status_code >= 400:
        raise AdapterError("unavailable", f"{provider} error {r.status_code}")


# ---------------------------------------------------------------------------------------------- Plaid
PLAID_HOSTS = {"sandbox": "https://sandbox.plaid.com", "production": "https://production.plaid.com"}


def plaid_batch(credential: str, cursor: str | None, client: httpx.Client | None = None, max_pages: int = 20) -> SyncBatch:
    try:
        cred = json.loads(credential)
        env = cred.get("env", "production")
        body_base = {"client_id": cred["client_id"], "secret": cred["secret"], "access_token": cred["access_token"]}
    except (ValueError, KeyError) as exc:
        raise AdapterError("bad_input", 'credential must be JSON {"client_id", "secret", "access_token", "env"}') from exc
    if env not in PLAID_HOSTS:
        raise AdapterError("bad_input", "env must be sandbox or production")
    c = client or httpx.Client(base_url=PLAID_HOSTS[env], timeout=30)
    out = SyncBatch(data_mode="live" if env == "production" else "simulated")
    r = c.post("/accounts/balance/get", json=body_base)
    _raise_for(r, "plaid")
    for a in r.json().get("accounts", []):
        typ = "credit_card" if a.get("type") == "credit" else ("savings" if a.get("subtype") == "savings" else "checking")
        b = a.get("balances", {})
        to_minor = (lambda v: None if v is None else round(float(v) * 100))
        out.accounts.append(RawAccount(a["account_id"], a.get("name", "Account"), typ, (b.get("iso_currency_code") or "USD"),
                                       to_minor(b.get("current")), to_minor(b.get("available")), a.get("mask")))
    nxt = cursor
    for _ in range(max_pages):
        r = c.post("/transactions/sync", json={**body_base, **({"cursor": nxt} if nxt else {}), "count": 500})
        _raise_for(r, "plaid")
        body = r.json()
        for t in body.get("added", []) + body.get("modified", []):
            if t.get("pending"):
                continue
            # Plaid: positive amount = money leaving the account. We store negative = money out.
            out.transactions.append(RawTxn(_iso(date.fromisoformat(t["date"])), -round(float(t["amount"]) * 100), t.get("name") or "",
                                           (t.get("iso_currency_code") or "USD"), f"plaid:{t['transaction_id']}", t["account_id"],
                                           t.get("merchant_name")))
        nxt = body.get("next_cursor")
        if not body.get("has_more"):
            break
    out.cursor = nxt
    if out.transactions:
        out.covered_from = min(t.posted_at for t in out.transactions)
        out.covered_to = max(t.posted_at for t in out.transactions)
    return out


# ---------------------------------------------------------------------------------------------- App Store Connect
def _asc_jwt(cred: dict) -> str:
    import jwt  # ES256 via `cryptography`

    now = int(time.time())
    return jwt.encode({"iss": cred["issuer_id"], "iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"}, cred["private_key"],
                      algorithm="ES256", headers={"kid": cred["key_id"], "typ": "JWT"})


def app_store_batch(credential: str, days: int = 7, client: httpx.Client | None = None) -> SyncBatch:
    """Daily SALES summary reports. Proceeds are in each row's proceeds currency; non-USD rows are reported as a
    coverage gap rather than converted with an invented rate."""
    try:
        cred = json.loads(credential)
        cred["issuer_id"], cred["key_id"], cred["private_key"], cred["vendor_number"]  # noqa: B018
    except (ValueError, KeyError) as exc:
        raise AdapterError("bad_input", 'credential must be JSON {"issuer_id", "key_id", "private_key", "vendor_number"}') from exc
    c = client or httpx.Client(base_url="https://api.appstoreconnect.apple.com", timeout=30)
    token = _asc_jwt(cred)
    out = SyncBatch(data_mode="live")
    today = datetime.now(timezone.utc).date()
    skipped_currency = 0
    for back in range(2, days + 2):  # Apple publishes daily reports with a delay
        day = today - timedelta(days=back)
        r = c.get("/v1/salesReports", headers={"Authorization": f"Bearer {token}", "Accept": "application/a-gzip"},
                  params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                          "filter[vendorNumber]": cred["vendor_number"], "filter[reportDate]": day.isoformat()})
        if r.status_code == 404:
            out.errors.append(f"no report for {day} (not published yet or no sales)")
            continue
        _raise_for(r, "app_store_connect")
        rows = csv.DictReader(io.StringIO(gzip.decompress(r.content).decode()), delimiter="\t")
        total = 0
        for row in rows:
            if (row.get("Currency of Proceeds") or "USD") != "USD":
                skipped_currency += 1
                continue
            total += round(float(row.get("Developer Proceeds") or 0) * 100) * int(float(row.get("Units") or 0))
        if total:
            out.transactions.append(RawTxn(_iso(day), total, f"App Store proceeds {day}", "USD", f"asc:{day}", None, "Apple",
                                           "revenue", "revenue"))
    if skipped_currency:
        out.errors.append(f"{skipped_currency} non-USD report row(s) not converted (no exchange rate source authorized)")
    out.covered_from = _iso(today - timedelta(days=days + 1))
    out.covered_to = _iso(today - timedelta(days=2))
    return out


def fetch(provider: str, credential: str | None, *, since: str | None = None, cursor: str | None = None, upload: bytes | None = None) -> SyncBatch:
    p = PROVIDERS.get(provider)
    if p is None or not p.built:
        raise AdapterError("unavailable", f"{provider} integration is not built yet")
    check_read_only(p)
    if provider == "simulated":
        anchor = json.loads(credential or "{}").get("anchor") or datetime.now(timezone.utc).date().isoformat()
        return simulated_batch(anchor)
    if provider == "csv_upload":
        if upload is None:
            raise AdapterError("bad_input", "upload a CSV file to sync this connection")
        return csv_batch(upload)
    if not credential:
        raise AdapterError("auth", "this connection has no authorized credential")
    if provider == "stripe":
        return stripe_batch(credential, since)
    if provider == "plaid":
        return plaid_batch(credential, cursor)
    if provider == "app_store_connect":
        return app_store_batch(credential)
    raise AdapterError("unavailable", provider)
