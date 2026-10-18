import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Acme Appliances Ledger Agent", version="1.0.0")

EMAIL = "24f3002203@ds.study.iitm.ac.in"
QUIZ_SIGN = os.getenv(
    "QUIZ_SIGN",
    "UG3410K1awo4b3jbzjwE9KWjaz4d0KP8rtrwwJrQ4+nlnQ2yAH69cwsIqog79xzC2945yuMyeri5UEujIj7M3ALweXhr36Pbj7U2WSKTMpAFbFLlQyDt1ukuHykcrqSCDQME4Wq7AB1P2SUXL4EjRvZ+yFIHn/0E5QHnIz3szrAOJo0SvyZE8Zwi43Jp3kJgw1VqrP68QmA+EvZvnpeCDh44CG/E+olVrMvxOerstfvDoL/vxek2ikw05X8jSBHi/Up42hLxM3VEKJmyGmvCN9SYUI8HViOS+O0x2wENe02/28v8rcv9dvV1M3t0fYem2uFb0nZTuH4bFrGwt0EoeA==",
)
QUESTION_DATA_URL = (
    "https://exam.sanand.workers.dev/questionData"
    f"?email={EMAIL.replace('@', '%40')}"
    f"&quizSign={requests.utils.quote(QUIZ_SIGN, safe='')}"
    "&questionId=q-ledger-agent-server&path=%2F"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "AcmeLedgerAgent/1.0", "Accept": "application/json"})
CACHE: dict[str, Any] = {"expires": 0, "data": None}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def get_json(url: str, timeout: float = 4.0) -> Any:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return r.text


def extract_urls(obj: Any, base_url: str) -> list[str]:
    found = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and (k.lower() in {
                    "href", "url", "endpoint", "next", "api", "openapi", "swagger",
                    "schema", "orders", "customers", "products", "refunds", "ledger"
                } or v.startswith("/")):
                    if v.startswith(("http://", "https://", "/")):
                        u = urljoin(base_url, v)
                        if u.startswith(("http://", "https://")):
                            found.append(u)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return list(dict.fromkeys(found))


def load_discovered_data() -> Any:
    now = time.time()
    if CACHE["data"] is not None and now < CACHE["expires"]:
        return CACHE["data"]

    # The exam URL is the entry point. Its response describes the API and/or
    # exposes the root resource; follow advertised links instead of guessing routes.
    root = get_json(QUESTION_DATA_URL, timeout=6)
    all_docs: list[tuple[str, Any]] = [(QUESTION_DATA_URL, root)]
    visited = {QUESTION_DATA_URL}
    queue = extract_urls(root, QUESTION_DATA_URL)
    # Crawl a small API surface with strict bounds so calls remain fast.
    while queue and len(all_docs) < 35:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            doc = get_json(url, timeout=2.0)
        except Exception:
            continue
        all_docs.append((url, doc))
        # Follow links exposed by API responses, not arbitrary external links.
        for nxt in extract_urls(doc, url):
            if nxt.startswith("https://exam.sanand.workers.dev") and nxt not in visited:
                queue.append(nxt)

    CACHE["data"] = all_docs
    CACHE["expires"] = now + 45
    return all_docs


def normalize_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", k.lower())


def flatten_records(obj: Any, source: str = "") -> list[dict]:
    """Extract row-like records from JSON responses while retaining source endpoint."""
    out = []
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts and any(any(isinstance(v, (str, int, float, bool)) or v is None for v in x.values()) for x in dicts):
            out.extend({**x, "__source": source} for x in dicts)
        else:
            for x in obj:
                out.extend(flatten_records(x, source))
    elif isinstance(obj, dict):
        # A dictionary with scalar fields is itself a record if it looks row-like.
        scalar_count = sum(not isinstance(v, (dict, list)) for v in obj.values())
        if scalar_count >= 3 and any(normalize_key(k) in {
            "orderid", "customerid", "product", "productname", "amount", "revenue",
            "refund", "refundamount", "region", "date", "orderdate", "status"
        } for k in obj):
            out.append({**obj, "__source": source})
        for k, v in obj.items():
            if isinstance(v, (list, dict)):
                out.extend(flatten_records(v, source))
    return out


def records_from_docs(docs: list[tuple[str, Any]]) -> list[dict]:
    records = []
    seen = set()
    for url, obj in docs:
        for row in flatten_records(obj, url):
            signature = json.dumps({k: v for k, v in row.items() if k != "__source"}, sort_keys=True, default=str)
            if signature not in seen:
                seen.add(signature)
                records.append(row)
    return records


def key_value(row: dict, *names: str):
    wanted = {normalize_key(n) for n in names}
    for k, v in row.items():
        if normalize_key(k) in wanted:
            return v
    return None


def to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("USD", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def parse_date(value: Any) -> date | None:
    if isinstance(value, (int, float)):
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s[:26], fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None


def money_fields(row: dict) -> dict[str, float]:
    result = {}
    for k, v in row.items():
        n = to_number(v)
        if n is not None and any(w in normalize_key(k) for w in ("revenue", "amount", "total", "price", "refund", "sales", "subtotal")):
            result[k] = n
    return result


def answer_question(question: str, docs: list[tuple[str, Any]]) -> Any:
    q = question.lower()
    rows = records_from_docs(docs)

    # If the API provides an explicit natural-language/query endpoint or usage
    # guide, expose it in errors rather than fabricating an answer.
    if not rows:
        snippets = []
        for url, obj in docs[:8]:
            snippets.append({"url": url, "response": obj})
        raise HTTPException(502, detail={"message": "Could not identify ledger records from the API responses", "discovery": snippets})

    # Choose the likely row family for the question.
    if "refund" in q:
        family = [r for r in rows if any(w in (r.get("__source", "") + " " + " ".join(r.keys())).lower() for w in ("refund",))]
        if family:
            rows = family
    elif "customer" in q or "who" in q:
        family = [r for r in rows if any("customer" in normalize_key(k) for k in r)]
        if family:
            rows = family
    elif "product" in q or "which" in q:
        family = [r for r in rows if any("product" in normalize_key(k) for k in r)]
        if family:
            rows = family
    else:
        family = [r for r in rows if any(any(w in normalize_key(k) for w in ("orderid", "orderdate", "revenue", "amount", "total")) for k in r)]
        if family:
            rows = family

    # Apply region filters.
    regions = ("north", "south", "east", "west", "central")
    region = next((r for r in regions if re.search(rf"\b{r}\b", q)), None)
    if region:
        rows = [r for r in rows if any(isinstance(v, str) and v.strip().lower() == region
                                       for k, v in r.items() if "region" in normalize_key(k))]

    # Apply product filter if a product name occurs in the question.
    product_values = set()
    for row in rows:
        for k, v in row.items():
            if "product" in normalize_key(k) and isinstance(v, str):
                product_values.add(v)
    product_filter = next((p for p in product_values if p.lower() in q), None)
    if product_filter:
        rows = [r for r in rows if any(isinstance(v, str) and v.lower() == product_filter.lower()
                                       for k, v in r.items() if "product" in normalize_key(k))]

    # Apply month/year from question.
    months = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
        "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12
    }
    month = next((n for name, n in months.items() if re.search(rf"\b{name}\b", q)), None)
    year_match = re.search(r"\b(20\d{2})\b", q)
    year = int(year_match.group(1)) if year_match else None
    if month or year:
        dated = []
        for row in rows:
            d = None
            for k, v in row.items():
                if any(w in normalize_key(k) for w in ("date", "createdat", "orderdate", "refunddate", "timestamp")):
                    d = parse_date(v)
                    if d:
                        break
            if d and (month is None or d.month == month) and (year is None or d.year == year):
                dated.append(row)
        rows = dated

    # Identify an explicit amount/revenue field; don't silently add unit prices.
    metric_words = []
    if "refund" in q:
        metric_words = ["refundamount", "refund", "amount"]
    elif "revenue" in q or "sales" in q:
        metric_words = ["revenue", "sales", "totalamount", "amount", "total"]
    elif "average" in q or "avg" in q:
        metric_words = ["revenue", "amount", "total", "price"]
    else:
        metric_words = ["amount", "revenue", "total", "refundamount", "price"]

    if any(w in q for w in ("how many", "count", "number of orders", "number of customers")):
        return len(rows)

    candidates = []
    for row in rows:
        for k, v in row.items():
            nk = normalize_key(k)
            if any(w in nk for w in metric_words):
                n = to_number(v)
                if n is not None:
                    candidates.append((row, k, n))
    # Prefer the most semantically relevant field.
    if candidates:
        def score(item):
            nk = normalize_key(item[1])
            return max((len(w) for w in metric_words if w in nk), default=0)
        best_score = max(score(x) for x in candidates)
        chosen = [x for x in candidates if score(x) == best_score]
        if "average" in q or "avg" in q:
            return round(sum(x[2] for x in chosen) / len(chosen), 2) if chosen else 0
        if "max" in q or "highest" in q or "largest" in q:
            return round(max(x[2] for x in chosen), 2)
        if "min" in q or "lowest" in q or "smallest" in q:
            return round(min(x[2] for x in chosen), 2)
        if any(w in q for w in ("total", "sum", "overall", "revenue", "sales", "refund")):
            return round(sum(x[2] for x in chosen), 2)

    # For product/customer questions, return the matching rows with internal metadata removed.
    cleaned = []
    for row in rows:
        cleaned.append({k: v for k, v in row.items() if not k.startswith("__")})
    if cleaned:
        # Keep responses compact and JSON serializable.
        return cleaned[:100]
    return 0


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/")
@app.post("/ask")
def ask(body: AskRequest):
    try:
        docs = load_discovered_data()
        answer = answer_question(body.question, docs)
        return {"answer": answer}
    except HTTPException:
        raise
    except requests.RequestException as e:
        raise HTTPException(502, detail=f"Could not fetch the Acme API: {str(e)}")
    except Exception as e:
        raise HTTPException(500, detail=f"Query failed: {str(e)}")
