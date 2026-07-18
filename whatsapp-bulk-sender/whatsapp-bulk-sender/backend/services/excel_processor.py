"""
Excel and CSV file processing service.
Uses Pandas for robust data handling, cleaning, and phone number normalization.
"""

import re
import uuid
import logging
from pathlib import Path
from typing import Optional
import os
import pickle

import pandas as pd
import phonenumbers

logger = logging.getLogger(__name__)

# Use local temp directory for caching DataFrames instead of Redis
# since we are running natively on Windows without Docker.
TMP_DIR = Path("tmp_cache")
TMP_DIR.mkdir(exist_ok=True)

def store_dataframe(df: pd.DataFrame) -> str:
    """
    Store a DataFrame locally and return a unique ID.
    The ID is used to retrieve the DataFrame later for sending.
    """
    file_id = str(uuid.uuid4())
    file_path = TMP_DIR / f"{file_id}.pkl"
    # Serialize DataFrame and store locally
    with open(file_path, "wb") as f:
        pickle.dump(df, f)
    return file_id


def retrieve_dataframe(file_id: str) -> Optional[pd.DataFrame]:
    """Retrieve a cached DataFrame by its ID."""
    file_path = TMP_DIR / f"{file_id}.pkl"
    if file_path.exists():
        with open(file_path, "rb") as f:
            return pickle.load(f)
    return None


def clear_dataframe(file_id: str) -> None:
    """Remove a DataFrame after sending is complete."""
    file_path = TMP_DIR / f"{file_id}.pkl"
    if file_path.exists():
        file_path.unlink()


def load_file(file_path: Path, filename: str) -> pd.DataFrame:
    """
    Load an Excel or CSV file into a Pandas DataFrame.
    Handles both .xlsx and .csv formats.
    """
    suffix = Path(filename).suffix.lower()

    if suffix == ".csv":
        # Try common encodings
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                df = pd.read_csv(file_path, encoding=encoding, dtype=str)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Could not decode CSV file. Please use UTF-8 encoding.")

    elif suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path, dtype=str)

    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .csv or .xlsx")

    # Strip whitespace from column names
    df.columns = [str(col).strip() for col in df.columns]

    # Drop completely empty rows
    df = df.dropna(how="all").reset_index(drop=True)

    logger.info(f"Loaded file '{filename}': {len(df)} rows, {len(df.columns)} columns")
    return df


def clean_phone_number(
    raw_phone: str,
    default_country_code: str = "1",
) -> tuple[str, bool]:
    """
    Clean and normalize a phone number.

    Strategy:
    1. Strip all non-digit characters
    2. If the number parses with phonenumbers library, use E.164 format
    3. Fallback: prepend country code if number seems too short

    Returns:
        Tuple of (cleaned_number, is_valid)
    """
    if not raw_phone or pd.isna(raw_phone):
        return "", False

    # Convert to string and remove formatting characters
    raw = str(raw_phone).strip()
    # Remove common formatting: spaces, dashes, parens, dots
    digits_only = re.sub(r"[\s\-\(\)\.\+]", "", raw)

    if not digits_only:
        return "", False

    # Try parsing with phonenumbers library
    try:
        # First try: assume number may already include country code
        parsed = phonenumbers.parse(f"+{digits_only}")
        if phonenumbers.is_valid_number(parsed):
            # Return E.164 without the + (Evolution API format)
            e164 = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
            return e164.lstrip("+"), True
    except phonenumbers.NumberParseException:
        pass

    # Second try: prepend default country code
    try:
        with_code = f"+{default_country_code}{digits_only}"
        parsed = phonenumbers.parse(with_code)
        if phonenumbers.is_valid_number(parsed):
            e164 = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
            return e164.lstrip("+"), True
    except phonenumbers.NumberParseException:
        pass

    # Last resort: return digits with country code prepended
    # (Some valid numbers may fail phonenumbers validation)
    logger.warning(f"Could not fully validate number: {raw_phone}")
    if not digits_only.startswith(default_country_code):
        return f"{default_country_code}{digits_only}", True
    return digits_only, True


def process_contacts(
    df: pd.DataFrame,
    phone_column: str,
    country_code: str = "1",
) -> pd.DataFrame:
    """
    Process the DataFrame to clean phone numbers.

    Adds two helper columns:
    - _cleaned_phone: The normalized phone number
    - _phone_valid: Boolean indicating if the number is valid

    Args:
        df: Source DataFrame
        phone_column: Column name containing raw phone numbers
        country_code: Default country code to apply

    Returns:
        DataFrame with additional helper columns
    """
    if phone_column not in df.columns:
        raise ValueError(
            f"Column '{phone_column}' not found. "
            f"Available columns: {list(df.columns)}"
        )

    # Apply cleaning to each phone number
    results = df[phone_column].apply(
        lambda x: clean_phone_number(str(x) if pd.notna(x) else "", country_code)
    )

    df = df.copy()
    df["_cleaned_phone"] = results.apply(lambda x: x[0])
    df["_phone_valid"] = results.apply(lambda x: x[1])

    valid_count = df["_phone_valid"].sum()
    invalid_count = len(df) - valid_count
    logger.info(
        f"Phone processing complete: {valid_count} valid, {invalid_count} invalid"
    )

    return df


def render_message(template: str, row: dict) -> str:
    """
    Render a message template by substituting column variables.

    Example:
        template: "Hello {Name}, your order {OrderID} is ready!"
        row: {"Name": "Alice", "OrderID": "12345"}
        result: "Hello Alice, your order 12345 is ready!"
    """
    message = template
    for key, value in row.items():
        # Skip internal helper columns
        if key.startswith("_"):
            continue
        # Replace {ColumnName} placeholders (case-sensitive)
        placeholder = "{" + str(key) + "}"
        safe_value = str(value) if pd.notna(value) else ""
        message = message.replace(placeholder, safe_value)
    return message
