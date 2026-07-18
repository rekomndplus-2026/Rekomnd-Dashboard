"""
Contacts/file upload router.
Handles Excel/CSV file processing and column mapping.
"""

import logging
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from models.schemas import ProcessFileResponse
from services.excel_processor import (
    load_file,
    process_contacts,
    store_dataframe,
    retrieve_dataframe,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contacts", tags=["Contacts"])

# Max file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


@router.post("/upload", response_model=ProcessFileResponse)
async def upload_contacts_file(
    file: UploadFile = File(..., description="Excel or CSV file with contacts"),
):
    """
    Upload and parse a contacts file.

    Returns:
    - Column names (for the user to map phone column)
    - Preview of first 10 rows
    - A file_id to reference this data in the send endpoint
    """
    # Validate file extension
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file_ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 10MB."
        )

    # Write to temp file for pandas to read
    with tempfile.NamedTemporaryFile(
        suffix=file_ext, delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Load into DataFrame
        df = load_file(tmp_path, file.filename or "upload")

        if df.empty:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file appears to be empty."
            )

        if len(df.columns) == 0:
            raise HTTPException(
                status_code=400,
                detail="No columns found in the file."
            )

        # Store DataFrame for later use
        file_id = store_dataframe(df)

        # Build preview (first 10 rows, convert NaN to empty string)
        preview_df = df.head(10).fillna("")
        preview = preview_df.to_dict(orient="records")

        logger.info(
            f"File '{file.filename}' processed: "
            f"{len(df)} rows, columns: {list(df.columns)}"
        )

        return ProcessFileResponse(
            total_rows=len(df),
            columns=list(df.columns),
            preview=preview,
            file_id=file_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process file: {str(e)}"
        )
    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


@router.post("/preview-cleaned")
async def preview_cleaned_numbers(
    file_id: str = Form(...),
    phone_column: str = Form(...),
    country_code: str = Form(default="1"),
):
    """
    Preview how phone numbers will look after cleaning.
    Allows users to verify the processing before sending.
    """
    df = retrieve_dataframe(file_id)
    if df is None:
        raise HTTPException(
            status_code=404,
            detail="File not found. Please re-upload your file."
        )

    try:
        processed = process_contacts(df, phone_column, country_code)

        # Show sample of cleaned numbers
        sample = processed[
            [phone_column, "_cleaned_phone", "_phone_valid"]
        ].head(20).fillna("")

        invalid_count = (~processed["_phone_valid"]).sum()

        return {
            "sample": sample.to_dict(orient="records"),
            "total": len(processed),
            "valid": int(processed["_phone_valid"].sum()),
            "invalid": int(invalid_count),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
