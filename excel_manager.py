"""Excel infrastructure module for managing contacts, replies, and cycle history.

Provides atomic workbook initialization, validation, read/update/append operations
with duplicate prevention and locked-file detection using openpyxl.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select

from config import AppConfig, CONFIG

logger = logging.getLogger("linkedin_automation.excel")


class ExcelError(Exception):
    """Base exception for Excel file management operations."""


class ExcelFileLockedError(ExcelError):
    """Raised when an Excel workbook is locked or open in another application."""


class InvalidWorkbookStructureError(ExcelError):
    """Raised when an Excel workbook has missing sheets or unexpected header schemas."""


# Column Schemas
CONTACTS_SHEET = "Contacts"
CONTACTS_COLUMNS = [
    "Contact ID",
    "Contact Name",
    "Profile URL",
    "Eligibility Status",
    "Initial Message Status",
    "Initial Message Timestamp",
    "Reply Received",
    "Last Reply Timestamp",
    "Next Follow-up Due",
    "Follow-up Status",
    "Last Updated",
]

SCRAPED_REPLIES_SHEET = "ScrapedReplies"
SCRAPED_REPLIES_COLUMNS = [
    "Contact ID",
    "Contact Name",
    "Conversation ID",
    "Reply ID",
    "Reply Text",
    "Reply Timestamp",
    "Collection Timestamp",
    "Processing Status",
]

CONVERSATION_HISTORY_SHEET = "ConversationHistory"
CONVERSATION_HISTORY_COLUMNS = [
    "Contact ID",
    "Contact Name",
    "Conversation ID",
    "Message ID",
    "Sender Identifier",
    "Sender Name",
    "Message Direction",
    "Message Text",
    "Message Timestamp",
    "Collection Timestamp",
    "Processing Status",
]

CYCLE_HISTORY_SHEET = "CycleHistory"
CYCLE_HISTORY_COLUMNS = [
    "Cycle ID",
    "Contact ID",
    "Contact Name",
    "Initial Message Status",
    "Initial Message Timestamp",
    "Reply ID",
    "Reply Category",
    "Selected Template",
    "Response Status",
    "Response Timestamp",
    "Follow-up Due",
    "Follow-up Status",
    "Last Updated",
    "Error Details",
]


def _format_cell_value(val: Any) -> Any:
    """Format timestamps and non-primitive values consistently for Excel storage."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return val


def _atomic_save(wb: openpyxl.Workbook, target_path: Path) -> None:
    """Save an openpyxl workbook atomically via a temporary file and replace.

    Detects file lock permissions and provides clear error reporting.
    """
    target_path = Path(target_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Create temporary file in the same directory to allow atomic replacement
    temp_fd, temp_path_str = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=f".tmp_{target_path.stem}_",
        suffix=".xlsx",
    )
    os.close(temp_fd)
    temp_path = Path(temp_path_str)

    try:
        wb.save(temp_path)
        # Attempt atomic replace
        os.replace(temp_path, target_path)
    except PermissionError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        msg = (
            f"The workbook '{target_path.name}' is currently locked or open in Excel/another program. "
            f"Please close it and retry. Details: {exc}"
        )
        logger.error(msg)
        raise ExcelFileLockedError(msg) from exc
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        msg = f"Failed to save workbook '{target_path.name}': {exc}"
        logger.error(msg)
        raise ExcelError(msg) from exc


def _create_or_load_workbook(
    file_path: Path, sheet_name: str, headers: Sequence[str]
) -> openpyxl.Workbook:
    """Create a workbook with the specified sheet and headers, or load existing."""
    file_path = Path(file_path).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if not file_path.exists():
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        ws.append(list(headers))
        _atomic_save(wb, file_path)
        logger.info("Created workbook '%s' with sheet '%s'.", file_path.name, sheet_name)
        return wb

    # Load existing
    try:
        wb = openpyxl.load_workbook(file_path)
    except PermissionError as exc:
        raise ExcelFileLockedError(
            f"Workbook '{file_path.name}' cannot be opened because it is locked: {exc}"
        ) from exc
    except Exception as exc:
        raise ExcelError(f"Could not read workbook '{file_path.name}': {exc}") from exc

    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(title=sheet_name)
        ws.append(list(headers))
        _atomic_save(wb, file_path)
        logger.info("Added sheet '%s' to existing workbook '%s'.", sheet_name, file_path.name)
    else:
        # Check if empty sheet
        ws = wb[sheet_name]
        if ws.max_row == 0 or (ws.max_row == 1 and all(cell.value is None for cell in ws[1])):
            ws.delete_rows(1, ws.max_row or 1)
            ws.append(list(headers))
            _atomic_save(wb, file_path)

    return wb


def validate_workbook(
    file_path: Path,
    expected_sheet: str,
    expected_headers: Sequence[str],
) -> bool:
    """Validate that the workbook exists, contains expected sheet, and headers match schema."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise InvalidWorkbookStructureError(f"Workbook does not exist: {path}")

    try:
        wb = openpyxl.load_workbook(path, read_only=True)
    except PermissionError as exc:
        raise ExcelFileLockedError(f"Cannot read '{path.name}', file is locked: {exc}") from exc
    except Exception as exc:
        raise ExcelError(f"Error opening '{path.name}': {exc}") from exc

    try:
        if expected_sheet not in wb.sheetnames:
            raise InvalidWorkbookStructureError(
                f"Sheet '{expected_sheet}' not found in workbook '{path.name}'. "
                f"Found sheets: {wb.sheetnames}"
            )

        ws = wb[expected_sheet]
        rows = list(ws.iter_rows(values_only=True, max_row=1))
        if not rows or not rows[0]:
            raise InvalidWorkbookStructureError(
                f"Workbook '{path.name}' sheet '{expected_sheet}' has no header row."
            )

        actual_headers = [str(col).strip() if col is not None else "" for col in rows[0]]
        # Check each expected header
        for i, expected in enumerate(expected_headers):
            if i >= len(actual_headers) or actual_headers[i] != expected:
                raise InvalidWorkbookStructureError(
                    f"Workbook '{path.name}' header mismatch at column {i+1}. "
                    f"Expected '{expected}', found '{actual_headers[i] if i < len(actual_headers) else 'None'}'."
                )
        return True
    finally:
        wb.close()


def initialize_workbooks(config: Optional[AppConfig] = None) -> None:
    """Initialize all three Excel workbooks with required sheets and headers."""
    cfg = config or CONFIG
    cfg.ensure_directories()

    _create_or_load_workbook(cfg.contacts_workbook_path, CONTACTS_SHEET, CONTACTS_COLUMNS)
    validate_workbook(cfg.contacts_workbook_path, CONTACTS_SHEET, CONTACTS_COLUMNS)

    _create_or_load_workbook(cfg.scraped_replies_workbook_path, SCRAPED_REPLIES_SHEET, SCRAPED_REPLIES_COLUMNS)
    validate_workbook(cfg.scraped_replies_workbook_path, SCRAPED_REPLIES_SHEET, SCRAPED_REPLIES_COLUMNS)

    _create_or_load_workbook(cfg.automation_cycles_workbook_path, CYCLE_HISTORY_SHEET, CYCLE_HISTORY_COLUMNS)
    validate_workbook(cfg.automation_cycles_workbook_path, CYCLE_HISTORY_SHEET, CYCLE_HISTORY_COLUMNS)

    logger.info("All three workbooks initialized and validated successfully.")


def load_contacts(file_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read all contact rows from contacts.xlsx into a list of dictionaries."""
    path = Path(file_path or CONFIG.contacts_workbook_path).resolve()
    if not path.exists():
        logger.warning("Contacts workbook '%s' does not exist.", path)
        return []

    validate_workbook(path, CONTACTS_SHEET, CONTACTS_COLUMNS)

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[CONTACTS_SHEET]
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) <= 1:
            return []

        headers = [str(h).strip() for h in rows[0]]
        contacts: List[Dict[str, Any]] = []

        for row in rows[1:]:
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            item = {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}
            contacts.append(item)

        return contacts
    finally:
        wb.close()


def update_contact_status(
    contact_data: Dict[str, Any],
    file_path: Optional[Path] = None,
) -> bool:
    """Update or append a contact record in contacts.xlsx keyed by 'Contact ID'.

    Returns True if an existing record was updated, False if a new record was appended.
    """
    path = Path(file_path or CONFIG.contacts_workbook_path).resolve()
    _create_or_load_workbook(path, CONTACTS_SHEET, CONTACTS_COLUMNS)

    wb = openpyxl.load_workbook(path)
    try:
        ws = wb[CONTACTS_SHEET]
        contact_id = str(contact_data.get("Contact ID") or "").strip()
        if not contact_id:
            raise ExcelError("Cannot update contact without a non-empty 'Contact ID'.")

        header_row = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        header_map = {name: idx + 1 for idx, name in enumerate(header_row)}

        # Find existing contact row by Contact ID
        target_row_idx: Optional[int] = None
        for row_idx in range(2, ws.max_row + 1):
            cell_val = str(ws.cell(row=row_idx, column=header_map["Contact ID"]).value or "").strip()
            if cell_val == contact_id:
                target_row_idx = row_idx
                break

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated_data = dict(contact_data)
        updated_data.setdefault("Last Updated", now_str)

        is_update = target_row_idx is not None
        if is_update:
            # Update cells in existing row
            for col_name, val in updated_data.items():
                if col_name in header_map:
                    ws.cell(row=target_row_idx, column=header_map[col_name]).value = _format_cell_value(val)
        else:
            # Append new row
            new_row_values = [
                _format_cell_value(updated_data.get(col_name, ""))
                for col_name in CONTACTS_COLUMNS
            ]
            ws.append(new_row_values)

        _atomic_save(wb, path)
        return is_update
    finally:
        wb.close()


def append_scraped_replies(
    replies: Sequence[Dict[str, Any]],
    file_path: Optional[Path] = None,
) -> int:
    """Append scraped reply rows to scraped_replies.xlsx, preventing duplicates by Reply ID.

    Returns the number of new records actually appended.
    """
    path = Path(file_path or CONFIG.scraped_replies_workbook_path).resolve()
    _create_or_load_workbook(path, SCRAPED_REPLIES_SHEET, SCRAPED_REPLIES_COLUMNS)

    wb = openpyxl.load_workbook(path)
    try:
        ws = wb[SCRAPED_REPLIES_SHEET]
        header_row = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        header_map = {name: idx + 1 for idx, name in enumerate(header_row)}

        # Collect existing Reply IDs
        existing_reply_ids = set()
        reply_id_col = header_map.get("Reply ID")
        if reply_id_col:
            for row_idx in range(2, ws.max_row + 1):
                val = ws.cell(row=row_idx, column=reply_id_col).value
                if val is not None and str(val).strip():
                    existing_reply_ids.add(str(val).strip())

        appended_count = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for reply in replies:
            reply_id = str(reply.get("Reply ID") or "").strip()
            # If reply ID exists and is already in workbook, skip duplicate
            if reply_id and reply_id in existing_reply_ids:
                logger.debug("Skipping duplicate Reply ID: %s", reply_id)
                continue

            row_data = dict(reply)
            row_data.setdefault("Collection Timestamp", now_str)
            row_data.setdefault("Processing Status", "new")

            row_cells = [
                _format_cell_value(row_data.get(col_name, ""))
                for col_name in SCRAPED_REPLIES_COLUMNS
            ]
            ws.append(row_cells)
            if reply_id:
                existing_reply_ids.add(reply_id)
            appended_count += 1

        if appended_count > 0:
            _atomic_save(wb, path)

        return appended_count
    finally:
        wb.close()


def append_cycle_history(
    cycle_records: Sequence[Dict[str, Any]],
    file_path: Optional[Path] = None,
) -> int:
    """Append records to automation_cycles.xlsx, avoiding duplicate (Cycle ID, Contact ID, Reply ID) entries.

    Returns the count of new entries added.
    """
    path = Path(file_path or CONFIG.automation_cycles_workbook_path).resolve()
    _create_or_load_workbook(path, CYCLE_HISTORY_SHEET, CYCLE_HISTORY_COLUMNS)

    wb = openpyxl.load_workbook(path)
    try:
        ws = wb[CYCLE_HISTORY_SHEET]
        header_row = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        header_map = {name: idx + 1 for idx, name in enumerate(header_row)}

        # Build existing keys to prevent duplicates
        existing_keys = set()
        cycle_col = header_map.get("Cycle ID")
        contact_col = header_map.get("Contact ID")
        reply_col = header_map.get("Reply ID")

        for row_idx in range(2, ws.max_row + 1):
            c_id = str(ws.cell(row=row_idx, column=cycle_col).value or "").strip() if cycle_col else ""
            cnt_id = str(ws.cell(row=row_idx, column=contact_col).value or "").strip() if contact_col else ""
            r_id = str(ws.cell(row=row_idx, column=reply_col).value or "").strip() if reply_col else ""
            if c_id or cnt_id or r_id:
                existing_keys.add((c_id, cnt_id, r_id))

        appended_count = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for rec in cycle_records:
            c_id = str(rec.get("Cycle ID") or "").strip()
            cnt_id = str(rec.get("Contact ID") or "").strip()
            r_id = str(rec.get("Reply ID") or "").strip()
            key = (c_id, cnt_id, r_id)

            if key in existing_keys and any(key):
                logger.debug("Skipping duplicate cycle history record: %s", key)
                continue

            row_data = dict(rec)
            row_data.setdefault("Last Updated", now_str)

            row_cells = [
                _format_cell_value(row_data.get(col_name, ""))
                for col_name in CYCLE_HISTORY_COLUMNS
            ]
            ws.append(row_cells)
            if any(key):
                existing_keys.add(key)
            appended_count += 1

        if appended_count > 0:
            _atomic_save(wb, path)

        return appended_count
    finally:
        wb.close()


def append_conversation_messages(
    messages: Sequence[Dict[str, Any]],
    file_path: Optional[Path] = None,
) -> int:
    """Append conversation message rows to ConversationHistory sheet in scraped_replies.xlsx.

    Avoids duplicating records based on Message ID or (Conversation ID, Message ID).
    Returns the number of new records actually appended.
    """
    path = Path(file_path or CONFIG.scraped_replies_workbook_path).resolve()
    # Make sure workbook exists
    _create_or_load_workbook(path, SCRAPED_REPLIES_SHEET, SCRAPED_REPLIES_COLUMNS)

    wb = openpyxl.load_workbook(path)
    try:
        if CONVERSATION_HISTORY_SHEET not in wb.sheetnames:
            ws = wb.create_sheet(title=CONVERSATION_HISTORY_SHEET)
            ws.append(list(CONVERSATION_HISTORY_COLUMNS))
        else:
            ws = wb[CONVERSATION_HISTORY_SHEET]

        header_row = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        header_map = {name: idx + 1 for idx, name in enumerate(header_row)}

        existing_message_ids = set()
        msg_id_col = header_map.get("Message ID")
        conv_id_col = header_map.get("Conversation ID")

        for row_idx in range(2, ws.max_row + 1):
            m_id = str(ws.cell(row=row_idx, column=msg_id_col).value or "").strip() if msg_id_col else ""
            c_id = str(ws.cell(row=row_idx, column=conv_id_col).value or "").strip() if conv_id_col else ""
            if m_id:
                existing_message_ids.add(m_id)
            if c_id and m_id:
                existing_message_ids.add((c_id, m_id))

        appended_count = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for msg in messages:
            msg_id = str(msg.get("Message ID") or msg.get("external_message_id") or "").strip()
            conv_id = str(msg.get("Conversation ID") or msg.get("external_conversation_id") or "").strip()
            if msg_id and (msg_id in existing_message_ids or (conv_id, msg_id) in existing_message_ids):
                logger.debug("Skipping duplicate Message ID in ConversationHistory: %s", msg_id)
                continue

            row_data = dict(msg)
            row_data.setdefault("Collection Timestamp", now_str)
            row_data.setdefault("Processing Status", "new")

            row_cells = [
                _format_cell_value(row_data.get(col_name, ""))
                for col_name in CONVERSATION_HISTORY_COLUMNS
            ]
            ws.append(row_cells)
            if msg_id:
                existing_message_ids.add(msg_id)
                if conv_id:
                    existing_message_ids.add((conv_id, msg_id))
            appended_count += 1

        if appended_count > 0:
            _atomic_save(wb, path)

        return appended_count
    finally:
        wb.close()


def rebuild_scraped_replies_workbook(
    file_path: Optional[Path] = None,
    config: Optional[AppConfig] = None,
    engine: Optional[Any] = None,
) -> int:
    """Reconstruct scraped_replies.xlsx directly from persisted SQLite reply records.

    Preserves original file as a backup if it exists and creates the workbook anew.
    Reconstructs ScrapedReplies and ConversationHistory worksheets.
    Returns the count of reply records exported.
    """
    import shutil
    from database import get_db_session
    from models import ConversationMessage, Reply

    cfg = config or CONFIG
    target_path = Path(file_path or cfg.scraped_replies_workbook_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing workbook if it exists
    if target_path.exists():
        backup_path = target_path.with_suffix(".bak")
        try:
            shutil.copy2(target_path, backup_path)
            logger.info("Preserved existing workbook backup at '%s'", backup_path)
        except Exception as exc:
            logger.warning("Could not create backup of '%s': %s", target_path, exc)

    # Fetch all replies and conversation messages from SQLite
    with get_db_session(engine=engine, config=cfg) as session:
        replies = session.scalars(select(Reply).order_by(Reply.id.asc())).all()
        records: List[Dict[str, Any]] = []
        for r in replies:
            c_name = r.contact.name if r.contact else ""
            c_id = str(r.contact_id) if r.contact_id is not None else ""
            r_id = r.external_reply_id or f"rep_{r.id}"
            conv_id = getattr(r, "conversation_id", None) or ""
            records.append({
                "Contact ID": c_id,
                "Contact Name": c_name,
                "Conversation ID": conv_id,
                "Reply ID": r_id,
                "Reply Text": r.reply_text,
                "Reply Timestamp": _format_cell_value(r.reply_timestamp),
                "Collection Timestamp": _format_cell_value(r.collected_at),
                "Processing Status": r.processing_status,
            })

        # Fetch conversation messages if table exists
        conv_records: List[Dict[str, Any]] = []
        try:
            conv_messages = session.scalars(
                select(ConversationMessage).order_by(ConversationMessage.id.asc())
            ).all()
            for cm in conv_messages:
                c_name = cm.contact.name if cm.contact else (cm.sender_name or "")
                c_id = str(cm.contact_id) if cm.contact_id is not None else ""
                m_id = cm.external_message_id or f"msg_{cm.id}"
                conv_id = cm.external_conversation_id or ""
                conv_records.append({
                    "Contact ID": c_id,
                    "Contact Name": c_name,
                    "Conversation ID": conv_id,
                    "Message ID": m_id,
                    "Sender Identifier": cm.sender_identifier or "",
                    "Sender Name": cm.sender_name or "",
                    "Message Direction": cm.message_direction,
                    "Message Text": cm.message_text,
                    "Message Timestamp": _format_cell_value(cm.message_timestamp),
                    "Collection Timestamp": _format_cell_value(cm.collected_at),
                    "Processing Status": cm.processing_status,
                })
        except Exception as exc:
            logger.debug("Could not fetch conversation messages during rebuild: %s", exc)

    # Create new workbook and worksheet with standard schema
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SCRAPED_REPLIES_SHEET
    ws.append(list(SCRAPED_REPLIES_COLUMNS))

    for rec in records:
        row_cells = [_format_cell_value(rec.get(col, "")) for col in SCRAPED_REPLIES_COLUMNS]
        ws.append(row_cells)

    # If conversation records exist, add ConversationHistory sheet
    if conv_records:
        ws_conv = wb.create_sheet(title=CONVERSATION_HISTORY_SHEET)
        ws_conv.append(list(CONVERSATION_HISTORY_COLUMNS))
        for crec in conv_records:
            crow_cells = [_format_cell_value(crec.get(col, "")) for col in CONVERSATION_HISTORY_COLUMNS]
            ws_conv.append(crow_cells)

    _atomic_save(wb, target_path)
    logger.info("Rebuilt '%s' with %d reply records and %d conversation messages from SQLite.", target_path.name, len(records), len(conv_records))
    return len(records)

