#!/usr/bin/env python3
"""
Setup script for creating encrypted credentials
"""

import os
import sys
import getpass
from cryptography.fernet import Fernet

def setup_encrypted_credentials():
    """Interactive setup for encrypted credentials"""
    print("=== Tastytrade Trade Journal Credential Setup ===")
    print()
    
    # Check if encrypted credentials already exist
    if os.path.exists('encrypted_credentials.py'):
        response = input("Encrypted credentials already exist. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Setup cancelled.")
            return
    
    # Get credentials from user
    print("Enter your Tastytrade credentials:")
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    
    # Confirm password
    password_confirm = getpass.getpass("Confirm Password: ")
    if password != password_confirm:
        print("Error: Passwords do not match!")
        sys.exit(1)
    
    # Generate or use existing key
    key_file = 'crypto.key'
    if os.path.exists(key_file):
        print(f"\nUsing existing encryption key from {key_file}")
        with open(key_file, 'rb') as f:
            key = f.read().strip()
    else:
        print(f"\nGenerating new encryption key...")
        key = Fernet.generate_key()
        with open(key_file, 'wb') as f:
            f.write(key)
        print(f"Encryption key saved to {key_file}")
        print("IMPORTANT: Keep this key file safe and never share it!")
    
    # Encrypt credentials
    try:
        cipher = Fernet(key)
        encrypted_username = cipher.encrypt(username.encode())
        encrypted_password = cipher.encrypt(password.encode())
        
        # Write encrypted credentials
        with open('encrypted_credentials.py', 'w') as f:
            f.write("# Encrypted credentials - Do not modify manually\n")
            f.write(f"ENCRYPTED_USERNAME = {encrypted_username}\n")
            f.write(f"ENCRYPTED_PASSWORD = {encrypted_password}\n")
        
        print(f"\nEncrypted credentials saved to encrypted_credentials.py")
        print("\n✓ Setup complete!")
        print("\nYou can now run the sync script without storing credentials in plain text.")
        print("Make sure to keep crypto.key safe - you'll need it to decrypt your credentials.")
        
    except Exception as e:
        print(f"\nError encrypting credentials: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    setup_encrypted_credentials()