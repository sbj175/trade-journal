#!/usr/bin/env python3
"""
Webhook server for handling sync requests from Google Sheets
This can be deployed to a cloud service like Google Cloud Run, AWS Lambda, or Heroku
"""

import os
import subprocess
from flask import Flask, request, jsonify
from loguru import logger
import threading

app = Flask(__name__)

# Configure logging
logger.add(
    "logs/webhook_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO"
)


def run_sync_in_background(days: int, spreadsheet_id: str):
    """Run the sync script in the background"""
    try:
        # Set the spreadsheet ID environment variable if provided
        env = os.environ.copy()
        if spreadsheet_id:
            env['GOOGLE_SHEETS_SPREADSHEET_ID'] = spreadsheet_id
        
        # Run the sync script
        result = subprocess.run(
            ['python', 'src/sync_trades.py', '--days', str(days)],
            capture_output=True,
            text=True,
            env=env
        )
        
        if result.returncode == 0:
            logger.info(f"Sync completed successfully for {days} days")
        else:
            logger.error(f"Sync failed: {result.stderr}")
            
    except Exception as e:
        logger.error(f"Error running sync: {str(e)}")


@app.route('/webhook/sync-trades', methods=['POST'])
def sync_trades_webhook():
    """Handle sync request from Google Sheets"""
    try:
        # Get request data
        data = request.get_json()
        
        # Extract parameters
        days = data.get('days', 30)
        full_refresh = data.get('fullRefresh', False)
        spreadsheet_id = data.get('spreadsheetId', '')
        
        logger.info(f"Received sync request: days={days}, fullRefresh={full_refresh}")
        
        # Start sync in background thread
        thread = threading.Thread(
            target=run_sync_in_background,
            args=(days, spreadsheet_id)
        )
        thread.start()
        
        # Return immediate response
        return jsonify({
            'status': 'success',
            'message': f'Sync started for {days} days',
            'days': days,
            'fullRefresh': full_refresh
        }), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    # For local testing
    app.run(host='0.0.0.0', port=8080, debug=True)