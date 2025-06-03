#!/usr/bin/env python3
"""
Google Authentication Setup Helper
"""

import os
import json

def check_credentials_file():
    """Check if credentials.json exists and is valid"""
    if not os.path.exists('credentials.json'):
        print("❌ credentials.json not found")
        return False
    
    try:
        with open('credentials.json', 'r') as f:
            creds = json.load(f)
        
        # Check if it has the right structure
        if 'installed' in creds and 'client_id' in creds['installed']:
            print("✅ credentials.json found and appears valid")
            print(f"   Project ID: {creds['installed'].get('project_id', 'unknown')}")
            print(f"   Client ID: {creds['installed']['client_id'][:20]}...")
            return True
        else:
            print("❌ credentials.json has invalid format")
            return False
            
    except Exception as e:
        print(f"❌ Error reading credentials.json: {e}")
        return False

def clean_old_tokens():
    """Remove old authentication tokens"""
    files_to_remove = ['token.json', 'token.pickle']
    removed = []
    
    for file in files_to_remove:
        if os.path.exists(file):
            os.remove(file)
            removed.append(file)
    
    if removed:
        print(f"🧹 Removed old tokens: {', '.join(removed)}")
    else:
        print("ℹ️  No old tokens to remove")

def test_auth():
    """Test authentication with current credentials"""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        
        print("\n🔐 Testing Google authentication...")
        
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        
        print("📝 Manual authentication required:")
        print("1. Copy the URL that appears below")
        print("2. Open it in your web browser")
        print("3. Complete the authorization")
        print("4. The browser will try to redirect to localhost (this may fail)")
        print("5. If redirect fails, copy the full URL from your browser address bar")
        print("\nStarting authentication...\n")
        
        # Try local server first, fallback to manual
        try:
            creds = flow.run_local_server(port=0, open_browser=False)
        except Exception as server_error:
            print(f"Local server method failed: {server_error}")
            print("\nTrying alternative method...")
            
            # Manual flow
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"\nPlease visit this URL to authorize the application:")
            print(f"\n{auth_url}\n")
            
            auth_code = input("Enter the authorization code (or full redirect URL): ").strip()
            
            # Handle if user pasted the full URL instead of just the code
            if auth_code.startswith('http'):
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(auth_code)
                query_params = parse_qs(parsed.query)
                if 'code' in query_params:
                    auth_code = query_params['code'][0]
                else:
                    raise ValueError("Could not extract authorization code from URL")
            
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
        
        # Save credentials
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("\n✅ Authentication successful!")
        print("📁 Token saved to token.json")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        
        if "invalid_client" in str(e):
            print("\n💡 This error usually means:")
            print("   • The OAuth client was deleted or disabled")
            print("   • Wrong credentials.json file")
            print("   • Google Cloud project issues")
            print("\n🔧 Solutions:")
            print("   1. Create new OAuth credentials in Google Cloud Console")
            print("   2. Download fresh credentials.json")
            print("   3. Make sure Google Sheets API is enabled")
        
        return False

def main():
    print("=== Google Authentication Setup ===\n")
    
    # Check credentials file
    if not check_credentials_file():
        print("\n📋 To fix this:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project or select existing")
        print("3. Enable Google Sheets API")
        print("4. Create OAuth 2.0 credentials (Desktop application)")
        print("5. Download as credentials.json")
        return
    
    # Clean old tokens
    clean_old_tokens()
    
    # Test authentication
    success = test_auth()
    
    if success:
        print("\n🎉 Setup complete! You can now run:")
        print("   python3 src/sync_trades.py --days 7")
    else:
        print("\n❌ Setup failed. Check the error messages above.")

if __name__ == "__main__":
    main()