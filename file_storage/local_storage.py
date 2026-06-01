"""
Local filesystem implementation of FileStorage
"""
import shutil
from pathlib import Path
from typing import List, Optional
from file_storage.base_storage import FileStorage
import config


class LocalFileStorage(FileStorage):
    """Local filesystem-based file storage"""

    def __init__(self, base_dir: Path = None):
        self.base_dir = Path(base_dir) if base_dir else config.DATA_DIR
        self.base_dir.mkdir(exist_ok=True)

    def upload(self, source_path: str, destination_folder: str, new_filename: Optional[str] = None) -> str:
        """Upload a file to destination folder"""
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        dest_folder = self.base_dir / destination_folder
        dest_folder.mkdir(parents=True, exist_ok=True)

        # Use provided filename or original filename
        filename = new_filename or source_path.name
        dest_path = dest_folder / filename

        # Copy file
        shutil.copy2(source_path, dest_path)

        # Return relative path
        return str(dest_path.relative_to(self.base_dir))

    def download(self, file_identifier: str) -> bytes:
        """Download and return file contents"""
        file_path = self.base_dir / file_identifier
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_identifier}")
        return file_path.read_bytes()

    def list_files(self, folder_path: str) -> List[str]:
        """List all files in a folder"""
        folder = self.base_dir / folder_path
        if not folder.exists():
            return []
        files = [f.name for f in folder.iterdir() if f.is_file()]
        return sorted(files)

    def delete(self, file_identifier: str) -> bool:
        """Delete a file"""
        file_path = self.base_dir / file_identifier
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def file_exists(self, file_identifier: str) -> bool:
        """Check if file exists"""
        file_path = self.base_dir / file_identifier
        return file_path.exists() and file_path.is_file()

    def create_folder(self, folder_path: str) -> bool:
        """Create a folder"""
        folder = self.base_dir / folder_path
        folder.mkdir(parents=True, exist_ok=True)
        return True

    def get_full_path(self, file_identifier: str) -> Path:
        """Get full path for a file identifier"""
        return self.base_dir / file_identifier
