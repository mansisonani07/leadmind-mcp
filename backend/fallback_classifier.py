"""
Rule-based fallback classifier.

Used when:
  - GROQ_API_KEY is not configured (zero-config local dev)
  - Groq returns 429 (free-tier rate limit hit)
  - Groq times out or errors

Design goals:
  - **Explainable** — every decision returns a human-readable reasoning string.
  - **Negation-aware** — "not ready to buy" must NOT match the hot keyword
    "ready to buy". We use per-keyword negative-lookbehind regex matching
    instead of blunt substring matching.
  - **Weighted** — strong signals (e.g. "urgent", "asap", "no rush", "just
    browsing") count for 2 points; weak signals count for 1. This prevents
    a single weak warm signal ("interested") from overriding a strong cold
    signal ("no rush").
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Lexicons — each entry is (keyword, weight). Weight 2 = strong signal.
# ---------------------------------------------------------------------------

HOT_KEYWORDS: List[Tuple[str, int]] = [
    # Urgency / timing (strong)
    ("urgent", 2), ("urgently", 2), ("asap", 2), ("immediately", 2),
    ("right away", 2), ("today", 2), ("tomorrow", 2),
    ("this week", 2), ("this quarter", 2),
    ("deadline", 2), ("by friday", 2), ("by monday", 2),
    # Budget / decision readiness (strong)
    ("budget approved", 2), ("budget allocated", 2), ("have budget", 2),
    ("approved budget", 2), ("ready to buy", 2), ("ready to sign", 2),
    ("ready to move", 2), ("ready to move forward", 2),
    ("decision maker", 2), ("decision-maker", 2),
    # Action-oriented (mixed weight)
    ("purchase", 2), ("contract", 2), ("sign the contract", 2),
    ("call me", 2), ("let's talk", 2),
    ("quote", 1), ("proposal", 1),
    # Growth signals (strong)
    ("growing fast", 2), ("expanding", 1), ("hiring", 1),
    ("fund", 1), ("funding", 1), ("investment", 1),
    ("approve", 1), ("approved", 1),
    ("serious", 1),
]

WARM_KEYWORDS: List[Tuple[str, int]] = [
    # Evaluation / exploration
    ("evaluating", 1), ("evaluate", 1), ("considering", 1),
    ("review", 1), ("reviewing", 1),
    ("explore", 1), ("exploring", 1),
    ("compare", 1), ("comparing", 1),
    ("learn more", 1), ("more information", 1),
    # Timing — deferred but not distant
    ("next month", 1), ("next quarter", 1),
    ("call next week", 1), ("discuss next week", 1),
    ("schedule a call", 1), ("schedule a meeting", 1),
    ("let's discuss", 1),
    # Pricing inquiry (no urgency)
    ("pricing", 1), ("pricing for", 1),
    # Soft intent
    ("demo", 1), ("demo request", 1),
    ("case study", 1), ("follow up", 1),
    ("questions about", 1), ("questions regarding", 1),
    ("team meeting", 1),
]

COLD_KEYWORDS: List[Tuple[str, int]] = [
    # Passive / browsing (strong)
    ("just browsing", 2), ("just looking", 2),
    ("no rush", 2), ("no immediate", 2), ("no plans", 2),
    ("no budget", 2),
    # Distant timing (strong)
    ("in a year", 2), ("next year", 2), ("in 6 months", 2),
    ("in a few months", 2), ("in a month", 2),
    ("few months", 1), ("reach out in", 1),
    # Research-only (strong)
    ("just doing research", 2), ("just researching", 2),
    ("gathering info", 2), ("just gathering", 2),
    ("for now", 1),
    # Passive intent (weak)
    ("curious", 1), ("research", 1), ("researching", 1),
    ("newsletter", 1), ("subscribe", 1), ("subscribed", 1),
    ("just starting", 1), ("small team", 1),
    ("thinking about", 1), ("maybe", 1),
    ("future", 1), ("later", 1), ("not now", 1),
    # Explicit disinterest / opt-out (strong) — BUG 1 fix
    ("not interested", 2),
    ("no longer interested", 2),
    ("remove me from", 2),
    ("unsubscribe", 2),
    ("no thanks", 2),
    ("pass for now", 2),
    ("not looking for", 2),
    ("don't need", 2),
    ("no longer need", 2),
]


# ---------------------------------------------------------------------------
# Sentence-level negation phrases — BUG 2 fix
# ---------------------------------------------------------------------------
# If ANY of these phrases appears ANYWHERE in the message, we suppress ALL
# HOT keyword matches for the entire message. This handles cases where the
# negation is too far from the HOT keyword for the per-keyword lookback to
# catch it (e.g. "We are not ready to buy anything this quarter" — "not
# ready to buy" is at char 7, "this quarter" at char 36, ~30 chars apart).
#
# These are checked before scoring; if matched, hot_score is forced to 0.
_SENTENCE_NEGATIONS = [
    "not ready to buy",
    "not interested",
    "no longer",
    "don't need",
]


# ---------------------------------------------------------------------------
# Negation detection
# ---------------------------------------------------------------------------

# Words that, when they appear within ~3 words before a HOT or WARM keyword,
# negate that keyword. We do NOT include "no" here because "no" is itself
# part of legitimate COLD phrases like "no rush", "no plans", "no budget".
_NEGATION_WORDS = r"not|don't|doesn't|isn't|aren't|won't|can't|cannot|without|never|n't"

# Match a negation word followed by 0-3 intermediate words.
_NEGATION_PREFIX = re.compile(
    rf"\b(?:{_NEGATION_WORDS})(?:\s+\w+){{0,3}}\s*$",
    re.IGNORECASE,
)


def _keyword_is_negated(text_lower: str, kw_start: int) -> bool:
    """Look back up to 60 chars before the keyword start for a negation word
    followed by 0-3 filler words. If found, the keyword is negated.

    Widened from 30 → 60 chars (BUG 2 fix) so that negations like
    "not ready to buy" correctly suppress later HOT keywords such as
    "this quarter" that sit ~30 chars away in the same sentence.
    """
    lookback = text_lower[max(0, kw_start - 60):kw_start]
    return bool(_NEGATION_PREFIX.search(lookback))


def _score_keyword_list(text_lower: str, keywords: List[Tuple[str, int]],
                        check_negation: bool) -> Tuple[int, List[str]]:
    """Return (total_score, matched_keywords). For HOT/WARM we honor negation;
    for COLD we do not (cold keywords like 'no rush' contain 'no' themselves)."""
    score = 0
    matched: List[str] = []
    for kw, weight in keywords:
        # Find all occurrences; word-boundary aware so "ready" doesn't match "already"
        pattern = r"\b" + re.escape(kw) + r"\b"
        for m in re.finditer(pattern, text_lower):
            if check_negation and _keyword_is_negated(text_lower, m.start()):
                continue  # this occurrence is negated
            score += weight
            if kw not in matched:
                matched.append(kw)
            break  # only count each keyword once
    return score, matched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(text: str) -> Dict[str, object]:
    """
    Classify a lead message into Hot / Warm / Cold.

    Returns:
        {
            "status":      "Hot" | "Warm" | "Cold",
            "confidence":  float in [0.0, 1.0],
            "reasoning":   short human-readable explanation,
            "keywords":    list of matched keywords (for debugging),
            "source":      "fallback"
        }
    """
    if not text or not text.strip():
        return {
            "status": "Warm",
            "confidence": 0.30,
            "reasoning": "Empty message — no signals detected; defaulting to Warm for follow-up.",
            "keywords": [],
            "source": "fallback",
        }

    text_lower = text.lower()

    hot_score, hot_matched = _score_keyword_list(text_lower, HOT_KEYWORDS, check_negation=True)
    warm_score, warm_matched = _score_keyword_list(text_lower, WARM_KEYWORDS, check_negation=True)
    cold_score, cold_matched = _score_keyword_list(text_lower, COLD_KEYWORDS, check_negation=False)

    # BUG 2 fix — sentence-level negation: if any of the explicit
    # disinterest phrases appears ANYWHERE in the message, suppress ALL
    # HOT keyword matches for the entire message. This catches negations
    # that are too far from the HOT keyword for the per-keyword 60-char
    # lookback (e.g. "We are not ready to buy anything this quarter").
    sentence_negation_hit = next(
        (phrase for phrase in _SENTENCE_NEGATIONS if phrase in text_lower),
        None,
    )
    if sentence_negation_hit:
        hot_score = 0
        hot_matched = []

    scores = {"Hot": hot_score, "Warm": warm_score, "Cold": cold_score}
    max_score = max(scores.values())

    if max_score == 0:
        return {
            "status": "Warm",
            "confidence": 0.40,
            "reasoning": "No strong buying-intent keywords detected; defaulting to Warm for follow-up.",
            "keywords": [],
            "source": "fallback",
        }

    # Pick the bucket with the highest weighted score.
    # Tie-break order (BUG 2 fix): Cold > Warm > Hot.
    # A false Cold costs one extra follow-up touch (recoverable); a false Hot
    # wastes sales-rep time on a dead lead (expensive). When Hot and Cold tie,
    # prefer Cold. When Warm ties with either, prefer the more conservative
    # option (Cold over Warm, Warm over Hot).
    if cold_score == max_score and cold_score >= hot_score and cold_score >= warm_score:
        status = "Cold"
        confidence = min(0.55 + 0.05 * cold_score, 0.88)
        top_kw = cold_matched[:4] if cold_matched else ["passive/deferred language"]
        reasoning = (
            f"Cold because passive/deferred signals detected "
            f"({', '.join(top_kw)}; score={cold_score}) — long-term nurture, not active sales time."
        )
        if sentence_negation_hit:
            reasoning = (
                f"Cold because explicit disinterest phrase detected "
                f"(\"{sentence_negation_hit}\"); HOT signals suppressed. "
                f"Cold signals: {', '.join(top_kw) if cold_matched else 'none'} (score={cold_score})."
            )
    elif warm_score == max_score and warm_score >= hot_score:
        status = "Warm"
        confidence = min(0.50 + 0.05 * warm_score, 0.80)
        top_kw = warm_matched[:4] if warm_matched else ["exploring language"]
        reasoning = (
            f"Warm because evaluation/exploration signals detected "
            f"({', '.join(top_kw)}; score={warm_score}) but no urgent commitment language."
        )
    else:
        status = "Hot"
        confidence = min(0.55 + 0.05 * hot_score, 0.92)
        top_kw = hot_matched[:4] if hot_matched else ["budget/timing/decision language"]
        reasoning = (
            f"Hot because strong buying-intent signals detected "
            f"({', '.join(top_kw)}; score={hot_score}) — prioritize outreach."
        )

    return {
        "status": status,
        "confidence": round(confidence, 2),
        "reasoning": reasoning,
        "keywords": {"Hot": hot_matched, "Warm": warm_matched, "Cold": cold_matched}[status],
        "source": "fallback",
    }


def suggest_next_action(lead: dict, history: list) -> Dict[str, str]:
    """Rule-based next-action suggestion. Used when Groq is unavailable."""
    status = (lead or {}).get("status", "Warm")
    name = (lead or {}).get("name", "the lead")
    last_events = [h for h in (history or []) if h.get("event_type") == "status_change"]
    recent_change = last_events[-1] if last_events else None

    if status == "Hot":
        return {
            "suggestion": (
                f"Call {name} within 24 hours — hot leads decay fast. Confirm budget, "
                "decision timeline, and decision-maker; then send a tailored proposal "
                "within 48 hours."
            ),
            "source": "fallback",
        }
    if status == "Warm":
        if recent_change:
            return {
                "suggestion": (
                    f"Send {name} a relevant case study this week, then follow up with "
                    "a 20-minute discovery call invite. Reference their recent interest signal."
                ),
                "source": "fallback",
            }
        return {
            "suggestion": (
                f"Add {name} to a 3-touch nurture sequence: case study (day 0), "
                "industry insight (day 4), discovery call invite (day 7)."
            ),
            "source": "fallback",
        }
    if status == "Cold":
        return {
            "suggestion": (
                f"Add {name} to the monthly newsletter and re-engage in 30 days with "
                "new content. Do not allocate sales-rep time yet."
            ),
            "source": "fallback",
        }
    if status == "Converted":
        return {
            "suggestion": (
                f"Send {name} an onboarding welcome email, schedule a kickoff call "
                "within 5 business days, and add them to the customer success queue."
            ),
            "source": "fallback",
        }
    if status == "Lost":
        return {
            "suggestion": (
                f"Mark {name} for re-engagement in 90 days. Log loss reason if not already recorded."
            ),
            "source": "fallback",
        }
    return {
        "suggestion": f"Review {name}'s record and decide on next step manually.",
        "source": "fallback",
    }
