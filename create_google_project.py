#!/usr/bin/env python3
"""
Guide for creating a new Google Cloud project for Trade Journal
"""

def print_setup_instructions():
    """Print step-by-step instructions for setting up Google Cloud project"""
    
    print("=" * 60)
    print("   GOOGLE CLOUD PROJECT SETUP GUIDE")
    print("=" * 60)
    
    print("\n🚀 STEP 1: Create New Project")
    print("-" * 30)
    print("1. Go to: https://console.cloud.google.com/")
    print("2. Click the project dropdown (top left)")
    print("3. Click 'New Project'")
    print("4. Project name: 'Trade Journal Personal'")
    print("5. Click 'Create'")
    print("6. Wait for project creation, then select the new project")
    
    print("\n📚 STEP 2: Enable Google Sheets API")
    print("-" * 35)
    print("1. Go to 'APIs & Services' > 'Library'")
    print("2. Search for 'Google Sheets API'")
    print("3. Click on it and press 'Enable'")
    print("4. Wait for it to be enabled")
    
    print("\n🔐 STEP 3: Configure OAuth Consent Screen")
    print("-" * 40)
    print("1. Go to 'APIs & Services' > 'OAuth consent screen'")
    print("2. Choose 'External' (unless you have Google Workspace)")
    print("3. Fill in REQUIRED fields only:")
    print("   • App name: 'Trade Journal'")
    print("   • User support email: YOUR_EMAIL@gmail.com")
    print("   • Developer contact: YOUR_EMAIL@gmail.com")
    print("4. Click 'Save and Continue'")
    print("5. SCOPES page: Click 'Save and Continue' (skip)")
    print("6. TEST USERS page:")
    print("   • Click 'Add Users'")
    print("   • Enter YOUR_EMAIL@gmail.com")
    print("   • Click 'Save'")
    print("7. Click 'Save and Continue'")
    print("8. Review and click 'Back to Dashboard'")
    
    print("\n🔑 STEP 4: Create OAuth Credentials")
    print("-" * 35)
    print("1. Go to 'APIs & Services' > 'Credentials'")
    print("2. Click 'Create Credentials' > 'OAuth client ID'")
    print("3. Application type: 'Desktop application'")
    print("4. Name: 'Trade Journal Desktop'")
    print("5. Click 'Create'")
    print("6. Click 'Download JSON' on the popup")
    print("7. Save as 'credentials.json' in your project folder")
    print("   (Replace the existing file)")
    
    print("\n🧪 STEP 5: Test Authentication")
    print("-" * 30)
    print("1. Run: python3 setup_google_auth.py")
    print("2. Follow the authentication prompts")
    print("3. If successful, run: python3 src/sync_trades.py --days 7")
    
    print("\n" + "=" * 60)
    print("💡 IMPORTANT NOTES:")
    print("• Make sure to add YOUR email as a test user")
    print("• The app will stay in 'testing' mode - this is fine for personal use")
    print("• You can add up to 100 test users if needed")
    print("• No Google verification needed for personal use")
    print("=" * 60)

def check_current_project():
    """Check the current credentials file"""
    import os
    import json
    
    print("\n🔍 CURRENT PROJECT INFO:")
    print("-" * 25)
    
    if os.path.exists('credentials.json'):
        try:
            with open('credentials.json', 'r') as f:
                creds = json.load(f)
            
            project_id = creds.get('installed', {}).get('project_id', 'unknown')
            client_id = creds.get('installed', {}).get('client_id', 'unknown')
            
            print(f"• Project ID: {project_id}")
            print(f"• Client ID: {client_id[:30]}...")
            print(f"• Status: ❌ Current project has access issues")
            
        except Exception as e:
            print(f"• Error reading credentials: {e}")
    else:
        print("• No credentials.json found")
    
    print(f"• Recommendation: Create new project with fresh credentials")

def main():
    print_setup_instructions()
    check_current_project()
    
    print(f"\n🎯 QUICK START:")
    print(f"If you want to keep your current project, just add your email")
    print(f"as a test user in the OAuth consent screen.")
    print(f"\nOtherwise, follow the full guide above for a clean setup.")

if __name__ == "__main__":
    main()