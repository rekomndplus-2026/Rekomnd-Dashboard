"""
Buyer Detection Engine — ENHANCED
===================================
Detects buyer posts and extracts EVERY available data point:
- Phone numbers (mobile + WhatsApp)
- Buyer name (from text patterns)
- Lead score (0-100, weighted)
- Budget range (min + max)
- Payment method (cash/installments/mortgage)
- Urgency level (urgent/flexible/unknown)
- Delivery preference (immediate/within_year/future)
- Compound/developer preference
- Finishing level preference
- All property details (type, area, rooms, floor, furnished)
- All location details (area, governorate)
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  BUYER SIGNAL KEYWORDS
# ─────────────────────────────────────────────────────────────────────────────

STRONG_BUYER_SIGNALS = [
    # User-provided strong keywords
    "مطلوب للشراء", "مطلوب شراء", "مطلوب شقة", "مطلوب فيلا", "مطلوب أرض", "مطلوب محل", 
    "مطلوب مكتب", "مطلوب وحدة", "مطلوب وحدة سكنية", "مطلوب وحدة تجارية", "مطلوب تاون هاوس", 
    "مطلوب توين هاوس", "مطلوب دوبلكس", "مطلوب بنتهاوس", "مطلوب استوديو", "مطلوب شاليه", 
    "مطلوب عقار", "شراء عقار", "شراء شقة", "شراء فيلا", "شراء أرض", "شراء محل", "شراء مكتب", 
    "شراء وحدة", "شراء شاليه", "شراء دوبلكس", "شراء بنتهاوس", "شراء استوديو", "شراء عيادة", 
    "شراء صيدلية", "شراء مخزن", "شراء مصنع", "شراء عمارة", "شراء مبنى", "أرغب في الشراء", 
    "أريد الشراء", "اريد الشراء", "راغب في الشراء", "يرغب في الشراء", "مهتم بالشراء", 
    "أنوي الشراء", "ناوي أشتري", "بفكر أشتري", "جاهز للشراء", "طلب شراء", "طلبات شراء", 
    "أبحث عن شقة", "أبحث عن فيلا", "أبحث عن أرض", "أبحث عن محل", "أبحث عن مكتب", 
    "أبحث عن وحدة", "أبحث عن شاليه", "أبحث عن دوبلكس", "أبحث عن بنتهاوس", "أبحث عن عقار", 
    "أبحث عن بيت", "أبحث عن منزل", "ابحث عن شقة", "ابحث عن فيلا", "ابحث عن عقار", 
    "ابحث عن أرض", "ابحث عن محل", "بدور على شقة", "بدور على فيلا", "بدور على أرض", 
    "بدور على محل", "بدور على مكتب", "بدور على عقار", "بدور على بيت", "بدور على منزل", 
    "حابب أشتري", "حابة أشتري", "عايز أشتري", "عايزة أشتري", "عاوز أشتري", "عاوزه أشتري", 
    "محتاج أشتري", "محتاجة أشتري", "عايز أجيب شقة", "عايزة أجيب شقة", "هجيب شقة", "هجيب فيلا", 
    "عايز شقة", "عايزة شقة", "محتاج شقة", "محتاجة شقة", "عايز فيلا", "عايزة فيلا", "محتاج فيلا", 
    "محتاجة فيلا", "عايز أرض", "عايزة أرض", "محتاج أرض", "محتاجة أرض", "عايز محل", "عايزة محل", 
    "محتاج محل", "محتاجة محل", "عايز مكتب", "عايزة مكتب", "محتاج مكتب", "محتاجة مكتب", 
    "عايز شاليه", "عايزة شاليه", "محتاج شاليه", "محتاجة شاليه", "عايز دوبلكس", "عايز بنتهاوس", 
    "عايز تاون هاوس", "عايز توين هاوس", "هل يوجد شقة", "هل يوجد فيلا", "هل يوجد أرض", 
    "حد عنده شقة للبيع", "حد عنده فيلا للبيع", "مين عنده شقة للبيع", "هل فيه شقة للبيع", 
    "هل فيه فيلا للبيع", "ترشيح شقة", "ترشيح كمبوند", "أفضل مشروع", "أفضل كمبوند", 
    "looking to buy", "want to buy", "want to purchase", "need to buy", "looking for apartment", 
    "looking for flat", "looking for villa", "looking for property", "looking for house", 
    "looking for home", "looking for land", "looking for office", "looking for shop", 
    "looking for chalet", "looking for duplex", "looking for townhouse", "searching for apartment", 
    "searching for flat", "searching for villa", "searching for property", "searching for house", 
    "searching for land", "interested in buying", "buy property", "buy apartment", "buy villa", 
    "buy house", "purchase property", "need apartment", "need flat", "need villa", "need property", 
    "need house", "need land", "want property",
    # Legacy rent-seeking that are considered strong leads
    "مطلوب للإيجار", "مطلوب إيجار", "عايز أأجر", "بدور على شقة إيجار", "محتاج شقة إيجار"
]

MEDIUM_BUYER_SIGNALS = [
    # User-provided medium/generic keywords
    "مطلوب", "شراء", "أبحث عن", "ابحث عن", "بحث عن", "بدور", "بدوّر", "بدور على", "بدوّر على", 
    "أدور على", "بدورلي", "بدور ليا", "عايز", "عايزة", "عاوز", "عاوزه", "محتاج", "محتاجة", 
    "نفسي", "نفسي في", "حابب أجيب", "حابه أجيب", "هشتري", "هنشتري", "هل يوجد", "هل في", "هل فيه", 
    "فيه", "في حد عنده", "حد عنده", "حد يعرف", "مين عنده", "من عنده", "من لديهم", "من لديه", 
    "أي حد", "لو حد", "ممكن", "ممكن حد", "ممكن ألاقي", "حد يرشح", "ترشيحات", "أفضل مكان", 
    "أنسب مشروع", "أنسب كمبوند", "إيه الأفضل", "أيه الأفضل", "محتار بين", "للتواصل", "يرجى التواصل", 
    "أرجو التواصل", "تواصل معي", "كلمني", "كلموني", "ابعتلي", "ابعتولي", "راسلني", "راسلوني", 
    "خاص", "Inbox", "DM", "looking for", "searching for", "require", "in need of", "LF", "LFB", 
    "WTB", "ISO", "Looking For", "Need", "Wanted", "wanted", "ابحت", "ابحس", "بدورر", "بدور علي", 
    "بدور ع", "شقه", "فيلاا", "ارض", "عقارر", "اريد", "أريد", "نريد"
]

SELLER_SIGNALS = [
    "للبيع", "بيع", "معروض للبيع", "للإيجار", "للايجار",
    "إيجار", "ايجار", "بيع مباشر", "بدون وسيط", "مالك مباشر",
    "للتقديم", "سعر المتر", "عرض خاص", "خصم", "تخفيض",
    "for sale", "for rent", "selling", "sale", "rent",
    "نقدم", "نعرض", "تفضلوا", "متاح", "فرصة استثمارية",
    "اغتنم", "حجز", "احجز", "استلام فوري",
    "اتصل الآن", "عرض محدود", "آخر قطعة",
    "للتفاصيل", "تواصل معنا", "كلمنا", "للحجز",
]

COMMENT_BUYER_SIGNALS = [
    "تفاصيل", "التفاصيل", "بكام", "السعر", "رقمك", "ممكن التفاصيل",
    "مهتم", "إنبوكس", "خاص", "انبوكس", "dm", "رسالة",
    "موقع", "المكان", "مساحة", "الصور", "صور",
    "details", "price", "how much", "interested", "ممكن رقمك",
    "التواصل", "تواصل", "ابعتلي",
]

# ─────────────────────────────────────────────────────────────────────────────
#  EGYPT LOCATIONS  (expanded)
# ─────────────────────────────────────────────────────────────────────────────

EGYPT_LOCATIONS = {
    # Greater Cairo
    "مدينة نصر": "القاهرة", "المعادي": "القاهرة", "الزمالك": "القاهرة",
    "مصر الجديدة": "القاهرة", "عين شمس": "القاهرة", "شبرا": "القاهرة",
    "المقطم": "القاهرة", "حلوان": "القاهرة",
    "القاهرة الجديدة": "القاهرة", "التجمع الخامس": "القاهرة",
    "التجمع الأول": "القاهرة", "التجمع الثالث": "القاهرة",
    "الرحاب": "القاهرة", "مدينتي": "القاهرة",
    "الشروق": "القاهرة", "بدر": "القاهرة", "العبور": "القاهرة",
    "العاصمة الإدارية": "القاهرة", "مستقبل سيتي": "القاهرة",
    "النزهة": "القاهرة", "الحي السابع": "القاهرة",
    "اللوتس": "القاهرة", "جنوب الأكاديمية": "القاهرة",
    "شمال الرحاب": "القاهرة", "بيت الوطن": "القاهرة",
    # Giza
    "6 أكتوبر": "الجيزة", "أكتوبر": "الجيزة", "الشيخ زايد": "الجيزة",
    "الجيزة": "الجيزة", "الهرم": "الجيزة", "فيصل": "الجيزة",
    "الدقي": "الجيزة", "المهندسين": "الجيزة", "إمبابة": "الجيزة",
    "حدائق أكتوبر": "الجيزة", "الحصري": "الجيزة",
    # Alexandria
    "الإسكندرية": "الإسكندرية", "سيدي بشر": "الإسكندرية",
    "العجمي": "الإسكندرية", "سموحة": "الإسكندرية", "المنتزه": "الإسكندرية",
    "جليم": "الإسكندرية", "سان ستيفانو": "الإسكندرية",
    "الإبراهيمية": "الإسكندرية", "لوران": "الإسكندرية",
    # Coast & Sea
    "الساحل الشمالي": "مطروح", "العلمين": "مطروح", "مرسى مطروح": "مطروح",
    "الغردقة": "البحر الأحمر", "الجونة": "البحر الأحمر",
    "سهل حشيش": "البحر الأحمر", "مكادي": "البحر الأحمر",
    "العين السخنة": "السويس", "شرم الشيخ": "جنوب سيناء",
    "رأس سدر": "جنوب سيناء", "دهب": "جنوب سيناء",
    # Other
    "المنصورة": "الدقهلية", "طنطا": "الغربية",
    "الإسماعيلية": "الإسماعيلية", "بورسعيد": "بورسعيد",
    "السويس": "السويس", "أسيوط": "أسيوط",
    "الأقصر": "الأقصر", "أسوان": "أسوان",
    "الفيوم": "الفيوم", "بني سويف": "بني سويف",
    "المنيا": "المنيا", "سوهاج": "سوهاج",
    "دمياط": "دمياط", "كفر الشيخ": "كفر الشيخ",
}

# ─────────────────────────────────────────────────────────────────────────────
#  PROPERTY TYPES
# ─────────────────────────────────────────────────────────────────────────────

PROPERTY_TYPES = {
    "apartment":  ["شقة", "شقق", "apartment", "flat", "وحدة سكنية",
                   "استوديو", "studio", "وحدة"],
    "villa":      ["فيلا", "فلل", "villa", "فيلات"],
    "duplex":     ["دوبلكس", "duplex"],
    "penthouse":  ["بنتهاوس", "penthouse", "روف", "roof"],
    "land":       ["أرض", "ارض", "قطعة أرض", "land", "plot"],
    "office":     ["مكتب", "مكاتب", "office", "إداري", "اداري"],
    "shop":       ["محل", "محلات", "shop", "تجاري"],
    "chalet":     ["شاليه", "chalet", "شاليهات"],
    "townhouse":  ["تاون هاوس", "توين هاوس", "townhouse", "twin house"],
    "warehouse":  ["مخزن", "مستودع", "warehouse"],
    "clinic":     ["عيادة", "clinic", "طبي"],
}

# ─────────────────────────────────────────────────────────────────────────────
#  KNOWN COMPOUNDS & DEVELOPERS
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_COMPOUNDS = [
    "ماونتن فيو", "Mountain View", "بالم هيلز", "Palm Hills",
    "هايد بارك", "Hyde Park", "سوديك", "SODIC", "إعمار", "Emaar",
    "طلعت مصطفى", "TMG", "أورا", "ORA", "المراسم", "Al Marasem",
    "سيتي إيدج", "City Edge", "لافيستا", "La Vista",
    "حسن علام", "Hassan Allam", "كمبوند", "compound",
    "مدينة نصر للإسكان", "MNHD", "درة", "Dorra",
    "الأهلي صبور", "Al Ahly Sabbour", "وادي دجلة", "Wadi Degla",
    "مينا", "Mena", "بيتا إيجيبت", "Beta Egypt",
    "كابيتال جروب", "Capital Group", "تطوير مصر", "Tatweer Misr",
    "ريدكون", "Redcon", "إل بوسكو", "Il Bosco",
]

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN DETECTOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BuyerDetector:
    """
    Analyses raw Facebook post text and extracts ALL available buyer data.
    """

    def analyse(self, raw_text: str, is_comment: bool = False, force_lead: bool = False) -> dict:
        if not raw_text or len(raw_text.strip()) < 2:  # Comments can be very short like "بكام"
            return self._empty()

        text = raw_text.strip()

        # Step 1 — reject obvious seller posts (only if not a comment, as comments are usually buyers asking sellers)
        if not is_comment and self._is_seller(text) and not force_lead:
            return self._empty()

        # Step 2 — score buyer signals
        score, matched = self._buyer_score(text, is_comment=is_comment)
        
        # Lower threshold for comments since they are usually shorter and implicit
        # User requested more generous finding, so threshold is lower:
        threshold = 10 if is_comment else 15
        is_buyer = score >= threshold

        if not is_buyer and not force_lead:
            return self._empty()

        # Step 2b — reject advisor/recommender posts (people giving tips, not buying)
        if self._is_advisor(text, matched) and not force_lead:
            return self._empty()

        # Step 3 — extract ALL lead data
        locations, govs = self._extract_locations(text)
        phones = self._extract_phones(text)
        whatsapp = self._extract_whatsapp(text)
        budget_min, budget_max = self._extract_budget_range(text)
        bedrooms = self._extract_rooms(text, "bedroom")
        bathrooms = self._extract_rooms(text, "bathroom")
        property_type = self._detect_property_type(text)
        area_min, area_max = self._extract_area_range(text)
        payment = self._detect_payment_method(text)
        urgency = self._detect_urgency(text)
        delivery = self._detect_delivery_pref(text)
        finishing = self._detect_finishing(text)
        compounds = self._extract_compounds(text)
        buyer_name_from_text = self._extract_name_from_text(text)

        # Step 4 — calculate lead score (0-100)
        lead_score = self._calculate_lead_score(
            matched=matched,
            phones=phones,
            whatsapp=whatsapp,
            budget=budget_max,
            locations=locations,
            area_max=area_max,
            property_type=property_type,
            bedrooms=bedrooms,
            payment=payment,
            urgency=urgency,
        )

        # Merge all phone numbers (dedup)
        all_phones = list(dict.fromkeys(phones + whatsapp))

        # Adjust intent and grade if it's a forced lead with low score
        intent = self._detect_intent(text)
        grade = self._score_to_grade(lead_score)
        
        if force_lead and not is_buyer:
            is_buyer = True
            intent = "comment"
            if lead_score < 10:
                lead_score = 10
            grade = "⚪ COLD"

        result = {
            "is_buyer":          is_buyer,
            "confidence":        min(score, 100),
            "lead_score":        lead_score,
            "lead_grade":        grade,
            "intent":            intent,
            "property_type":     property_type,
            "locations":         locations,
            "governorates":      govs,
            "budget_min":        budget_min,
            "budget_max":        budget_max,
            "area_min":          area_min,
            "area_max":          area_max,
            "bedrooms":          bedrooms,
            "bathrooms":         bathrooms,
            "furnished":         self._detect_furnished(text),
            "floor_pref":        self._extract_floor_pref(text),
            "phone_numbers":     all_phones,
            "whatsapp_numbers":  whatsapp,
            "buyer_name":        buyer_name_from_text,
            "payment_method":    payment,
            "urgency":           urgency,
            "delivery_pref":     delivery,
            "finishing_level":   finishing,
            "preferred_compounds": compounds,
            "notes":             self._extract_notes(text),
            "raw_text":          text,
            "matched_signals":   matched,
        }

        return result

    # ── Lead Score ────────────────────────────────────────────────────────

    def _calculate_lead_score(self, matched, phones, whatsapp, budget,
                               locations, area_max, property_type,
                               bedrooms, payment, urgency) -> int:
        """
        Calculate a 0-100 lead score.
        Factors: signal strength, data completeness, urgency, contact info.
        """
        score = 0

        # Signal quality (cap at 40)
        strong_count = sum(1 for m in matched if m in STRONG_BUYER_SIGNALS)
        medium_count = len(matched) - strong_count
        signal_score = min(40, strong_count * 18 + medium_count * 6)
        score += signal_score

        # Contact info (up to 20)
        if phones:                  score += 12
        if whatsapp:                score += 5
        if len(phones) >= 2:        score += 3

        # Budget info (up to 10)
        if budget:                  score += 10

        # Location specificity (up to 8)
        if locations:               score += 5
        if len(locations) >= 2:     score += 3

        # Property details (up to 12)
        if property_type != "unknown": score += 4
        if area_max:                   score += 3
        if bedrooms:                   score += 3
        if payment:                    score += 2

        # Urgency bonus (up to 10)
        if urgency == "urgent":     score += 10
        elif urgency == "soon":     score += 5

        return min(100, score)

    @staticmethod
    def _score_to_grade(score: int) -> str:
        if score >= 80: return "🔥 HOT"
        if score >= 60: return "🟢 WARM"
        if score >= 40: return "🟡 COOL"
        return "⚪ COLD"

    # ── Seller detection ──────────────────────────────────────────────────

    def _is_seller(self, text: str) -> bool:
        seller_hits = sum(1 for s in SELLER_SIGNALS if s in text)
        buyer_hits  = sum(1 for s in STRONG_BUYER_SIGNALS if s in text)
        if seller_hits >= 2 and buyer_hits == 0:
            return True
        if seller_hits >= 4:
            return True
        return False

    def _is_advisor(self, text: str, matched_signals: list) -> bool:
        """
        Reject posts where someone is giving ADVICE/RECOMMENDATIONS to others
        rather than expressing their own intent to buy.
        e.g. "شوف stn مشروع ع طريق السويس" or "لو هدفك سكن مش استثمار"
        """
        advisor_patterns = [
            # 2nd person recommendations
            r"\b(لو هدفك|انت بتدور|لو كنت|شوف |جرب|روح|تعمل)",
            r"\b(بيعطيك|هينفعك|تنفعك|ينفعك|انصحك|نصيحتي|بنصحك)",
            r"\b(بيبقى|هيبقى|هينفع|بينفع)",
            # Broker/agent recommendation phrases
            r"(يوجد عندك|عندي لك|عندنا لك|متوفر لك)",
        ]
        has_advisor = any(
            re.search(pat, text, re.IGNORECASE)
            for pat in advisor_patterns
        )
        # Only reject as advisor if there are NO strong buyer signals from the person themselves
        strong_self_signals = [
            "عايز أشتري", "عايزة أشتري", "بدور على", "بدور على شقة",
            "محتاج شقة", "محتاجة شقة", "مطلوب شقة", "نفسي أشتري",
            "أرغب في الشراء", "أبحث عن شقة",
        ]
        has_self_intent = any(sig in text for sig in strong_self_signals)
        return has_advisor and not has_self_intent

    # ── Buyer scoring ─────────────────────────────────────────────────────

    def _buyer_score(self, text: str, is_comment: bool = False) -> tuple:
        score   = 0
        matched = []

        for sig in STRONG_BUYER_SIGNALS:
            if sig in text:
                score += 40
                matched.append(sig)

        for sig in MEDIUM_BUYER_SIGNALS:
            if sig in text:
                score += 15
                matched.append(sig)

        if is_comment:
            for sig in COMMENT_BUYER_SIGNALS:
                if sig in text:
                    score += 20
                    matched.append(sig)

        has_budget = self._extract_budget_range(text)[1] is not None
        
        # Only boost score with phone/location if there's a strong indication of intent (keyword or budget)
        if len(matched) > 0 or has_budget or is_comment:
            if self._extract_phones(text):
                score += 20
            if has_budget:
                score += 15
            locs, _ = self._extract_locations(text)
            if locs:
                score += 10
            if re.search(r"\d+\s*(?:متر|م)", text):
                score += 5

        return score, list(set(matched))

    # ── Intent ────────────────────────────────────────────────────────────

    def _detect_intent(self, text: str) -> str:
        buy_words  = ["شراء", "أشتري", "اشتري", "buy", "purchase",
                      "تمليك", "ملكية", "تملك"]
        rent_words = ["إيجار", "ايجار", "استئجار", "أستأجر",
                      "rent", "مفروشة", "أأجر"]
        buy_hits  = sum(1 for w in buy_words  if w in text)
        rent_hits = sum(1 for w in rent_words if w in text)
        if buy_hits > rent_hits: return "buy"
        if rent_hits > buy_hits: return "rent"
        return "buy"

    # ── Property type ─────────────────────────────────────────────────────

    def _detect_property_type(self, text: str) -> str:
        for ptype, kws in PROPERTY_TYPES.items():
            if any(k in text for k in kws):
                return ptype
        return "unknown"

    # ── Location extraction ───────────────────────────────────────────────

    def _extract_locations(self, text: str) -> tuple:
        found_locs, found_govs = [], []
        for loc, gov in EGYPT_LOCATIONS.items():
            if loc in text:
                if loc not in found_locs:  found_locs.append(loc)
                if gov not in found_govs:  found_govs.append(gov)
        return found_locs, found_govs

    # ── Budget extraction (RANGE — min + max) ─────────────────────────────

    def _extract_budget_range(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Extract budget as a RANGE: (min, max).
        Handles patterns like:
          من 2 مليون إلى 3 مليون
          ميزانية 3 مليون
          بحدود مليون ونص
          2-3 مليون
        """
        multipliers = {
            "مليار": 1_000_000_000, "مليون": 1_000_000,
            "ألف": 1_000, "الف": 1_000, "k": 1_000,
        }

        def _parse_amount(raw: str, suffix: str) -> Optional[float]:
            try:
                amount = float(raw.replace(",", ""))
                for word, mult in multipliers.items():
                    if word in suffix.lower():
                        amount *= mult
                        break
                if amount >= 30_000:
                    return amount
            except (ValueError, TypeError):
                pass
            return None

        # Range pattern: من X إلى Y / X-Y مليون
        range_patterns = [
            r"(?:من|min)\s*(\d+(?:\.\d+)?)\s*(مليار|مليون|ألف|الف|k)?\s*(?:إلى|الى|لـ|ل|حتى|-|–|to)\s*(\d+(?:\.\d+)?)\s*(مليار|مليون|ألف|الف|k)?",
            r"(\d+(?:\.\d+)?)\s*(?:-|–)\s*(\d+(?:\.\d+)?)\s*(مليار|مليون|ألف|الف|k)",
        ]

        for pat in range_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                groups = m.groups()
                if len(groups) == 4:
                    suffix1 = groups[1] or groups[3] or ""
                    suffix2 = groups[3] or groups[1] or ""
                    mn = _parse_amount(groups[0], suffix1)
                    mx = _parse_amount(groups[2], suffix2)
                    if mn and mx:
                        return mn, mx

                elif len(groups) == 3:
                    suffix = groups[2] or ""
                    mn = _parse_amount(groups[0], suffix)
                    mx = _parse_amount(groups[1], suffix)
                    if mn and mx:
                        return mn, mx

        # Single value patterns (max only)
        single_patterns = [
            r"(?:ميزانية|الميزانية|بحد أقصى|حد أقصى|بحدود|في حدود|لا تتجاوز|مش أكتر من|مش أكثر من|budget|max)"
            r"[\s:]+([\d,]+(?:\.\d+)?)\s*(مليار|مليون|ألف|الف|k)?",
            r"(?:أقل من|اقل من|تحت|under)\s+([\d,]+(?:\.\d+)?)\s*(مليار|مليون|ألف|الف|k)?",
            r"([\d,]+(?:\.\d+)?)\s*(مليار|مليون|ألف|الف)\s*(?:جنيه|ج\.م|EGP|L\.E|فقط)?",
            # Only match standalone 6-9 digit numbers if explicitly followed by currency.
            # This prevents phone numbers formatted with spaces from being captured.
            r"(?<!\d)(\d{6,9})(?!\d)\s*(?:جنيه|ج\.م|EGP|L\.E|ج)",
        ]

        for pat in single_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                suffix = ""
                if m.lastindex and m.lastindex >= 2:
                    suffix = (m.group(2) or "").strip()
                val = _parse_amount(m.group(1), suffix)
                if val:
                    return None, val

        return None, None

    # ── Area range ────────────────────────────────────────────────────────

    def _extract_area_range(self, text: str) -> tuple:
        m = re.search(
            r"(\d+)\s*(?:إلى|الى|-|–)\s*(\d+)\s*(?:متر|م²|m2|sqm)",
            text, re.IGNORECASE,
        )
        if m:
            return float(m.group(1)), float(m.group(2))
        patterns = [
            r"(?:مساحة|مساحته|مساحتها)[:\s]+([\d,]+(?:\.\d+)?)",
            r"([\d,]+(?:\.\d+)?)\s*(?:متر مربع|م مربع|م²|m2|sqm)",
            r"([\d,]+(?:\.\d+)?)\s*متر(?!\s*شارع)",
            r"(\d+)\s*م\b",
        ]
        for pat in patterns:
            m2 = re.search(pat, text, re.IGNORECASE)
            if m2:
                val = float(m2.group(1).replace(",", ""))
                if 15 < val < 5000:
                    return None, val
        return None, None

    # ── Rooms ─────────────────────────────────────────────────────────────

    def _extract_rooms(self, text: str, room_type: str) -> Optional[int]:
        if room_type == "bedroom":
            patterns = [
                r"(\d)\s*(?:غرف نوم|غرفة نوم|أوض|أوضة نوم|غرف)",
                r"(\d)\s*نوم", r"(\d)\s*(?:bedroom|room|bed|BR)",
                r"(?:غرف|أوض)\s*(\d)",
            ]
        else:
            patterns = [
                r"(\d)\s*(?:حمام|حمامات|bathroom|bath)",
                r"(\d)\s*دورة مياه",
                r"(?:حمام|حمامات)\s*(\d)",
            ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1))
                    if 0 < v < 15: return v
                except ValueError:
                    pass
        return None

    # ── Furnished preference ──────────────────────────────────────────────

    def _detect_furnished(self, text: str) -> Optional[bool]:
        if any(k in text for k in ["مفروشة", "مفروش", "furnished",
                                    "fully furnished", "مع الأثاث",
                                    "بالأثاث", "بالفرش"]):
            return True
        if any(k in text for k in ["غير مفروشة", "غير مفروش",
                                    "unfurnished", "بدون أثاث",
                                    "بدون فرش", "فاضية"]):
            return False
        return None

    # ── Floor preference ──────────────────────────────────────────────────

    def _extract_floor_pref(self, text: str) -> Optional[str]:
        prefs = {
            "أرضي": "ground", "ارضي": "ground", "ground": "ground",
            "أول": "1st", "اول": "1st", "ثاني": "2nd", "ثالث": "3rd",
            "رابع": "4th", "خامس": "5th",
            "دور منخفض": "low_floor", "أدوار منخفضة": "low_floor",
            "دور مرتفع": "high_floor", "أدوار مرتفعة": "high_floor",
            "آخر دور": "top_floor", "اخر دور": "top_floor",
            "دور متكرر": "repeated_floor",
        }
        for word, val in prefs.items():
            if word in text:
                return val
        return None

    # ── Phone numbers (enhanced) ──────────────────────────────────────────

    def _extract_phones(self, text: str) -> list:
        """Extract all Egyptian mobile numbers from text."""
        patterns = [
            r"\b(01[0125]\d{8})\b",
            r"\b(01[0125][\s\-]?\d{4}[\s\-]?\d{4})\b",
            r"\+20\s?(1[0125]\d{8})",
            r"(?:تواصل|موبايل|تليفون|واتساب|whatsapp|واتس|رقم|موبيل|تلفون|جوال|هاتف|فون|phone|call|tel)[:\s]+([\d][\d\s\-]{8,})",
            # Numbers written with dots or spaces
            r"\b(01[0125][\.\s]?\d{4}[\.\s]?\d{4})\b",
            # Arabic-Eastern numerals (٠١٢...)
            r"(٠١[٠١٢٥][\s\-]?[٠-٩]{4}[\s\-]?[٠-٩]{4})",
        ]
        found, seen = [], set()
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                raw = re.sub(r"[\s\-\.]", "", m.group(1))
                # Convert Arabic-Eastern numerals to Western
                eastern = "٠١٢٣٤٥٦٧٨٩"
                for i, c in enumerate(eastern):
                    raw = raw.replace(c, str(i))
                # Normalize: +201XXXXXXXX → 01XXXXXXXX, 201XXXXXXXX → 01XXXXXXXX
                if raw.startswith("+20"):
                    raw = "0" + raw[3:]
                elif raw.startswith("20") and len(raw) == 12:
                    raw = "0" + raw[2:]
                # Must be exactly 11 digits and start with 01
                if len(raw) == 11 and raw.startswith("01") and raw not in seen:
                    seen.add(raw)
                    found.append(raw)
        return found[:6]

    # ── WhatsApp numbers ──────────────────────────────────────────────────

    def _extract_whatsapp(self, text: str) -> list:
        """Extract numbers specifically mentioned with WhatsApp context."""
        wa_patterns = [
            # wa.me links: wa.me/201XXXXXXXXX or wa.me//01XXXXXXXXX
            r"wa\.me//?(20)?(1[0125]\d{8})",
            r"api\.whatsapp\.com/send\?phone=20(1[0125]\d{8})",
            r"(?:واتساب|واتس|whatsapp|whats\s*app|wa|واتسب|وتساب)[:\s]*([\d][\d\s\-\.]{8,})",
            r"(01[0125][\s\-]?\d{4}[\s\-]?\d{4})\s*(?:واتساب|واتس|whatsapp|wa)",
            r"(?:واتساب|واتس|whatsapp)\s*(?:فقط|only)?\s*(01[0125]\d{8})",
        ]
        found, seen = [], set()
        for pat in wa_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                # Use the last non-None captured group (handles wa.me 2-group pattern)
                raw_group = next(
                    (g for g in reversed(m.groups()) if g is not None),
                    None
                )
                if not raw_group:
                    continue
                raw = re.sub(r"[\s\-\.]", "", raw_group)
                eastern = "٠١٢٣٤٥٦٧٨٩"
                for i, c in enumerate(eastern):
                    raw = raw.replace(c, str(i))
                # Normalize: +201XXXXXXXX → 01XXXXXXXX
                if raw.startswith("+20"):
                    raw = "0" + raw[3:]
                elif raw.startswith("20") and len(raw) == 12:
                    raw = "0" + raw[2:]
                elif len(raw) == 9 and raw.startswith("1"):
                    # wa.me pattern captured just "1XXXXXXXX" (10 digits with 20 stripped)
                    raw = "0" + raw
                if len(raw) == 11 and raw.startswith("01") and raw not in seen:
                    seen.add(raw)
                    found.append(raw)
        return found[:4]


    # ── Payment method ────────────────────────────────────────────────────

    def _detect_payment_method(self, text: str) -> Optional[str]:
        """Detect: cash, installments, mortgage, or mixed."""
        cash_kw = ["كاش", "cash", "نقدي", "نقداً", "دفع فوري", "كاملة"]
        inst_kw = ["تقسيط", "أقساط", "اقساط", "installment", "قسط شهري",
                   "على أقساط", "تسهيلات", "سداد", "دفعات"]
        mort_kw = ["تمويل عقاري", "بنك", "mortgage", "تمويل بنكي"]

        has_cash = any(k in text for k in cash_kw)
        has_inst = any(k in text for k in inst_kw)
        has_mort = any(k in text for k in mort_kw)

        if has_cash and has_inst: return "cash_or_installments"
        if has_cash:              return "cash"
        if has_inst:              return "installments"
        if has_mort:              return "mortgage"
        return None

    # ── Urgency ───────────────────────────────────────────────────────────

    def _detect_urgency(self, text: str) -> Optional[str]:
        """Detect how urgently the buyer needs the property."""
        urgent_kw = ["مستعجل", "ضروري", "فوري", "urgent", "ASAP",
                     "عاجل", "بسرعة", "في أقرب وقت", "محتاج بسرعة",
                     "النهاردة", "اليوم", "حالاً", "فوراً",
                     "خلال أسبوع", "خلال اسبوع"]
        soon_kw = ["قريب", "خلال شهر", "خلال أسبوعين", "في أقرب فرصة",
                   "soon", "الشهر ده", "الشهر الجاي"]

        if any(k in text for k in urgent_kw): return "urgent"
        if any(k in text for k in soon_kw):   return "soon"
        return None

    # ── Delivery preference ───────────────────────────────────────────────

    def _detect_delivery_pref(self, text: str) -> Optional[str]:
        """When does the buyer want to receive the property?"""
        immediate_kw = ["استلام فوري", "تسليم فوري", "جاهز للسكن",
                        "ready to move", "فوري", "تسليم"]
        future_kw = ["تسليم بعد", "تسليم خلال", "على المخطط",
                     "under construction", "بعد سنة", "بعد سنتين"]

        if any(k in text for k in immediate_kw): return "immediate"
        if any(k in text for k in future_kw):    return "future"
        return None

    # ── Finishing level ───────────────────────────────────────────────────

    def _detect_finishing(self, text: str) -> Optional[str]:
        """Detect preferred finishing level."""
        super_lux = ["سوبر لوكس", "super lux", "سوبر لوكص", "لوكس"]
        semi_fin = ["نصف تشطيب", "نص تشطيب", "semi finished", "سيمي فنش"]
        full_fin = ["تشطيب كامل", "fully finished", "متشطبة", "تشطيب"]
        core_sh = ["كور وشل", "core & shell", "core and shell", "على الطوب"]

        if any(k in text for k in super_lux): return "super_lux"
        if any(k in text for k in semi_fin):  return "semi_finished"
        if any(k in text for k in full_fin):  return "fully_finished"
        if any(k in text for k in core_sh):   return "core_shell"
        return None

    # ── Compound / Developer preference ───────────────────────────────────

    def _extract_compounds(self, text: str) -> list:
        """Extract any mentioned compound or developer names."""
        found = []
        for name in KNOWN_COMPOUNDS:
            if name.lower() in text.lower() and name not in found:
                found.append(name)
        return found[:5]

    # ── Name extraction from text ─────────────────────────────────────────

    def _extract_name_from_text(self, text: str) -> str:
        """
        Try to extract buyer's name from the post text.
        Patterns like: اسمي أحمد / أنا محمد / my name is ...
        """
        patterns = [
            r"(?:اسمي|اسمى|انا|أنا|my name is|i am|i'm)\s+([^\n,\.]{2,30})",
            r"(?:الاسم|الأسم)[:\s]+([^\n,\.]{2,30})",
            r"(?:ا/|أ/|م/|مهندس|مهندسة|دكتور|دكتورة|أستاذ|استاذ)\s*([^\n,\.]{2,25})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # Basic validation: not too long, no numbers
                if 2 <= len(name) <= 30 and not re.search(r"\d{3,}", name):
                    return name
        return ""

    # ── Notes / extra preferences ─────────────────────────────────────────

    def _extract_notes(self, text: str) -> str:
        pref_words = [
            "تشطيب", "فيو", "view", "حديقة", "garden", "كمبوند",
            "بحري", "قبلي", "ركنية", "ناصية", "قريب من", "بالقرب",
            "مترو", "جامعة", "مدرسة", "بدون رسوم", "بدون عمولة",
            "تقسيط", "كاش", "أقساط", "جراج", "parking", "أسانسير",
            "elevator", "حمام سباحة", "pool", "أمن", "security",
            "نادي", "club", "مول", "mall", "مساحة خضراء",
            "شارع رئيسي", "واجهة", "طابق", "دور",
        ]
        notes = []
        for line in text.split("\n"):
            line = line.strip()
            if line and any(w in line for w in pref_words):
                notes.append(line)
        return " | ".join(notes[:8])

    # ── Empty result ──────────────────────────────────────────────────────

    @staticmethod
    def _empty() -> dict:
        return {"is_buyer": False}
