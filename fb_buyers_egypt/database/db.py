"""
Database Manager — ENHANCED CRUD for buyer leads.
Now saves and exports ALL extracted data fields.
"""

import os
import logging
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import sessionmaker, Session

from database.models import Base, BuyerLead

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self, db_url: str = "sqlite:///egypt_buyers.db"):
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self._migrate_schema()  # Add missing columns to existing tables
        self._Session = sessionmaker(bind=self.engine)
        logger.info(f"📦 Database ready: {db_url}")

    def _migrate_schema(self):
        """Add any missing columns to existing tables (lightweight migration)."""
        from sqlalchemy import inspect, text
        inspector = inspect(self.engine)

        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue

            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}

            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(self.engine.dialect)
                    default = ""
                    if col.default is not None:
                        default_val = col.default.arg
                        if callable(default_val):
                            default = ""
                        elif isinstance(default_val, bool):
                            default = f" DEFAULT {int(default_val)}"
                        elif isinstance(default_val, (int, float)):
                            default = f" DEFAULT {default_val}"
                        elif isinstance(default_val, str):
                            default = f" DEFAULT '{default_val}'"

                    sql = f'ALTER TABLE {table_name} ADD COLUMN "{col.name}" {col_type}{default}'
                    try:
                        with self.engine.begin() as conn:
                            conn.execute(text(sql))
                        logger.info(f"  ➕ Added column: {table_name}.{col.name}")
                    except Exception as e:
                        logger.debug(f"  Column {col.name} migration skipped: {e}")


    def get_session(self) -> Session:
        return self._Session()

    # ── Save leads ────────────────────────────────────────────────────────

    def save_leads(self, leads: List[dict]) -> dict:
        """Save a batch of leads with ALL fields. Returns stats."""
        session = self.get_session()
        saved, skipped, updated = 0, 0, 0

        try:
            for lead_data in leads:
                if not lead_data.get("is_buyer"):
                    continue

                post_url = lead_data.get("post_url", "")

                # Check for duplicate
                existing = None
                profile_url = lead_data.get("profile_url", "")
                
                if post_url and profile_url:
                    existing = session.query(BuyerLead).filter_by(
                        post_url=post_url,
                        profile_url=profile_url
                    ).first()
                elif post_url:
                    existing = session.query(BuyerLead).filter_by(
                        post_url=post_url
                    ).first()

                if existing:
                    new_score = lead_data.get("lead_score", 0)
                    if new_score > (existing.lead_score or 0):
                        self._update_lead(existing, lead_data)
                        updated += 1
                    else:
                        # Still merge new phone numbers even if score isn't better
                        self._merge_phones(existing, lead_data)
                        skipped += 1
                    continue

                # Create new lead with ALL fields
                lead = BuyerLead(
                    # Identity
                    post_url           = post_url or None,
                    profile_url        = lead_data.get("profile_url", ""),
                    profile_pic        = lead_data.get("profile_pic", ""),
                    # Buyer info
                    buyer_name         = lead_data.get("buyer_name") or lead_data.get("author", ""),
                    author             = lead_data.get("author", ""),
                    phone_numbers      = lead_data.get("phone_numbers", []),
                    whatsapp_numbers   = lead_data.get("whatsapp_numbers", []),
                    comment_phones     = lead_data.get("comment_phones", []),
                    emails             = lead_data.get("emails", []),
                    websites           = lead_data.get("websites", []),
                    whatsapp_links     = lead_data.get("whatsapp_links", []),
                    # Intent & scoring
                    intent             = lead_data.get("intent", "buy"),
                    confidence         = lead_data.get("confidence", 0),
                    lead_score         = lead_data.get("lead_score", 0),
                    lead_grade         = lead_data.get("lead_grade", ""),
                    property_type      = lead_data.get("property_type", "unknown"),
                    # Location
                    locations          = lead_data.get("locations", []),
                    governorates       = lead_data.get("governorates", []),
                    floor_pref         = lead_data.get("floor_pref"),
                    # Budget
                    budget_min         = lead_data.get("budget_min"),
                    budget_max         = lead_data.get("budget_max"),
                    # Size
                    area_min           = lead_data.get("area_min"),
                    area_max           = lead_data.get("area_max"),
                    bedrooms           = lead_data.get("bedrooms"),
                    bathrooms          = lead_data.get("bathrooms"),
                    furnished          = lead_data.get("furnished"),
                    # Preferences
                    payment_method     = lead_data.get("payment_method"),
                    urgency            = lead_data.get("urgency"),
                    delivery_pref      = lead_data.get("delivery_pref"),
                    finishing_level    = lead_data.get("finishing_level"),
                    preferred_compounds = lead_data.get("preferred_compounds", []),
                    # Profile enrichment
                    lives_in           = lead_data.get("lives_in", ""),
                    hometown           = lead_data.get("hometown", ""),
                    work_title         = lead_data.get("work_title", ""),
                    work_company       = lead_data.get("work_company", ""),
                    bio                = lead_data.get("bio", ""),
                    profile_scraped    = lead_data.get("profile_scraped", False),
                    is_broker          = lead_data.get("is_broker", False),
                    # Engagement
                    reactions          = lead_data.get("reactions", 0),
                    comment_count      = lead_data.get("comment_count", 0),
                    shares             = lead_data.get("shares", 0),
                    # Group
                    group_name         = lead_data.get("group_name", ""),
                    group_region       = lead_data.get("group_region", ""),
                    group_url          = lead_data.get("group_url", ""),
                    # Raw
                    raw_text           = lead_data.get("raw_text", ""),
                    notes              = lead_data.get("notes", ""),
                    matched_signals    = lead_data.get("matched_signals", []),
                    images             = lead_data.get("images", []),
                    comment_snippets   = lead_data.get("comment_snippets", []),
                    timestamp          = lead_data.get("timestamp", ""),
                )
                session.add(lead)
                saved += 1

            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"DB save error: {e}")
            raise
        finally:
            session.close()

        stats = {"saved": saved, "skipped": skipped, "updated": updated}
        logger.info(f"  💾 DB: {stats}")
        return stats

    def _update_lead(self, existing: BuyerLead, new_data: dict):
        """Update an existing lead with better/newer data."""
        # Update all fields that have new values
        update_fields = [
            "lead_score", "lead_grade", "confidence",
            "phone_numbers", "whatsapp_numbers", "comment_phones",
            "emails", "websites", "whatsapp_links",
            "budget_min", "budget_max", "bedrooms", "bathrooms",
            "area_min", "area_max", "notes",
            "payment_method", "urgency", "delivery_pref",
            "finishing_level", "preferred_compounds",
            "reactions", "comment_count", "shares",
            "comment_snippets",
            "lives_in", "hometown", "work_title", "work_company",
            "bio", "profile_scraped", "is_broker",
        ]
        for field in update_fields:
            new_val = new_data.get(field)
            if new_val:
                setattr(existing, field, new_val)

        # Merge phone numbers (don't lose old ones)
        self._merge_phones(existing, new_data)
        existing.updated_at = datetime.now(timezone.utc)

    def _merge_phones(self, existing: BuyerLead, new_data: dict):
        """Merge new phone numbers into existing lead without losing data."""
        for field in ["phone_numbers", "whatsapp_numbers", "comment_phones",
                      "emails", "websites", "whatsapp_links"]:
            old = existing.__dict__.get(field) or []
            new = new_data.get(field, [])
            merged = list(dict.fromkeys(old + new))  # dedup, preserve order
            setattr(existing, field, merged)

    # ── Queries ───────────────────────────────────────────────────────────

    def get_all_leads(self) -> pd.DataFrame:
        session = self.get_session()
        try:
            leads = session.query(BuyerLead).order_by(
                desc(BuyerLead.lead_score)
            ).all()
            return self._to_dataframe(leads)
        finally:
            session.close()

    def get_hot_leads(self, min_score: int = 60) -> pd.DataFrame:
        session = self.get_session()
        try:
            leads = session.query(BuyerLead).filter(
                BuyerLead.lead_score >= min_score
            ).order_by(desc(BuyerLead.lead_score)).all()
            return self._to_dataframe(leads)
        finally:
            session.close()

    def get_leads_by_region(self, region: str) -> pd.DataFrame:
        session = self.get_session()
        try:
            leads = session.query(BuyerLead).filter(
                BuyerLead.group_region == region
            ).order_by(desc(BuyerLead.lead_score)).all()
            return self._to_dataframe(leads)
        finally:
            session.close()

    def get_stats(self) -> dict:
        session = self.get_session()
        try:
            total = session.query(func.count(BuyerLead.id)).scalar()
            hot = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.lead_score >= 60
            ).scalar()
            with_phone = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.phone_numbers != '[]',
                BuyerLead.phone_numbers.isnot(None),
            ).scalar()
            contacted = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.is_contacted == True
            ).scalar()
            avg_score = session.query(func.avg(BuyerLead.lead_score)).scalar()
            urgent = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.urgency == "urgent"
            ).scalar()
            with_whatsapp = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.whatsapp_numbers != '[]',
                BuyerLead.whatsapp_numbers.isnot(None),
            ).scalar()

            with_email = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.emails != '[]',
                BuyerLead.emails.isnot(None),
            ).scalar()
            broker_count = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.is_broker == True
            ).scalar()
            profile_scraped_count = session.query(func.count(BuyerLead.id)).filter(
                BuyerLead.profile_scraped == True
            ).scalar()

            return {
                "total_leads":        total or 0,
                "hot_leads":          hot or 0,
                "with_phone":         with_phone or 0,
                "with_email":         with_email or 0,
                "with_whatsapp":      with_whatsapp or 0,
                "urgent_leads":       urgent or 0,
                "contacted":          contacted or 0,
                "brokers":            broker_count or 0,
                "profiles_scraped":   profile_scraped_count or 0,
                "avg_lead_score":     round(avg_score or 0, 1),
            }
        finally:
            session.close()

    def mark_contacted(self, lead_id: str, notes: str = ""):
        session = self.get_session()
        try:
            lead = session.query(BuyerLead).get(lead_id)
            if lead:
                lead.is_contacted = True
                lead.contact_notes = notes
                lead.updated_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()

    def export_to_excel(self, filepath: str, min_score: int = 0) -> str:
        """Export leads to Excel file with ALL data columns."""
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        df = self.get_all_leads()
        if min_score > 0:
            df = df[df["lead_score"] >= min_score]

        # ALL columns for team export
        export_cols = [
            "buyer_name", "phone_numbers", "emails", "whatsapp_numbers",
            "lead_score", "lead_grade", "intent", "urgency",
            "property_type", "locations", "governorates",
            "budget_min", "budget_max", "area_max", "bedrooms", "bathrooms",
            "furnished", "floor_pref",
            "payment_method", "delivery_pref", "finishing_level",
            "preferred_compounds",
            "lives_in", "hometown", "work_title", "work_company",
            "is_broker", "websites",
            "group_name", "group_region", "notes",
            "reactions", "comment_count",
            "post_url", "profile_url", "raw_text", "scraped_at",
            "is_contacted", "contact_notes",
        ]
        available = [c for c in export_cols if c in df.columns]
        df[available].to_excel(filepath, index=False, engine="openpyxl")
        logger.info(f"  📊 Exported {len(df)} leads → {filepath}")
        return filepath

    # ── Helpers ───────────────────────────────────────────────────────────

    def _to_dataframe(self, leads) -> pd.DataFrame:
        if not leads:
            return pd.DataFrame()
        data = []
        for l in leads:
            data.append({
                "id":                  l.id,
                "buyer_name":          l.buyer_name or l.author or "",
                "author":              l.author or "",
                "phone_numbers":       ", ".join(l.phone_numbers) if l.phone_numbers else "",
                "whatsapp_numbers":    ", ".join(l.whatsapp_numbers) if l.whatsapp_numbers else "",
                "comment_phones":      ", ".join(l.comment_phones) if l.comment_phones else "",
                "emails":              ", ".join(l.emails) if l.emails else "",
                "websites":            ", ".join(l.websites) if l.websites else "",
                "whatsapp_links":      ", ".join(l.whatsapp_links) if l.whatsapp_links else "",
                "lead_score":          l.lead_score or 0,
                "lead_grade":          l.lead_grade or "",
                "intent":              l.intent or "",
                "urgency":             l.urgency or "",
                "property_type":       l.property_type or "",
                "locations":           ", ".join(l.locations) if l.locations else "",
                "governorates":        ", ".join(l.governorates) if l.governorates else "",
                "budget_min":          l.budget_min,
                "budget_max":          l.budget_max,
                "area_min":            l.area_min,
                "area_max":            l.area_max,
                "bedrooms":            l.bedrooms,
                "bathrooms":           l.bathrooms,
                "furnished":           l.furnished,
                "floor_pref":          l.floor_pref or "",
                "payment_method":      l.payment_method or "",
                "delivery_pref":       l.delivery_pref or "",
                "finishing_level":     l.finishing_level or "",
                "preferred_compounds": ", ".join(l.preferred_compounds) if l.preferred_compounds else "",
                "lives_in":            l.lives_in or "",
                "hometown":            l.hometown or "",
                "work_title":          l.work_title or "",
                "work_company":        l.work_company or "",
                "bio":                 l.bio or "",
                "profile_scraped":     l.profile_scraped or False,
                "is_broker":           l.is_broker or False,
                "reactions":           l.reactions or 0,
                "comment_count":       l.comment_count or 0,
                "shares":              l.shares or 0,
                "group_name":          l.group_name or "",
                "group_region":        l.group_region or "",
                "notes":               l.notes or "",
                "raw_text":            l.raw_text or "",
                "post_url":            l.post_url or "",
                "profile_url":         l.profile_url or "",
                "profile_pic":         l.profile_pic or "",
                "scraped_at":          l.scraped_at,
                "is_contacted":        l.is_contacted or False,
                "contact_notes":       l.contact_notes or "",
            })
        return pd.DataFrame(data)
