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

            # Create user with home directory.
            # Shell nologin por defecto: los clientes NO tienen acceso SSH/shell
            # salvo que se active explícitamente (opt-in). El acceso SFTP se
            # gestiona aparte vía el grupo 'sftponly' (chroot, internal-sftp).
            logger.info(f"Creating user: {username}")
            self.execute_command([
                "useradd",
                "-m",           # Create home directory
                "-s", "/usr/sbin/nologin",
                "-d", home_dir,
                username
            ])

            # Home a 711: el dueño entra, pero otros usuarios NO pueden listar
            # su contenido (evita que un cliente husmee el home de otro).
            # www-data sí puede atravesar para servir la web (web/ es 750 user:www-data).
            self.execute_command(["chmod", "711", home_dir])

            # Set password if provided — chpasswd por stdin (sin shell, sin
            # exponer el password en la línea de comandos ni en los logs).
            if password:
                self.execute_with_input(["chpasswd"], f"{username}:{password}\n")

            # Estructura de directorios estilo Hestia:
            # /home/username/         755 user:user   (adduser lo crea)
            #   web/                  750 user:www-data  ← nginx puede atravesar
            #   tmp/                  750 user:user
            web_root = get_web_root(username)
            tmp_dir = f"{home_dir}/tmp"

            self.create_directory(web_root, mode=0o750)
            self.change_ownership(web_root, username, "www-data")  # nginx puede atravesar

            self.create_directory(tmp_dir, mode=0o750)
            self.change_ownership(tmp_dir, username)

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
            # chpasswd por stdin (sin shell, sin exponer el password en ps/logs)
            self.execute_with_input(["chpasswd"], f"{username}:{new_password}\n")
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
