"""Base class for all system managers"""

import subprocess
import logging
import os
from typing import Tuple

logger = logging.getLogger(__name__)


class SystemManager:
    """Base class for managing system operations"""

    def __init__(self, require_root: bool = True):
        self.require_root = require_root
        if require_root:
            self._validate_root()

    def _validate_root(self):
        """Ensure running as root"""
        if os.geteuid() != 0:
            raise PermissionError("This operation requires root privileges")

    def execute_command(self, cmd: list, check: bool = True) -> Tuple[int, str, str]:
        """
        Execute a system command safely.

        Args:
            cmd: Command as list ['ls', '-la']
            check: Raise exception on non-zero exit

        Returns:
            (return_code, stdout, stderr)
        """
        try:
            logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )

            if check and result.returncode != 0:
                logger.error(f"Command failed: {result.stderr}")
                raise subprocess.CalledProcessError(
                    result.returncode,
                    cmd,
                    output=result.stdout,
                    stderr=result.stderr
                )

            logger.info(f"Command succeeded with code {result.returncode}")
            return result.returncode, result.stdout, result.stderr

        except subprocess.CalledProcessError as e:
            logger.error(f"Command error: {e.stderr}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise

    def file_exists(self, path: str) -> bool:
        """Check if file/directory exists"""
        return os.path.exists(path)

    def create_directory(self, path: str, mode: int = 0o755):
        """Create directory with permissions"""
        try:
            os.makedirs(path, mode=mode, exist_ok=True)
            logger.info(f"Created directory: {path}")
        except Exception as e:
            logger.error(f"Failed to create directory: {str(e)}")
            raise

    def delete_directory(self, path: str):
        """Delete directory recursively"""
        try:
            self.execute_command(["rm", "-rf", path])
            logger.info(f"Deleted directory: {path}")
        except Exception as e:
            logger.error(f"Failed to delete directory: {str(e)}")
            raise

    def change_ownership(self, path: str, user: str, group: str = None):
        """Change file/directory ownership"""
        if group is None:
            group = user
        try:
            self.execute_command(["chown", f"{user}:{group}", path])
            logger.info(f"Changed ownership: {path} → {user}:{group}")
        except Exception as e:
            logger.error(f"Failed to change ownership: {str(e)}")
            raise

    def reload_service(self, service: str):
        """Reload a systemd service"""
        try:
            self.execute_command(["systemctl", "reload", service])
            logger.info(f"Reloaded service: {service}")
        except Exception as e:
            logger.error(f"Failed to reload service: {str(e)}")
            raise
