"""Deterministic demographic normalization and the identity package's PHI boundary (task 2.1).

Two things live here, and they are the same thing seen from two sides.

**The rules.** Normalization turns a referral's demographics into the composite match key —
last name, DOB, sex, first initial — by a fixed sequence of rules: fold accents, casefold, drop
punctuation, drop name suffixes (`Jr`/`Sr`/`III`), reduce the given name to its first initial,
and parse the DOB from unambiguous formats only. The same input always yields the same composite.
The rules are published as a table with worked examples in `docs/matching.md` and versioned
(`RULES_VERSION`); changing one is a breaking change to the genesis contract, not a patch, because
every `ledger.person_match_keys` row already registered was registered under the old rules
(design — Risks).

**The boundary.** The readable composite is PHI. It is built and hashed in one place
(`_composite` -> `composite_digest`), held in no dataclass, and returned from no public function:
`composite_digest(demographics) -> str` is the only public exit of this module, and the sha256 hex
digest it returns is the only thing the ledger's `[0-9a-f]{64}` check constraint will accept
(design decision 3). `Demographics` is the transient holder that carries PHI in from the envelope;
its `__repr__`/`__str__` redact, so an f-string in a log line or a container repr in a traceback
cannot leak it. Rejections name the offending *field* and a stable rule id — never the value:
`NormalizationError` stores no demographic value at all, so there is nothing in it to echo.

DOB parsing is deliberately narrow. `03/04/1990` is rejected rather than guessed: an all-numeric
day/month pair carries no format contract, and a guessed date silently registers a match key for
a different person. Accepted spellings are the ones that are unambiguous by construction — ISO
`YYYY-MM-DD`, compact `YYYYMMDD`, an alphabetic month name in either order, or a `datetime.date`
that never went through text at all.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass

__all__ = ["RULES_VERSION", "Demographics", "NormalizationError", "composite_digest"]

#: Version of the normalization rule set published in `docs/matching.md`. Every match key
#: registered in the ledger was derived under some version of these rules; bumping this is a
#: breaking change to the genesis contract and requires a re-registration plan (design — Risks).
RULES_VERSION = "v1"

#: Composite field separator. A colon appears in none of the normalized fields (they are
#: `[a-z0-9]` plus the DOB's hyphens), so the composite stays unambiguously splittable and a
#: reviewer can reproduce it by hand from the published table.
_SEPARATOR = ":"

#: R4 — generational suffix tokens dropped from a name. Roman numerals stop at VIII: past that
#: the token is far likelier to be a name than a generation.
_SUFFIXES = frozenset({"jr", "jnr", "sr", "snr", "ii", "iii", "iv", "v", "vi", "vii", "viii", "2nd", "3rd", "4th"})

#: R6 — accepted spellings of sex, mapped to a single canonical character. Anything else is
#: rejected rather than folded into "unknown": a value this module does not recognise is a
#: source-format question for a human, not a match key.
_SEX = {
    "m": "m",
    "male": "m",
    "f": "f",
    "female": "f",
    "o": "o",
    "other": "o",
    "u": "u",
    "unk": "u",
    "unknown": "u",
}

#: R7 — the month spellings that make a date unambiguous by construction. Taken from `calendar`
#: rather than hardcoded so the full and abbreviated names stay in step with each other.
_MONTH_NAMES = frozenset(name.casefold() for name in (*calendar.month_name[1:], *calendar.month_abbr[1:]))

_TOKEN = re.compile(r"[a-z0-9]+")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COMPACT_DATE = re.compile(r"^\d{8}$")
_DAY_FIRST_DATE = re.compile(r"^(\d{1,2}) ([a-z]+) (\d{4})$")
_MONTH_FIRST_DATE = re.compile(r"^([a-z]+) (\d{1,2}) (\d{4})$")


class NormalizationError(ValueError):
    """A demographic field cannot be normalized deterministically.

    Carries the field *name* and a stable rule id and nothing else — no value, no composite. The
    message is safe to log and safe to attach to a rejection: it identifies which field a human
    must look at without reproducing what was in it (design decision 3b).
    """

    def __init__(self, field: str, rule_id: str) -> None:
        super().__init__(f"demographic field {field!r} rejected by rule {rule_id!r}")
        self.field = field
        self.rule_id = rule_id


@dataclass(frozen=True)
class Demographics:
    """The transient PHI holder: raw demographics on their way into `composite_digest`.

    Nothing downstream of this module holds one. `__repr__` and `__str__` redact, so passing an
    instance to a logger, interpolating it into an f-string, or landing it inside a container
    whose repr a traceback renders yields no demographic value (design decision 3).
    """

    last_name: str
    first_name: str
    dob: str | dt.date
    sex: str

    def __repr__(self) -> str:
        return "Demographics(<REDACTED>)"

    __str__ = __repr__


def composite_digest(demographics: Demographics) -> str:
    """Return the sha256 hex digest of the composite match key — the only public exit.

    The readable composite is built and consumed inside this call; it is never returned, stored,
    or logged. The digest matches `[0-9a-f]{64}`, which is what `ledger.person_match_keys`
    enforces and all `register_match_key` will accept.

    Raises `NormalizationError` when a field cannot be normalized deterministically — an
    ambiguous or impossible DOB, an unrecognised sex, or a field that normalizes to nothing.
    """
    return hashlib.sha256(_composite(demographics).encode("utf-8")).hexdigest()


def _composite(demographics: Demographics) -> str:
    """Build the readable composite match key. Module-internal: this string is PHI."""
    last_name = _normalize_name(demographics.last_name, field="last_name")
    first_name = _normalize_name(demographics.first_name, field="first_name")
    return _SEPARATOR.join((
        last_name,
        _normalize_dob(demographics.dob).isoformat(),
        _normalize_sex(demographics.sex),
        first_name[0],
    ))


def _fold(value: str) -> str:
    """R1-R2 — decompose to NFKD, drop combining marks, casefold. `Martínez` -> `martinez`."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _normalize_name(value: str, *, field: str) -> str:
    """R3-R4 — fold, split on punctuation and whitespace, drop suffix tokens, join.

    Guard: a name made up entirely of suffix tokens keeps them. `Sr` as a surname is unlikely,
    but silently normalizing it to the empty string would collapse two different people onto one
    composite, and that is the failure this package exists to prevent.
    """
    tokens = _TOKEN.findall(_fold(value))
    if not tokens:
        raise NormalizationError(field, "missing_field")
    kept = [token for token in tokens if token not in _SUFFIXES]
    return "".join(kept or tokens)


def _normalize_sex(value: str) -> str:
    """R6 — map an accepted spelling of sex to its canonical character."""
    folded = "".join(_TOKEN.findall(_fold(value)))
    if not folded:
        raise NormalizationError("sex", "missing_field")
    try:
        return _SEX[folded]
    except KeyError:
        raise NormalizationError("sex", "unknown_sex") from None


def _normalize_dob(value: str | dt.date) -> dt.date:
    """R7 — parse the DOB from unambiguous formats only.

    `ambiguous_dob` means the *shape* carries no format contract (`03/04/1990` — is that March 4
    or 4 March?) or is not a date at all. `invalid_dob` means the shape was accepted but the day
    it names does not exist (`1990-02-30`). Neither error carries the value.
    """
    if isinstance(value, dt.datetime):
        # `datetime` is a `date` subclass, so it satisfies the annotation. Drop the time part
        # rather than let it into `isoformat()` and split one person across two composites.
        return value.date()
    if isinstance(value, dt.date):
        return value

    iso = value.strip()
    if _ISO_DATE.match(iso):
        return _parse(iso, "%Y-%m-%d")
    if _COMPACT_DATE.match(iso):
        return _parse(iso, "%Y%m%d")
    return _parse_month_name(_fold(" ".join(iso.replace(",", " ").replace("-", " ").split())))


def _parse(text: str, fmt: str) -> dt.date:
    try:
        return dt.datetime.strptime(text, fmt).date()
    except ValueError:
        raise NormalizationError("dob", "invalid_dob") from None


def _parse_month_name(text: str) -> dt.date:
    """Accept `4 Mar 1990` / `March 4, 1990` and their spelling variants, in either order.

    The shape is settled before the parse, so the two rejections stay distinguishable: a
    recognised month name with a day the calendar does not have is `invalid_dob`, and anything
    that never had a month name in it was `ambiguous_dob` all along.
    """
    day_first = _DAY_FIRST_DATE.match(text)
    month_first = _MONTH_FIRST_DATE.match(text)
    if day_first:
        day, month, year = day_first.groups()
    elif month_first:
        month, day, year = month_first.groups()
    else:
        raise NormalizationError("dob", "ambiguous_dob")
    if month not in _MONTH_NAMES:
        raise NormalizationError("dob", "ambiguous_dob")
    return _parse(f"{int(day):02d} {month} {year}", "%d %B %Y" if len(month) > 3 else "%d %b %Y")
