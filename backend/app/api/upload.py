"""Upload API endpoint for dataset ingestion and session creation.

This module is responsible for uploading datasets and creating analysis sessions.
It does NOT execute analytics, call the LLM, build charts, or explain results.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.dependencies import get_dataset_profiler, get_session_manager
from app.profiler import DatasetProfiler
from app.session import DatasetSessionManager

logger = logging.getLogger(__name__)

# Constants
MAX_UPLOAD_SIZE_MB = 50
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


class UploadResponse(BaseModel):
    """Response model for successful dataset upload."""

    session_id: str = Field(..., description="Unique session identifier for the uploaded dataset.")
    filename: str = Field(..., description="Original filename provided by the user.")
    rows: int = Field(..., description="Number of rows in the dataset.")
    columns: int = Field(..., description="Number of columns in the dataset.")
    uploaded_at: str = Field(..., description="ISO timestamp of when the upload was processed.")
    profile: dict[str, Any] = Field(..., description="Dataset profile from DatasetProfiler.")


router = APIRouter(prefix="/upload", tags=["upload"])


def _validate_file_extension(filename: str) -> str:
    """Validate that the file has a supported extension.

    Args:
        filename: The filename to validate.

    Returns:
        The lowercase file extension.

    Raises:
        HTTPException: If the extension is not supported.
    """
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot be empty.",
        )

    path = Path(filename)
    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file extension '{extension}'. Supported types: {supported}.",
        )

    return extension


def _sanitize_filename(filename: str) -> str:
    """Sanitize the filename for safe storage.

    Args:
        filename: The original filename.

    Returns:
        A sanitized filename.
    """
    path = Path(filename)
    # Keep only the stem and extension, remove any path components
    sanitized_stem = path.stem
    # Replace any non-alphanumeric characters (except underscore and hyphen) with underscore
    sanitized_stem = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in sanitized_stem)
    return f"{sanitized_stem}{path.suffix}"


@router.post("/", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(..., description="Dataset file to upload (CSV, XLSX, XLS)."),
    session_manager: DatasetSessionManager = Depends(get_session_manager),
    profiler: DatasetProfiler = Depends(get_dataset_profiler),
) -> UploadResponse:
    """Upload a dataset file and create an analysis session.

    This endpoint accepts CSV and Excel files, validates them, profiles the dataset,
    and creates an in-memory session for subsequent analysis.

    Args:
        file: The uploaded file (multipart/form-data).
        session_manager: DatasetSessionManager instance (dependency injection).
        profiler: DatasetProfiler instance (dependency injection).

    Returns:
        UploadResponse containing session information and dataset profile.

    Raises:
        HTTPException: For validation errors, file processing errors, or session creation failures.
    """

    # Validate file exists
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided.",
        )

    # Validate file extension
    extension = _validate_file_extension(file.filename)

    # Sanitize filename for display
    display_filename = _sanitize_filename(file.filename)

    # Generate unique temporary filename
    temp_filename = f"{uuid.uuid4()}{extension}"
    temp_dir = Path.cwd() / "temp_uploads"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / temp_filename

    try:
        # Validate upload size before reading
        file_size = 0
        chunk_size = 8192

        # Read file content to validate and save
        with open(temp_path, "wb") as temp_file:
            while chunk := await file.read(chunk_size):
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File size exceeds maximum allowed size of {MAX_UPLOAD_SIZE_MB}MB.",
                    )
                temp_file.write(chunk)

        # Validate file is not empty
        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        # Profile the dataset
        try:
            profile = profiler.profile_file(str(temp_path))
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Temporary file not found during profiling.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Dataset validation failed: {exc}",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to parse dataset: {exc}",
            ) from exc
        except Exception as exc:
            logger.error(f"Unexpected profiling error: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to profile dataset.",
            ) from exc

        # Load dataframe for session creation
        try:
            dataframe = profiler._load_dataset(temp_path, extension)
        except Exception as exc:
            logger.error(f"Failed to load dataframe: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to load dataset: {exc}",
            ) from exc

        # Create session
        try:
            session_id = session_manager.create_session(
                dataframe=dataframe,
                filename=display_filename,
                profile=profile,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Session creation failed: {exc}",
            ) from exc
        except Exception as exc:
            logger.error(f"Unexpected session creation error: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create session.",
            ) from exc

        # Build response
        shape = profile.get("shape", {})
        rows = shape.get("rows", 0)
        columns = shape.get("columns", 0)
        uploaded_at = datetime.now(timezone.utc).isoformat()

        return UploadResponse(
            session_id=session_id,
            filename=display_filename,
            rows=rows,
            columns=columns,
            uploaded_at=uploaded_at,
            profile=profile,
        )

    finally:
        # Always clean up temporary file
        try:
            if temp_path.exists():
                temp_path.unlink()
                logger.debug(f"Cleaned up temporary file: {temp_path}")
        except Exception as exc:
            logger.warning(f"Failed to clean up temporary file {temp_path}: {exc}")
