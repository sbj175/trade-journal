#!/usr/bin/env python3
"""
Simple test script for tastytrade authentication
Run this after installing dependencies to test authentication
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_credentials():
    """Test credential decryption"""
    try:
        from cryptography.fernet import Fernet
        
        # Load key
        with open('crypto.key', 'rb') as f:
            key = f.read().strip()
        
        # Import encrypted credentials
        from encrypted_credentials import ENCRYPTED_USERNAME, ENCRYPTED_PASSWORD
        
        # Decrypt
        cipher = Fernet(key)
        username = cipher.decrypt(ENCRYPTED_USERNAME).decode()
        password = cipher.decrypt(ENCRYPTED_PASSWORD).decode()
        
        print(f"✓ Credentials decrypted successfully")
        print(f"  Username: {username[:3]}***")
        print(f"  Password: {'*' * len(password)}")
        
        return username, password
        
    except Exception as e:
        print(f"✗ Credential decryption failed: {e}")
        return None, None

def test_tastytrade_auth(username, password):
    """Test tastytrade authentication"""
    try:
        from tastytrade import Session, Account
        
        print(f"\n🔗 Testing authentication with Tastytrade...")
        session = Session(username, password)
        print(f"✓ Session created successfully")
        
        # Test getting accounts
        accounts = Account.get(session)
        if accounts:
            print(f"✓ Found {len(accounts)} account(s)")
            account = accounts[0]
            print(f"  Account: {account.account_number}")
            return True
        else:
            print(f"✗ No accounts found")
            return False
            
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
        return False

def main():
    print("=== Tastytrade Authentication Test ===\n")
    
    # Test credential decryption
    username, password = test_credentials()
    
    if username and password:
        # Test tastytrade authentication
        success = test_tastytrade_auth(username, password)
        
        if success:
            print(f"\n🎉 All tests passed! Ready to sync trades.")
        else:
            print(f"\n❌ Authentication test failed.")
    else:
        print(f"\n❌ Credential test failed.")

if __name__ == "__main__":
    main()