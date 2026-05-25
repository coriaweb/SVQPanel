"""User management - create/delete system users"""

import logging
from .base import SystemManager
from .utils import validate_username, validate_email, get_home_directory, get_web_root

logger = logging.getLogger(__name__)


class UserManager(SystemManager):
    """Manage system users"""

    def __init__(self):
        super().__init__(require_root=True)

    def create_user(self, username: str, email: str, password: str = None) -> dict:
        """
        Create a new system user

        Args:
            username: System username (3-31 chars, alphanumeric+underscore)
            email: Email address
            password: Password (hashed before use)

        Returns:
            {'success': True, 'home_dir': '/home/user', ...}
        """
        # Validate inputs
        if not validate_username(username):
            raise ValueError(f"Invalid username format: {username}")

        if not validate_email(email):
            raise ValueError(f"Invalid email format: {email}")

        home_dir = get_home_directory(username)

        try:
            # Check if user already exists
            ret, _, _ = self.execute_command(["id", username], check=False)
            if ret == 0:
                raise ValueError(f"User already exists: {username}")

            # Create user with home directory
            logger.info(f"Creating user: {username}")
            self.execute_command([
                "useradd",
                "-m",           # Create home directory
                "-s", "/bin/bash",
                "-d", home_dir,
                username
            ])

            # Set password if provided (usando chpasswd via stdin)
            if password:
                self.execute_command(
                    f"echo '{username}:{password}' | chpasswd"
                )

            # Estructura de directorios estilo Hestia:
            # /home/username/
            #   web/          → dominios (creados al añadir cada dominio)
            #   tmp/          → archivos temporales
            web_root = get_web_root(username)
            tmp_dir = f"{home_dir}/tmp"

            for directory in [web_root, tmp_dir]:
                self.create_directory(directory, mode=0o750)
                self.change_ownership(directory, username)

            # .bashrc si no existe
            bashrc_path = f"{home_dir}/.bashrc"
            if not self.file_exists(bashrc_path):
                self.execute_command(["touch", bashrc_path])
                self.change_ownership(bashrc_path, username)

            logger.info(f"User created successfully: {username}")
            return {
                "success": True,
                "username": username,
                "email": email,
                "home_dir": home_dir,
                "web_root": web_root,
            }

        except Exception as e:
            logger.error(f"Failed to create user {username}: {str(e)}")
            raise

    def delete_user(self, username: str, remove_home: bool = True) -> dict:
        """
        Delete a system user

        Args:
            username: System username
            remove_home: Delete home directory

        Returns:
            {'success': True, 'deleted_user': 'username'}
        """
        if not validate_username(username):
            raise ValueError(f"Invalid username format: {username}")

        try:
            logger.info(f"Deleting user: {username}")

            # Check if user exists
            self.execute_command(["id", username])

            # Kill all user processes
            self.execute_command([
                "killall", "-u", username
            ], check=False)

            # Delete user
            cmd = ["userdel"]
            if remove_home:
                cmd.append("-r")
            cmd.append(username)

            self.execute_command(cmd)

            logger.info(f"User deleted: {username}")
            return {
                "success": True,
                "deleted_user": username
            }

        except Exception as e:
            logger.error(f"Failed to delete user {username}: {str(e)}")
            raise

    def user_exists(self, username: str) -> bool:
        """Check if user exists"""
        try:
            self.execute_command(["id", username])
            return True
        except:
            return False

    def change_password(self, username: str, new_password: str) -> dict:
        """Change user password"""
        if not validate_username(username):
            raise ValueError(f"Invalid username format: {username}")

        if not self.user_exists(username):
            raise ValueError(f"User does not exist: {username}")

        try:
            logger.info(f"Changing password for: {username}")
            # Use echo + chpasswd for non-interactive password change
            self.execute_command(
                f"echo '{username}:{new_password}' | chpasswd"
            )
            logger.info(f"Password changed: {username}")
            return {
                "success": True,
                "username": username,
                "message": "Password changed successfully"
            }
        except Exception as e:
            logger.error(f"Failed to change password: {str(e)}")
            raise

    def list_users(self) -> list:
        """List all users with UID >= 1000"""
        try:
            _, output, _ = self.execute_command([
                "awk",
                "-F:",
                "$3 >= 1000 {print $1}",
                "/etc/passwd"
            ])
            users = output.strip().split("\n")
            return [u for u in users if u]
        except Exception as e:
            logger.error(f"Failed to list users: {str(e)}")
            return []
