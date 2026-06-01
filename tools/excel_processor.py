"""
Excel processing utilities
"""
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List
import openpyxl
from openpyxl.utils import get_column_letter


def read_excel_sheet(filepath: Path, sheet_name: str) -> pd.DataFrame:
    """Read Excel sheet into DataFrame"""
    return pd.read_excel(filepath, sheet_name=sheet_name)


def write_excel_sheet(filepath: Path, sheet_name: str, df: pd.DataFrame):
    """Write DataFrame to Excel sheet"""
    with pd.ExcelWriter(filepath, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def get_template_placeholders(template_path: Path) -> List[str]:
    """Extract placeholder names from Excel template"""
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active
    placeholders = []

    for row in ws.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                # Find patterns like {{PLACEHOLDER}} or {PLACEHOLDER}
                import re
                matches = re.findall(r"\{\{([A-Z_]+)\}\}", cell.value)
                placeholders.extend(matches)

    return list(set(placeholders))


def fill_template(
    template_path: Path, output_path: Path, values: Dict[str, Any]
):
    """Fill Excel template with values"""
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    # Replace placeholders in cells
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                content = cell.value
                for key, value in values.items():
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in content:
                        content = content.replace(placeholder, str(value))
                cell.value = content

    wb.save(output_path)


def copy_template(src_path: Path, dest_path: Path):
    """Copy template file"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src_path, dest_path)
