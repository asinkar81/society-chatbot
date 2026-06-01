"""
Stub for future Google Drive implementation
"""
from file_storage.base_storage import FileStorage
from typing import List, Optional


class GoogleDriveStorage(FileStorage):
    """Google Drive implementation (stub for future development)"""

    def __init__(self, credentials_file: str):
        self.credentials_file = credentials_file
        raise NotImplementedError("Google Drive integration coming in future release")

    def upload(self, source_path: str, destination_folder: str, new_filename: Optional[str] = None) -> str:
        pass

    def download(self, file_identifier: str) -> bytes:
        pass

    def list_files(self, folder_path: str) -> List[str]:
        pass

    def delete(self, file_identifier: str) -> bool:
        pass

    def file_exists(self, file_identifier: str) -> bool:
        pass

    def create_folder(self, folder_path: str) -> bool:
        pass
