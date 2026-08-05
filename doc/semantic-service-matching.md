# Semantic Service Matching

## Overview

[app/services/semantic_matcher.py](../app/services/semantic_matcher.py)
matches free-text package names (typed by customers in WhatsApp booking
forms, or typed by CS staff) to a configured `ServiceType`, handling typos,
size modifiers, and known variant keywords.

Used by:
- `create_booking_from_form()` in `app/app.py` — auto-creating a booking
  from a parsed WhatsApp form (see
  [whatsapp-messaging.md](whatsapp-messaging.md#automatic-booking-creation)).
- The manual booking form on `/bookings`, to suggest/confirm a service from
  a typed package name.

## Matching strategy (`find_best_matching_service`)

1. **Keyword shortcut** — `KEYWORD_SERVICE_MAP` hard-codes well-known
   variant words to a service name, e.g. `gold`/`silver`/`platinum`/
   `graphene`/`ceramic` → `Coating Premium`; `quad`/`gfive`/`g1`/`ppf` →
   `PPF`. If any word in the package name matches, that service is returned
   immediately with a perfect score (`1.0`), and the remaining words become
   the "variant" info.
2. **Modifier stripping** — `extract_core_keywords()` removes size words
   (`small`, `medium`, `large`, `xl`, ...) from the package name so they
   don't dilute the similarity score, keeping them as "modifiers" instead.
3. **Fuzzy + keyword-overlap scoring** — for each active `ServiceType`:
   - `calculate_similarity()` — `difflib.SequenceMatcher` ratio between the
     full package name and the service name (handles typos, e.g.
     `"glasss polish"` ≈ `"Glass Polishing"`).
   - If the core keywords overlap with the service name's words, the score
     is boosted (`0.6 + overlap_ratio * 0.3`) so partial keyword matches
     beat pure fuzzy string similarity.
   - The highest-scoring **active** service wins.
4. A match is only returned if the best score is **≥ 0.5**; otherwise the
   package name is considered unmatched (`None`).

## Public functions

- `match_package_to_service(package_name, services)` → the matched
  `ServiceType` (or `None`).
- `get_variant_info(package_name, services)` → the leftover
  size/quality modifier text (e.g. `"medium gold"` → variant `"medium"` once
  `gold` identifies `Coating Premium`), appended to booking notes so no
  detail from the customer's original message is lost.

## Examples

| Input package text | Matched service | Variant |
|---|---|---|
| `"small gold"` | Coating Premium | `small` |
| `"medium gold coating"` | Coating Premium | `medium coating` |
| `"glasss polish deluxe"` (typo) | Glass Polishing | `deluxe` |
| `"ppf"` | PPF | *(none)* |
| `"xyz random"` | *(no match)* | — |
