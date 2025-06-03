#!/usr/bin/env python3
"""
Manual Google OAuth authentication
Use this if the automatic browser opening doesn't work
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def manual_auth():
    """Perform manual OAuth authentication"""
    try:
        credentials_file = os.getenv('GOOGLE_SHEETS_CREDENTIALS_FILE', 'credentials.json')
        
        if not os.path.exists(credentials_file):
            print(f"Error: {credentials_file} not found")
            print("Please download your OAuth credentials from Google Cloud Console")
            return False
        
        print("Starting manual OAuth flow...")
        
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_file, SCOPES)
        
        # Use run_console instead of run_local_server for manual auth
        creds = flow.run_console()
        
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("✅ Authentication successful!")
        print("Token saved to token.json")
        print("You can now run the sync script normally.")
        
        return True
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return False

if __name__ == "__main__":
    manual_auth()