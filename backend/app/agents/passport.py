"""Agent Passport (docs/COUNTERSIGN.md part 1).

A passport says "agent X acts for this human, at this company, with these scopes". Countersign signs it
(Ed25519). verify_passport() checks the signature, expiry and revocation, then checks the sponsor live
against Crustdata: the person exists, still works at the company, the domain belongs to that employer,
the claimed title is current, and that title can grant the scope. Anything it can't check is
"unverifiable", and an unverifiable check blocks (fail closed).
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..schemas import Source
from ..verify.profile import Job, company_key, expand_title, load_person, norm, same_company, tokens
from . import ledger
from .graph import Graph
from .models import Check, Passport, Scope, Sponsor, Verdict

REPO_ROOT = Path(__file__).resolve().parents[3]
LOOKUP_TIMEOUT_S = float(os.getenv("PASSPORT_LOOKUP_TIMEOUT_S", "10"))

# ----------------------------------------------------------------------------- keys


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode())


def _issuer_key_path() -> Path:
    return Path(os.getenv("ISSUER_KEY_PATH", REPO_ROOT / "backend" / "data" / "issuer_ed25519.key"))


def issuer_key() -> Ed25519PrivateKey:
    """Countersign's signing key. From ISSUER_PRIVATE_KEY (base64 raw 32 bytes) or a local file created on first use."""
    env = os.getenv("ISSUER_PRIVATE_KEY")
    if env:
        return Ed25519PrivateKey.from_private_bytes(_unb64(env))
    p = _issuer_key_path()
    if p.exists():
        return Ed25519PrivateKey.from_private_bytes(_unb64(p.read_text().strip()))
    key = Ed25519PrivateKey.generate()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_b64(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())))
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return key


def _pub_raw(k: Ed25519PrivateKey) -> bytes:
    return k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def issuer_key_id() -> str:
    return _pub_raw(issuer_key()).hex()[:16]


def issuer_public_key() -> str:
    return _b64(_pub_raw(issuer_key()))


def signing_bytes(p: Passport) -> bytes:
    return ledger.canonical(p.model_dump(exclude={"issuer_signature"})).encode()


# ----------------------------------------------------------------------------- issue / sign


def issue_passport(agent_name: str, role: str, sponsor: Sponsor, scopes: list[Scope], days: int = 30,
                   *, agent_id: str | None = None, now: datetime | None = None, record: bool = True) -> tuple[Passport, bytes]:
    """Returns (passport, agent private key raw bytes). The private key is shown once and never stored here."""
    now = now or datetime.now(timezone.utc)
    agent_key = Ed25519PrivateKey.generate()
    p = Passport(
        agent_id=agent_id or f"agt_{uuid.uuid4().hex[:12]}",
        agent_name=agent_name, role=role, sponsor=sponsor, scopes=list(dict.fromkeys(scopes)),
        issued_at=now.isoformat(timespec="seconds"),
        expires_at=(now + timedelta(days=days)).isoformat(timespec="seconds"),
        public_key=_b64(_pub_raw(agent_key)),
        issuer_key_id=issuer_key_id(),
    )
    p.issuer_signature = _b64(issuer_key().sign(signing_bytes(p)))
    if record:
        ledger.append("passport.issued", {"agent_id": p.agent_id, "passport": p.model_dump(exclude={"issuer_signature"})})
    raw = agent_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return p, raw


def sign_message(passport: Passport, agent_private_key: bytes, body: str) -> str:
    """The agent signs what it sends, binding the message to its passport."""
    key = Ed25519PrivateKey.from_private_bytes(agent_private_key)
    if _b64(_pub_raw(key)) != passport.public_key:
        raise ValueError("private key does not belong to this passport")
    return _b64(key.sign(_message_bytes(passport, body)))


def _message_bytes(passport: Passport, body: str) -> bytes:
    return ledger.canonical({"agent_id": passport.agent_id, "body": body}).encode()


def verify_message_signature(passport: Passport, body: str, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(passport.public_key)).verify(_unb64(signature), _message_bytes(passport, body))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def signature_valid(p: Passport) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(issuer_public_key())).verify(_unb64(p.issuer_signature), signing_bytes(p))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ----------------------------------------------------------------------------- authority rules

# Which current titles may delegate which scope. Matched on expanded title tokens / phrases.
_FOUNDER = (r"\b(founder|co ?founder|cofounder|fondat\w*|fundador\w*|grunder\w*|mitgrunder\w*|chief executive officer|managing director"
            r"|managing partner|general partner|founding partner|business owner|proprietor|proprietaire|geschaftsfuhrer\w*|directeur general"
            r"|president directeur general|pdg|amministratore delegato|prokurist)\b|^owner$|^owner founder$|^founder owner$")
_CXO_FUNCS = ("executive|operating|financial|technology|technical|product|revenue|commercial|business|legal|people|human resources|marketing"
              "|information|strategy|growth|data|security|risk|compliance|investment|digital|medical|scientific|science|accounting|procurement"
              "|customer|sales|engineering|innovation|transformation|administrative|supply chain")
_CXO = rf"\bchief (?:\w+ ){{0,2}}(?:{_CXO_FUNCS})(?: \w+){{0,2}} officer\b"
_FINANCE_LEAD = (r"\b(chief financial officer|chief accounting officer|chief investment officer|financial controller|finance controller"
                 r"|corporate controller|controller|treasurer|comptroller|directeur financier|directeur administratif et financier|daf"
                 r"|director financiero|diretor financeiro|finanzvorstand|finanzleiter\w*|leiter finanzen|kaufmannische\w* leiter\w*)\b"
                 r"|\b(head|director|vice president|manager|lead|officer)( of)? (corporate |fund |group )?(financ\w*|treasury|accounting)\b"
                 r"|\b(financ\w*|treasury) (director|manager|controller|head|lead|officer)\b")
SCOPE_RULES: dict[str, tuple[str, str]] = {
    "outreach.hiring": (_FOUNDER + "|" + _CXO + r"|\b(talent|recruit\w*|hiring|human resources|hr|people (ops|operations|partner)"
                        r"|ressources humaines|recrutement|recruteur|reclutador\w*|personalreferent\w*|vice president|director|head of"
                        r"|engineering manager)\b|\bmanager\b.*\bengineering\b|\bengineering\b.*\bmanager\b",
                        "talent/HR, an engineering manager or above, or a founder"),
    "outreach.sales": (_FOUNDER + "|" + _CXO + r"|\b(sales|business development|growth|revenue|marketing|account executive|account manager"
                       r"|partnerships|gtm|sdr|bdr|customer success|vertrieb|verkauf|vermittler|broker|vice president|director|head of)\b",
                       "sales/BD/marketing, a director or above, or a founder"),
    "data.read": (r".", "any current employee"),
    "contract.sign": (_FOUNDER + "|" + _CXO + r"|\b(vice president|director|head of|general counsel|legal counsel)\b",
                      "a founder, a CXO, a VP, a director/head or legal"),
    "payment.send": (_FOUNDER + "|" + _FINANCE_LEAD, "a founder, the CFO or a finance lead"),
}
MAX_TITLE = 200

# Someone ELSE's title inside this one: "to the CEO", "Office of the CFO", "CFO office", board seats.
_OTHER = r"(?:chief (?:\w+ ){1,4}officer|co founder|founder|managing director|president|chairman|chairwoman|chair|md|vice president)"
_THEIRS = re.compile(rf"\bto (?:the )?{_OTHER}(?: (?:and )?{_OTHER})*|\boffice of (?:the )?{_OTHER}|\b{_OTHER}(?: s)? office\b"
                     r"|\bnon executive director\b|\bboard (?:member|director|advisor|observer|of directors)\b|\bmember (?:of )?(?:the )?board\b")
# These anywhere mean the person works FOR the powerful one, is learning, or the title is a joke: no authority at all.
_ASSISTANT = re.compile(
    r"\b(assistant(?! professor)|asst|assist|assistent\w*|assistente|asistente|assistante|secretar\w*|sekretar\w*|right hand|gofer"
    r"|chief of staff|shadowing|mentee|supporting|working with|seeking|looking for|enthusiast|volunteer|wannabe|in the making"
    r"|intern(?! (?:recruit|hiring|talent|program))\w*|trainee|apprentice|stagiaire|praktikant\w*|werkstudent\w*|in training"
    r"|student(?! (?:recruit|experience|success|affairs|hiring|talent))|graduate (?:\w+ ){0,4}program\w*|first impressions|everything officer"
    r"|of my own life|me inc|society|club|pta)\b")
_AUTH = r"(?:chief (?:\w+ ){1,4}officer|co founder|cofounder|founder|managing director|director|head|vice president|president|owner|partner|treasurer|controller|financ\w*)"
_SUPPORT = re.compile(rf"\b(?:ea|pa|support|coordinator|liaison)\s+(?:(?:to|at|for)\s+)?(?:the\s+)?{_OTHER}|{_OTHER}(?: s)?\s+(?:ea|pa|support|coordinator|liaison)\b")
_PAST = re.compile(rf"\b(?:ex|former|formerly|previously|past|prior|retd|retired|emeritus|honorary|aspiring|future|incoming|outgoing|designate)\s+{_AUTH}"
                   rf"|{_AUTH}\s+(?:emeritus|designate|in training|on leave|acquired|exited)\b|\b(?:19|20)\d\d (?:19|20)\d\d\b")


def clean_title(title: str | None) -> str:
    """NFKC (fullwidth/compat letters), drop zero-width chars and accents, lowercase, expand abbreviations."""
    import unicodedata
    t = unicodedata.normalize("NFKC", title or "")
    t = re.sub(r"[​-‏⁠﻿]", "", t)
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    t = re.sub(r"\bgo[\s-]*to[\s-]*market\b", "gtm", t.lower()).replace("@", " at ")
    t = re.sub(r"\b((?:19|20)\d\d)\s*[-‐-―]\s*(present|now|today|current)\b", " ", t)  # open range = current
    t = re.sub(r"\bex[\s.\-‐-―]+(?=\w)", "ex ", t)
    return expand_title(" ".join(_ROLE_ABBREV.get(w, w) for w in norm(t).split()))


def authority_text(title: str | None, company: str | None = None) -> str | None:
    """The part of a title that speaks for THIS person at THIS company, or None if the title carries no authority."""
    if not title or not title.strip() or len(title) > MAX_TITLE:
        return None
    if re.search(r"'\d\d\s*[-‐-―]\s*'\d\d", title):  # Founder '15-'19
        return None
    t = clean_title(title)
    if _ASSISTANT.search(t) or _SUPPORT.search(t) or _PAST.search(t):
        return None
    t = _THEIRS.sub(" ", t)
    # "ex google" after a real role is a past employer, not a past role: drop it
    t = re.sub(r"\b(?:ex|former|formerly)\s+\w+", " ", t)
    if company:  # "Founder at SideProject" / "CEO of Acme" names a different organisation
        def other_org(m: re.Match) -> str:
            org = m.group(2)
            return m.group(0) if same_company(org, company) or company_key(company).startswith(company_key(org).split(" ")[0] or "~") else " "
        t = re.sub(r"\b(co founder|cofounder|founder|chief executive officer|owner|president|managing director)\s+(?:of|at)\s+((?:\w+ ?){1,3})", other_org, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def is_subordinate(title: str | None) -> bool:
    return bool(title and title.strip()) and authority_text(title) is None


def can_grant(title: str | None, scope: str, company: str | None = None) -> bool:
    """True if this person's own role (not one their title merely names) carries the authority for scope."""
    if not title or not title.strip() or scope not in SCOPE_RULES:
        return False
    if scope == "data.read":
        return True
    t = authority_text(title, company)
    return t is not None and re.search(SCOPE_RULES[scope][0], t) is not None


# ----------------------------------------------------------------------------- verify


def _root(domain: str | None) -> str:
    d = (domain or "").lower().strip().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
    return d


def _domains_match(a: str | None, b: str | None) -> bool:
    ra, rb = _root(a), _root(b)
    return bool(ra and rb) and (ra == rb or ra.endswith("." + rb) or rb.endswith("." + ra))


def _jobs_at(jobs: list[Job], sponsor: Sponsor) -> list[Job]:
    """Jobs at the sponsor's claimed company, best match first: name must match; then the claimed domain, then an exact name."""
    key = company_key(sponsor.company)
    hits = [j for j in jobs if same_company(j.company, sponsor.company) or _same_legal_name(j.company, sponsor.company)
            or (sponsor.company_domain and _domains_match(j.domain, sponsor.company_domain) and _first_word(j.company) == _first_word(sponsor.company))]

    def rank(j: Job) -> tuple:
        return (bool(sponsor.company_domain and _domains_match(j.domain, sponsor.company_domain)),
                company_key(j.company) == key, j.start or date.min)
    return sorted(hits, key=rank, reverse=True)


_LEGAL = re.compile(r"\b(llp|llc|inc|ltd|limited|pvt|private|plc|gmbh|ag|sa|bv|nv|pte|pty|co|corp|corporation|company)\b")


def _same_legal_name(a: str | None, b: str | None) -> bool:
    ka, kb = (re.sub(r"\s+", " ", _LEGAL.sub(" ", norm(x))).strip() for x in (a, b))
    return bool(ka) and ka == kb


def _first_word(name: str | None) -> str:
    w = company_key(name).split()
    return w[0] if w else ""


_STOP = {"of", "and", "the", "at", "for", "in", "a", "i", "ai", "an"}
_ROLE_ABBREV = {
    "ceo": "chief executive officer", "cto": "chief technology officer", "cfo": "chief financial officer",
    "coo": "chief operating officer", "cmo": "chief marketing officer", "cpo": "chief product officer",
    "cio": "chief information officer", "chro": "chief human resources officer", "cro": "chief revenue officer",
    "svp": "senior vice president", "evp": "executive vice president", "avp": "assistant vice president",
    "md": "managing director", "bdm": "business development manager", "hrbp": "hr business partner",
    "cofounder": "co founder", "ta": "talent acquisition",
}


def _stem(w: str) -> str:
    for suf in ("ial", "ing", "ion", "ive", "es", "al", "s", "e"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def title_terms(title: str | None) -> set[str]:
    words = " ".join(_ROLE_ABBREV.get(w, w) for w in norm(title).split())
    return {_stem(w) for w in expand_title(words).split() if w not in _STOP}


_ROLE_SPLIT = re.compile(r"\s+(?:and|&)\s+|\s*[|/;+]\s*|\s+[-\u2013\u2014]\s+", re.I)
_CHIEF = re.compile(r"\bchief\s+((?:[a-z]+\s+(?:and\s+|&\s+)?){1,3}?)officer\b")


def _roles(title: str | None) -> list[set[str]]:
    """'COO and Account Executive' -> two roles, compared one at a time so words can't mix across them.
    'Chief X Officer' becomes one atomic term, so CEO never matches CTO or 'COO, Account Executive'."""
    import unicodedata
    raw = "".join(ch for ch in unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", title or "")) if not unicodedata.combining(ch))
    t = " ".join(_ROLE_ABBREV.get(w, w) for w in re.sub(r"[^a-z0-9&|/;+\-\u2013\u2014 ]+", " ", raw.lower()).split())
    t = _CHIEF.sub(lambda m: "chief_" + "_".join(_stem(w) for w in re.findall(r"[a-z]+", m.group(1)) if w != "and") + "_officer", t)
    out = []
    for part in _ROLE_SPLIT.split(t):
        words = {w if w.startswith("chief_") else _stem(w) for w in expand_title(part.replace("_", "QQ")).replace("qq", "_").split()
                 if w not in _STOP}
        if words:
            out.append(words)
    return out


def title_matches(claimed: str | None, actual: str | None) -> bool:
    """Every role in the claimed title must fit inside one real role, word for word. Understating ("Director" for
    "Senior Director") passes; any extra or different word ("CEO" for "CTO", or for "COO and Account Executive") fails.
    A title identical to the real one always passes."""
    if clean_title(claimed) and clean_title(claimed) == clean_title(actual):
        return True
    if is_subordinate(actual) and not is_subordinate(claimed):  # 'CFO' for 'Executive Assistant to CEO & CFO'
        return False
    c, a = _roles(claimed), _roles(actual)
    # leaving out a rank-changing word isn't understating: "President" for "Vice President", "CFO" for "Former CFO"
    return bool(c and a) and all(any(cr <= ar and (ar & _RANK_WORDS) <= cr for ar in a) for cr in c)


_RANK_WORDS = {"vice", "associat", "assistant", "deputy", "former", "ex", "intern", "internship", "traine", "apprentice",
               "retired", "acting", "to", "offic", "junior", "interim", "fractional", "aspiring", "future", "student",
               "exited", "shadowing", "mentee", "asst", "sub", "board", "non", "volunteer", "honorary", "advisor", "advisory",
               "assoc", "asso", "co", "emeritus", "designate", "incoming", "outgoing", "previously", "past", "prior", "formerly", "retd"}
_RANK_WORDS = {_stem(w) for w in _RANK_WORDS} | _RANK_WORDS


def _src(endpoint: str, field: str | None, url: str | None = None) -> Source:
    return Source(endpoint=endpoint, field=field, url=url)


async def verify_passport(p: Passport, client: Any = None, scope: Scope | None = None, *, today: date | None = None,
                          graph: Graph | None = None, record: bool = True) -> Verdict:
    """Never raises. Every check is pass / fail / unverifiable with a source; allow only if all pass."""
    today = today or datetime.now(timezone.utc).date()
    graph = graph or Graph(client)
    checks: list[Check] = []

    def add(name: str, status: str, detail: str, source: Source | None = None) -> None:
        checks.append(Check(id=f"p{len(checks) + 1}", name=name, status=status, detail=detail, source=source))

    cs = _src("countersign/issuer", f"key {p.issuer_key_id}")
    add("signature_valid", "pass" if signature_valid(p) else "fail",
        "Passport signed by Countersign and unmodified" if signature_valid(p) else "Signature does not match: passport forged or edited", cs)

    try:
        exp = datetime.fromisoformat(p.expires_at).date()
        add("not_expired", "pass" if exp >= today else "fail", f"Expires {exp.isoformat()}", _src("passport", "expires_at"))
    except ValueError:
        add("not_expired", "fail", f"Unreadable expiry {p.expires_at!r}", _src("passport", "expires_at"))

    rev = ledger.is_revoked(p.agent_id)
    add("not_revoked", "fail" if rev else "pass",
        f"Revoked at ledger entry #{rev['seq']}: {(rev.get('payload') or {}).get('reason', 'no reason given')}" if rev else "No revocation on the ledger",
        _src("countersign/ledger", f"seq {rev['seq']}" if rev else None))

    if scope is not None:
        ok = scope in p.scopes
        add("scope_in_passport", "pass" if ok else "fail",
            f"Passport grants {scope}" if ok else f"Passport does not grant {scope} (has: {', '.join(p.scopes) or 'none'})", _src("passport", "scopes"))

    s = p.sponsor
    person = None
    try:
        person = await asyncio.wait_for(graph.person(s.profile_url), LOOKUP_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - fail closed
        add("sponsor_exists", "unverifiable", f"Crustdata lookup failed ({type(e).__name__}); cannot confirm the sponsor", _src("person/enrich", None, s.profile_url))

    if person is None and not any(c.name == "sponsor_exists" for c in checks):
        add("sponsor_exists", "unverifiable" if graph.offline else "fail",
            f"No Crustdata record for {s.profile_url}", _src("person/enrich", None, s.profile_url))

    if person is not None:
        pr = load_person(person)
        name_ok = bool(pr.name) and (norm(pr.name) == norm(s.name) or tokens(pr.name) >= tokens(s.name) or tokens(s.name) >= tokens(pr.name))
        add("sponsor_exists", "pass" if name_ok else "fail",
            f"{pr.name} found in Crustdata" if name_ok else f"Profile belongs to {pr.name!r}, not {s.name!r}",
            _src(pr.endpoint, pr.name_field or "basic_profile.name", s.profile_url))

        at = _jobs_at(pr.current, s)
        past = _jobs_at(pr.past, s)
        cur = at[0] if at else None
        if s.title and at:  # people often hold several roles at one company: check the claim against the one it names
            cur = next((j for j in at if title_matches(s.title, j.title)), cur)
        if cur:
            since = f" since {cur.start.isoformat()}" if cur.start else ""
            add("sponsor_still_employed", "pass", f"Currently {cur.title or 'employed'} at {cur.company}{since}", _src(pr.endpoint, cur.path, s.profile_url))
        elif past:
            last = max(past, key=lambda j: j.end or date.min)
            when = f" on {last.end.isoformat()} ({(today - last.end).days} days ago)" if last.end else ""
            now_at = f"; now at {pr.current[0].company}" if pr.current else ""
            add("sponsor_still_employed", "fail", f"Left {last.company}{when}{now_at}. Their authority ended when they left.",
                _src(pr.endpoint, last.path, s.profile_url))
        else:
            add("sponsor_still_employed", "fail", f"No record of {s.name} working at {s.company}", _src(pr.endpoint, "experience.employment_details", s.profile_url))

        job = cur
        if s.company_domain and job:  # only meaningful for a current employer; a departed sponsor already fails above
            dom_job = next((j for j in at if j.domain), None)
            if dom_job:
                ok = any(_domains_match(j.domain, s.company_domain) for j in at)
                add("domain_matches_company", "pass" if ok else "fail",
                    f"{s.company_domain} is {dom_job.company}'s domain" if ok else f"{s.company_domain} is not {dom_job.company}'s domain ({dom_job.domain})",
                    _src(pr.endpoint, f"{dom_job.path}.employer_company_website_domain", s.profile_url))
            else:
                await _domain_via_identify(graph, s, add)
        if job:
            if s.title:
                ok = title_matches(s.title, job.title)
                others = "; ".join(repr(j.title) for j in at if j.title)
                add("sponsor_title_current", "pass" if ok else "fail",
                    f"Title confirmed: {job.title}" if ok else f"Passport says {s.title!r}; Crustdata says {others or repr(job.title)}",
                    _src(pr.endpoint, f"{job.path}.title", s.profile_url))
            for sc in ([scope] if scope else p.scopes):
                # with no title claimed, any current role at the company that carries the authority counts
                grant = job if s.title else next((j for j in at if can_grant(j.title, sc, s.company)), job)
                ok = can_grant(grant.title, sc, s.company)
                add("sponsor_can_grant_scope", "pass" if ok else "fail",
                    f"{grant.title} can delegate {sc}" if ok else f"{grant.title} cannot delegate {sc} (needs {SCOPE_RULES.get(sc, ('', 'a known scope'))[1]})",
                    _src(pr.endpoint, f"{grant.path}.title", s.profile_url))

    decision = "allow" if checks and all(c.status == "pass" for c in checks) else "block"
    v = Verdict(subject=p.agent_id, decision=decision, checks=checks)
    if record:
        v.ledger_entry = ledger.append(
            "passport.verified",
            {"agent_id": p.agent_id, "scope": scope, "decision": decision, "checks": [c.model_dump(exclude={"source"}) for c in checks]},
            [c.source for c in checks if c.source],
        )
    return v


async def _domain_via_identify(graph: Graph, s: Sponsor, add) -> None:
    try:
        co = await asyncio.wait_for(graph.company_by_domain(s.company_domain), LOOKUP_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001
        add("domain_matches_company", "unverifiable", f"Company Identify failed ({type(e).__name__})", _src("company/identify", None))
        return
    info = (co or {}).get("basic_info") or {}
    if not co:
        add("domain_matches_company", "unverifiable", f"Crustdata has no company for {s.company_domain}", _src("company/identify", "domains"))
        return
    ok = same_company(info.get("name"), s.company)
    add("domain_matches_company", "pass" if ok else "fail",
        f"{s.company_domain} belongs to {info.get('name')}" if ok else f"{s.company_domain} belongs to {info.get('name')}, not {s.company}",
        _src("company/identify", "basic_info.name"))


def revoke(agent_id: str, reason: str, sources: list[Source] | None = None) -> str:
    return ledger.append("passport.revoked", {"agent_id": agent_id, "reason": reason}, sources)


def reinstate(agent_id: str, reason: str = "") -> str:
    return ledger.append("passport.reinstated", {"agent_id": agent_id, "reason": reason})
