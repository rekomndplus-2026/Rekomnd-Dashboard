"""
Real Estate Buyer Lead Classifier
Scores incoming messages by matching keywords.
Supports both English and Arabic keywords.
Any keyword match = lead saved.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Keyword Definitions (weight, keywords)
# ─────────────────────────────────────────────

# Each entry: (weight, [keywords...])
# Weight determines hot/warm tier when multiple keywords match
KEYWORD_GROUPS = [
    # ── Direct purchase intent (strongest signal) ──
    (5, [
        "مطلوب للشراء", "مطلوب شراء", "مطلوب تاون هاوس", "مطلوب توين هاوس",
        "مطلوب دوبلكس", "مطلوب بنتهاوس", "مطلوب استوديو", "مطلوب شاليه", "مطلوب عقار",
        "أرغب في الشراء", "أريد الشراء", "اريد الشراء", "راغب في الشراء",
        "يرغب في الشراء", "مهتم بالشراء", "أنوي الشراء",
        "ناوي أشتري", "بفكر أشتري", "جاهز للشراء",
        "طلب شراء", "طلبات شراء",
        "عايز أشتري", "عايزة أشتري", "عاوز أشتري", "عاوزه أشتري",
        "محتاج أشتري", "محتاجة أشتري",
        "حابب أشتري", "حابة أشتري",
        "هشتري", "هنشتري",
        "looking to buy", "want to buy", "want to purchase", "need to buy",
        "interested in buying", "buy property", "buy apartment", "buy villa",
        "buy house", "purchase property",
        "WTB",
    ]),

    # ── Search / looking intent ──
    (4, [
        "مطلوب شقة", "مطلوب فيلا", "مطلوب أرض", "مطلوب محل", "مطلوب مكتب",
        "مطلوب وحدة", "مطلوب وحدة سكنية", "مطلوب وحدة تجارية",
        "أبحث عن", "ابحث عن", "بحث عن",
        "أبحث عن شقة", "أبحث عن فيلا", "أبحث عن أرض", "أبحث عن محل",
        "أبحث عن مكتب", "أبحث عن وحدة", "أبحث عن شاليه", "أبحث عن دوبلكس",
        "أبحث عن بنتهاوس", "أبحث عن عقار", "أبحث عن بيت", "أبحث عن منزل",
        "ابحث عن شقة", "ابحث عن فيلا", "ابحث عن عقار", "ابحث عن أرض",
        "ابحث عن محل",
        "بدور على", "بدوّر على", "أدور على",
        "بدور على شقة", "بدور على فيلا", "بدور على أرض", "بدور على محل",
        "بدور على مكتب", "بدور على عقار", "بدور على بيت", "بدور على منزل",
        "Looking For", "LFB", "ISO",
        "looking for", "looking for apartment", "looking for flat",
        "looking for villa", "looking for property", "looking for house",
        "looking for home", "looking for land", "looking for office",
        "looking for shop", "looking for chalet", "looking for duplex",
        "looking for townhouse",
        "searching for", "searching for apartment", "searching for flat",
        "searching for villa", "searching for property", "searching for house",
        "searching for land",
    ]),

    # ── Direct property need / colloquial ──
    (3, [
        "عايز شقة", "عايزة شقة", "محتاج شقة", "محتاجة شقة",
        "عايز فيلا", "عايزة فيلا", "محتاج فيلا", "محتاجة فيلا",
        "عايز أرض", "عايزة أرض", "محتاج أرض", "محتاجة أرض",
        "عايز محل", "عايزة محل", "محتاج محل", "محتاجة محل",
        "عايز مكتب", "عايزة مكتب", "محتاج مكتب", "محتاجة مكتب",
        "عايز شاليه", "عايزة شاليه", "محتاج شاليه", "محتاجة شاليه",
        "عايز دوبلكس", "عايز بنتهاوس", "عايز تاون هاوس", "عايز توين هاوس",
        "هجيب شقة", "هجيب فيلا",
        "عايز أجيب شقة", "عايزة أجيب شقة",
        "حابب أجيب", "حابه أجيب",
        "need apartment", "need flat", "need villa", "need property",
        "need house", "need land",
        "wanted", "want property", "require", "in need of",
        "Wanted", "Need", "LF",
    ]),

    # ── General intent words ──
    (2, [
        "مطلوب", "عايز", "عايزة", "عاوز", "عاوزه",
        "محتاج", "محتاجة", "نفسي", "نفسي في",
        "هل يوجد شقة", "هل يوجد فيلا", "هل يوجد أرض",
        "هل يوجد", "هل في", "هل فيه", "فيه",
        "في حد عنده", "حد عنده", "حد يعرف", "مين عنده",
        "من عنده", "من لديهم", "من لديك", "أي حد", "لو حد",
        "ممكن حد", "ممكن ألاقي", "حد يرشح",
        "ترشيحات", "ترشيح شقة", "ترشيح كمبوند",
        "أفضل مشروع", "أفضل كمبوند", "أفضل مكان",
        "أنسب مشروع", "أنسب كمبوند",
        "إيه الأفضل", "أيه الأفضل", "محتار بين",
        "حد عنده شقة للبيع", "حد عنده فيلا للبيع",
        "مين عنده شقة للبيع", "هل فيه شقة للبيع", "هل فيه فيلا للبيع",
        "ممكن",
        "شقة", "فيلا", "أرض", "عقار", "محل", "مكتب",
        "شاليه", "دوبلكس", "بنتهاوس", "تاون هاوس", "توين هاوس",
        "استوديو", "وحدة", "بيت", "منزل", "عمارة", "مبنى",
        "شقه", "فيلاا", "ارض", "عقارر",
    ]),

    # ── Contact / reach-out signals ──
    (2, [
        "للتواصل", "يرجى التواصل", "أرجو التواصل", "تواصل معي",
        "كلمني", "كلموني", "ابعتلي", "ابعتولي",
        "راسلني", "راسلوني", "خاص",
        "Inbox", "DM",
    ]),

    # ── Additional colloquial ──
    (1, [
        "بدور", "بدوّر", "بدورلي", "بدور ليا", "أدور على",
        "بدورر", "بدور علي", "بدور ع",
        "ابحت", "ابحس",
        "اريد", "أريد", "نريد",
    ]),

    # ── English property-specific ──
    (3, [
        "apartment", "villa", "studio", "penthouse", "townhouse", "duplex",
        "chalet", "land", "plot", "unit", "property", "compound",
        "real estate", "for sale",
    ]),

    # ── Financial / budget signals (bonus when combined with above) ──
    (1, [
        "million", "thousand", "budget", "price range",
        "egp", "usd", "aed", "sar", "kwd",
        "cash", "installment", "down payment", "mortgage",
        "مليون", "الف", "ألف", "ميزانية", "سعر", "دفع", "قسط", "مقدم",
        "كاش", "نقد",
    ]),
]

# Minimum score to be classified as a lead (1 = any keyword match)
DEFAULT_THRESHOLD = 1


# ─────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────

@dataclass
class ClassificationResult:
    """Result of classifying a single message."""
    is_lead: bool
    score: int
    matched_keywords: list[str] = field(default_factory=list)
    lead_tier: str = "none"  # "none" | "warm" | "hot"


# ─────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────

def classify_message(
    message: str,
    threshold: int = DEFAULT_THRESHOLD,
) -> ClassificationResult:
    """
    Score a WhatsApp group message for real estate buyer intent.

    Args:
        message: The raw message text.
        threshold: Minimum score to be considered a lead.

    Returns:
        ClassificationResult with score and matched keywords.
    """
    if not message or not message.strip():
        return ClassificationResult(is_lead=False, score=0)

    text = message.lower().strip()
    total_score = 0
    matched: list[str] = []

    for weight, keywords in KEYWORD_GROUPS:
        for kw in keywords:
            pattern = re.compile(re.escape(kw.lower()), re.IGNORECASE | re.UNICODE)
            if pattern.search(text):
                total_score += weight
                matched.append(kw)
                # Only count each keyword group once (first match wins)
                break

    is_lead = total_score >= threshold

    # Determine tier
    tier = "none"
    if is_lead:
        tier = "hot" if total_score >= 5 else "warm"

    logger.debug(
        f"[LeadClassifier] score={total_score}, tier={tier}, "
        f"matched={matched[:5]}, message='{message[:80]}'"
    )

    return ClassificationResult(
        is_lead=is_lead,
        score=total_score,
        matched_keywords=matched,
        lead_tier=tier,
    )
