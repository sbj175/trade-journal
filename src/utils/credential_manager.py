"""
Credential manager for handling encrypted credentials
"""

import os
from cryptography.fernet import Fernet
from loguru import logger
from typing import Tuple, Optional


class CredentialManager:
    def __init__(self):
        self.key_file = 'crypto.key'
        self.cipher = None
        self._load_key()
    
    def _load_key(self):
        """Load the encryption key"""
        try:
            if os.path.exists(self.key_file):
                with open(self.key_file, 'rb') as f:
                    key = f.read().strip()
                self.cipher = Fernet(key)
                logger.debug("Encryption key loaded successfully")
            else:
                logger.error(f"Encryption key file '{self.key_file}' not found")
        except Exception as e:
            logger.error(f"Failed to load encryption key: {str(e)}")
    
    def get_tastytrade_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        """Get decrypted Tastytrade credentials"""
        try:
            # First try to import encrypted credentials
            from encrypted_credentials import ENCRYPTED_USERNAME, ENCRYPTED_PASSWORD
            
            if not self.cipher:
                logger.error("Cipher not initialized")
                return None, None
            
            # Decrypt credentials
            username = self.cipher.decrypt(ENCRYPTED_USERNAME).decode('utf-8')
            password = self.cipher.decrypt(ENCRYPTED_PASSWORD).decode('utf-8')
            
            logger.debug("Successfully decrypted Tastytrade credentials")
            return username, password
            
        except ImportError:
            logger.warning("Encrypted credentials not found, falling back to environment variables")
            # Fall back to environment variables
            username = os.getenv('TASTYTRADE_USERNAME')
            password = os.getenv('TASTYTRADE_PASSWORD')
            
            if username and password:
                logger.debug("Using credentials from environment variables")
                return username, password
            else:
                logger.error("No credentials found in encrypted file or environment")
                return None, None
                
        except Exception as e:
            logger.error(f"Failed to decrypt credentials: {str(e)}")
            return None, None
    
    @staticmethod
    def encrypt_credentials(username: str, password: str, key_file: str = 'crypto.key') -> bool:
        """
        Encrypt credentials and save to file (utility method)
        
        Usage:
            from src.utils.credential_manager import CredentialManager
            CredentialManager.encrypt_credentials('your_username', 'your_password')
        """
        try:
            # Generate or load key
            if os.path.exists(key_file):
                with open(key_file, 'rb') as f:
                    key = f.read().strip()
            else:
                key = Fernet.generate_key()
                with open(key_file, 'wb') as f:
                    f.write(key)
                logger.info(f"Generated new encryption key: {key_file}")
            
            # Encrypt credentials
            cipher = Fernet(key)
            encrypted_username = cipher.encrypt(username.encode())
            encrypted_password = cipher.encrypt(password.encode())
            
            # Write encrypted credentials
            with open('encrypted_credentials.py', 'w') as f:
                f.write("# Encrypted credentials - Do not modify manually\n")
                f.write(f"ENCRYPTED_USERNAME = {encrypted_username}\n")
                f.write(f"ENCRYPTED_PASSWORD = {encrypted_password}\n")
            
            logger.info("Credentials encrypted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to encrypt credentials: {str(e)}")
            return False