"""
Abstract base class for file storage
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, BinaryIO


class FileStorage(ABC):
    """Abstract interface for file storage"""

    @abstractmethod
    def upload(self, source_path: str, destination_folder: str, new_filename: Optional[str] = None) -> str:
        """
        Upload a file to destination folder.
        Returns: path/identifier of uploaded file
        """
        pass

    @abstractmethod
    def download(self, file_identifier: str) -> bytes:
        """Download and return file contents as bytes"""
        pass

    @abstractmethod
    def list_files(self, folder_path: str) -> List[str]:
        """List all files in a folder"""
        pass

    @abstractmethod
    def delete(self, file_identifier: str) -> bool:
        """Delete a file"""
        pass

    @abstractmethod
    def file_exists(self, file_identifier: str) -> bool:
        """Check if file exists"""
        pass

    @abstractmethod
    def create_folder(self, folder_path: str) -> bool:
        """Create a folder if it doesn't exist"""
        pass
