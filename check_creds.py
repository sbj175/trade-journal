#!/usr/bin/env python3
"""
Simple credential checker - doesn't require external dependencies
"""

import os

def check_files():
    """Check if required files exist"""
    files_to_check = [
        'crypto.key',
        'encrypted_credentials.py'
    ]
    
    print("=== File Check ===")
    all_exist = True
    
    for file in files_to_check:
        if os.path.exists(file):
            print(f"✓ {file} exists")
        else:
            print(f"✗ {file} missing")
            all_exist = False
    
    return all_exist

def check_credentials():
    """Try to decrypt credentials using only built-in modules"""
    try:
        # Try to import and check basic structure
        print("\n=== Credential Check ===")
        
        # Check if crypto.key exists and has content
        if os.path.exists('crypto.key'):
            with open('crypto.key', 'rb') as f:
                key_content = f.read().strip()
            print(f"✓ Encryption key loaded ({len(key_content)} bytes)")
        else:
            print("✗ crypto.key not found")
            return False
        
        # Check if encrypted_credentials.py exists and can be imported
        if os.path.exists('encrypted_credentials.py'):
            # Try to read the file
            with open('encrypted_credentials.py', 'r') as f:
                content = f.read()
            
            if 'ENCRYPTED_USERNAME' in content and 'ENCRYPTED_PASSWORD' in content:
                print("✓ Encrypted credentials file format looks correct")
                
                # Try basic import (this will fail if there are syntax errors)
                try:
                    import encrypted_credentials
                    if hasattr(encrypted_credentials, 'ENCRYPTED_USERNAME') and hasattr(encrypted_credentials, 'ENCRYPTED_PASSWORD'):
                        print("✓ Encrypted credentials can be imported")
                        return True
                    else:
                        print("✗ Encrypted credentials missing required variables")
                        return False
                except Exception as e:
                    print(f"✗ Error importing encrypted credentials: {e}")
                    return False
            else:
                print("✗ Encrypted credentials file missing required variables")
                return False
        else:
            print("✗ encrypted_credentials.py not found")
            return False
            
    except Exception as e:
        print(f"✗ Error checking credentials: {e}")
        return False

def main():
    print("Simple Credential Checker")
    print("=" * 40)
    
    files_ok = check_files()
    creds_ok = check_credentials()
    
    print(f"\n=== Summary ===")
    if files_ok and creds_ok:
        print("✅ All checks passed!")
        print("\nNext steps:")
        print("1. Install dependencies: python3 -m pip install -r requirements.txt")
        print("2. Run the authentication test: python3 test_auth.py")
        print("3. Run the sync: python3 src/sync_trades.py --days 7")
    else:
        print("❌ Some checks failed.")
        print("\nTroubleshooting:")
        if not files_ok:
            print("- Make sure crypto.key and encrypted_credentials.py exist")
        if not creds_ok:
            print("- Run 'python3 setup_credentials.py' to set up credentials")

if __name__ == "__main__":
    main()