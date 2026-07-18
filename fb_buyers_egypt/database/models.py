import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Integer,
    DateTime, JSON, Text, Boolean, Index,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


class BuyerLead(Base):
    __tablename__ = "buyer_leads"

    # ── Identity ──────────────────────────────────────────────────────
    id            = Column(String(36), primary_key=True, default=_uid)
    post_url      = Column(String(600), nullable=True)
    profile_url   = Column(String(600))
    profile_pic   = Column(String(800))

    # ── Buyer info ────────────────────────────────────────────────────
    buyer_name    = Column(String(250))
    author        = Column(String(250))
    phone_numbers = Column(JSON)         # list[str] — all phones
    whatsapp_numbers = Column(JSON)      # list[str] — WhatsApp-specific
    comment_phones = Column(JSON)        # list[str] — phones from comments
    emails         = Column(JSON)        # list[str] — extracted emails
    websites       = Column(JSON)        # list[str] — websites & social links
    whatsapp_links = Column(JSON)        # list[str] — wa.me links

    # ── Intent & scoring ──────────────────────────────────────────────
    intent        = Column(String(20))   # buy | rent
    confidence    = Column(Integer)      # 0-100
    lead_score    = Column(Integer)      # 0-100
    lead_grade    = Column(String(20))   # 🔥 HOT / 🟢 WARM / 🟡 COOL / ⚪ COLD
    property_type = Column(String(50))

    # ── Location ──────────────────────────────────────────────────────
    locations     = Column(JSON)         # list[str] — preferred areas
    governorates  = Column(JSON)         # list[str]
    floor_pref    = Column(String(50))

    # ── Budget ────────────────────────────────────────────────────────
    budget_min    = Column(Float)
    budget_max    = Column(Float)

    # ── Size ──────────────────────────────────────────────────────────
    area_min      = Column(Float)
    area_max      = Column(Float)
    bedrooms      = Column(Integer)
    bathrooms     = Column(Integer)
    furnished     = Column(Boolean)

    # ── Buyer preferences ─────────────────────────────────────────────
    payment_method     = Column(String(50))   # cash / installments / mortgage
    urgency            = Column(String(30))   # urgent / soon / None
    delivery_pref      = Column(String(30))   # immediate / future / None
    finishing_level    = Column(String(30))   # super_lux / semi / fully / core
    preferred_compounds = Column(JSON)        # list[str] — compound names

    # ── Profile enrichment (NEW) ──────────────────────────────────────
    lives_in       = Column(String(150))      # city from profile About
    hometown       = Column(String(150))      # hometown from profile About
    work_title     = Column(String(150))      # job title
    work_company   = Column(String(150))      # company name
    bio            = Column(Text)             # short profile intro
    profile_scraped = Column(Boolean, default=False)  # deep-scraped?
    is_broker      = Column(Boolean, default=False)   # broker flag

    # ── Engagement ────────────────────────────────────────────────────
    reactions     = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    shares        = Column(Integer, default=0)

    # ── Group ─────────────────────────────────────────────────────────
    group_name    = Column(String(250))
    group_region  = Column(String(50))
    group_url     = Column(String(600))

    # ── Raw data ──────────────────────────────────────────────────────
    raw_text        = Column(Text)
    notes           = Column(Text)
    matched_signals = Column(JSON)
    images          = Column(JSON)
    comment_snippets = Column(JSON)     # list[str] — comment text excerpts
    timestamp       = Column(String(100))

    # ── Meta ──────────────────────────────────────────────────────────
    scraped_at    = Column(DateTime, default=_now)
    updated_at    = Column(DateTime, default=_now, onupdate=_now)
    is_contacted  = Column(Boolean, default=False)
    contact_notes = Column(Text, default="")

    __table_args__ = (
        Index("ix_lead_score", "lead_score"),
        Index("ix_lead_grade", "lead_grade"),
        Index("ix_intent", "intent"),
        Index("ix_group_region", "group_region"),
        Index("ix_scraped_at", "scraped_at"),
        Index("ix_is_contacted", "is_contacted"),
        Index("ix_urgency", "urgency"),
        Index("ix_payment_method", "payment_method"),
        Index("ix_property_type", "property_type"),
        Index("ix_is_broker", "is_broker"),
        Index("ix_profile_scraped", "profile_scraped"),
    )
