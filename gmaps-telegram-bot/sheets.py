import os
import logging
from datetime import datetime
from typing import Optional
import uuid

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

from scraper import BusinessInfo, Review

load_dotenv()
logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_credentials.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

BUSINESS_HEADERS = [
    "Timestamp", "Search Query", "Business Name", "Overall Rating", "Total Reviews",
    "Category", "Price Level", "Address", "Phone", "Website", "Maps URL",
    "Reviews Scraped", "Read Reviews (Link)"
]

REVIEW_HEADERS = [
    "Search Query", "Business Name", "Author", "Rating", "Date", "Likes", "Review Text"
]

class SheetsWriter:
    def __init__(self, creds_path: str, sheet_id: str):
        self.sheet_id   = sheet_id
        self.creds_path = creds_path
        self._client: Optional[gspread.Client] = None

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            if not os.path.exists(self.creds_path):
                raise FileNotFoundError(f"Credentials not found at {self.creds_path}")
            creds = Credentials.from_service_account_file(self.creds_path, scopes=SCOPES)
            self._client = gspread.authorize(creds)
        return self._client

    def _get_or_create_tab(self, spreadsheet, title: str, headers: list[str]):
        try:
            ws = spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
            ws.append_row(headers, value_input_option="USER_ENTERED")
            ws.format("1:1", {"textFormat": {"bold": True}})
            logger.info("Created tab: %s", title)
        return ws

    def write(self, query: str, info: BusinessInfo) -> bool:
        if not self.sheet_id:
            logger.error("GOOGLE_SHEET_ID is missing.")
            return False

        try:
            client  = self._get_client()
            sheet   = client.open_by_key(self.sheet_id)
            ts      = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

            biz_ws = self._get_or_create_tab(sheet, "Businesses", BUSINESS_HEADERS)
            rev_ws = self._get_or_create_tab(sheet, "Reviews", REVIEW_HEADERS)

            # To create a direct link to the reviews, we'll create a filter view URL
            # The URL structure for a filter on Column B (Business Name) is:
            # https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={REV_GID}&fvid={SOME_ID}
            # Since generating dynamic fvid is complex via gspread, we will use a Google Sheets formula 
            # to query the reviews sheet directly onto a new cell, or simply instruct the user.
            # However, a highly effective trick is using a HYPERLINK to a search within the sheet, or just
            # putting the Business Name in a way they can easily use the native Sheets filter.
            # To keep it extremely clean, we will output the reviews to the 'Reviews' tab and give a simple text instruction.
            
            # Write to Reviews Tab first
            if info.reviews:
                review_rows = [
                    [query, info.name, r.author, r.rating, r.date, r.likes, r.text]
                    for r in info.reviews
                ]
                rev_ws.append_rows(review_rows, value_input_option="USER_ENTERED")

            # Write to Businesses Tab
            rev_sheet_url = f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit#gid={rev_ws.id}"
            
            business_row = [
                ts, query, info.name, info.rating, info.review_count,
                info.category, info.price_level, info.address, info.phone,
                info.website, info.maps_url,
                len(info.reviews),
                f'=HYPERLINK("{rev_sheet_url}", "Click here, then filter by Name")'
            ]
            biz_ws.append_row(business_row, value_input_option="USER_ENTERED")
            
            return True
        except Exception as e:
            logger.error(f"Error saving to Sheets: {e}")
            return False

def save_to_sheet(query: str, data: BusinessInfo) -> bool:
    writer = SheetsWriter(CREDENTIALS_PATH, SHEET_ID)
    return writer.write(query, data)

