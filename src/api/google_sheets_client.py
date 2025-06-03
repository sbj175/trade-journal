import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
import pickle

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


class GoogleSheetsClient:
    def __init__(self):
        self.spreadsheet_id = os.getenv('GOOGLE_SHEETS_SPREADSHEET_ID')
        self.credentials_file = os.getenv('GOOGLE_SHEETS_CREDENTIALS_FILE', 'credentials.json')
        self.creds = None
        self.service = None
        
    def authenticate(self) -> bool:
        """Authenticate with Google Sheets API"""
        try:
            # The file token.json stores the user's access and refresh tokens
            if os.path.exists('token.json'):
                self.creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            
            # If there are no (valid) credentials available, let the user log in
            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    self.creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, SCOPES)
                    self.creds = flow.run_local_server(port=0)
                
                # Save the credentials for the next run
                with open('token.json', 'w') as token:
                    token.write(self.creds.to_json())
            
            self.service = build('sheets', 'v4', credentials=self.creds)
            logger.info("Successfully authenticated with Google Sheets")
            return True
            
        except Exception as e:
            logger.error(f"Google Sheets authentication failed: {str(e)}")
            return False
    
    def create_sheets_if_not_exist(self) -> bool:
        """Create necessary sheets if they don't exist"""
        try:
            # Get spreadsheet metadata
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            existing_sheets = {sheet['properties']['title'] for sheet in spreadsheet['sheets']}
            
            required_sheets = ['Dashboard', 'Trades', 'Trade Legs', 'Transactions', 'Positions', 'Account Summary', 'Performance Analysis']
            sheets_to_create = [sheet for sheet in required_sheets if sheet not in existing_sheets]
            
            if sheets_to_create:
                requests = []
                for sheet_name in sheets_to_create:
                    requests.append({
                        'addSheet': {
                            'properties': {
                                'title': sheet_name
                            }
                        }
                    })
                
                body = {'requests': requests}
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body=body
                ).execute()
                
                logger.info(f"Created sheets: {', '.join(sheets_to_create)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create sheets: {str(e)}")
            return False
    
    def write_transactions(self, transactions: List[Dict[str, Any]]) -> bool:
        """Write transactions to the Transactions sheet"""
        try:
            if not transactions:
                logger.info("No transactions to write")
                return True
            
            # Prepare headers
            headers = [
                'Date/Time', 'Type', 'Sub Type', 'Symbol', 'Underlying',
                'Description', 'Quantity', 'Price', 'Commission', 'Fees',
                'Net Value', 'Action', 'Instrument Type', 'Transaction ID'
            ]
            
            # Prepare data rows
            rows = [headers]
            for tx in transactions:
                row = [
                    tx.get('executed_at', ''),
                    tx.get('transaction_type', ''),
                    tx.get('transaction_sub_type', ''),
                    tx.get('symbol', ''),
                    tx.get('underlying_symbol', ''),
                    tx.get('description', ''),
                    tx.get('quantity', ''),
                    tx.get('price', ''),
                    tx.get('commission', 0),
                    (tx.get('regulatory_fees', 0) or 0) + (tx.get('clearing_fees', 0) or 0),
                    tx.get('net_value', ''),
                    tx.get('action', ''),
                    tx.get('instrument_type', ''),
                    tx.get('id', '')
                ]
                rows.append(row)
            
            # Clear existing data and write new data
            self._clear_sheet('Transactions')
            
            body = {
                'values': rows
            }
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range='Transactions!A1',
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            logger.info(f"Written {len(rows) - 1} transactions to sheet")
            
            # Format the sheet
            self._format_transactions_sheet(len(rows))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write transactions: {str(e)}")
            return False
    
    def write_positions(self, positions: List[Dict[str, Any]]) -> bool:
        """Write positions to the Positions sheet"""
        try:
            # Prepare headers
            headers = [
                'Symbol', 'Underlying', 'Type', 'Quantity', 'Direction',
                'Avg Open Price', 'Close Price', 'Market Value', 'Cost',
                'Day P&L', 'Total P&L', '% Change'
            ]
            
            # Prepare data rows
            rows = [headers]
            for pos in positions:
                # Calculate P&L - handle cost_effect properly
                cost_effect_str = pos.get('cost_effect', 'Debit')
                market_value = float(pos.get('market_value', 0) or 0)
                
                # For cost, we need to calculate from quantity and average price
                quantity = float(pos.get('quantity', 0) or 0)
                avg_price = float(pos.get('average_open_price', 0) or 0)
                multiplier = float(pos.get('multiplier', 1) or 1)
                
                # Calculate cost basis
                cost = quantity * avg_price * multiplier
                if cost_effect_str == 'Credit':
                    cost = -cost  # Credit positions have negative cost basis
                
                # Calculate P&L
                pnl = market_value - cost
                pnl_percent = (pnl / abs(cost) * 100) if cost != 0 else 0
                
                row = [
                    pos.get('symbol', ''),
                    pos.get('underlying_symbol', ''),
                    pos.get('instrument_type', ''),
                    pos.get('quantity', ''),
                    pos.get('quantity_direction', ''),
                    pos.get('average_open_price', ''),
                    pos.get('close_price', ''),
                    market_value,
                    cost,
                    pos.get('realized_day_gain', 0),
                    pnl,
                    f"{pnl_percent:.2f}%"
                ]
                rows.append(row)
            
            # Clear existing data and write new data
            self._clear_sheet('Positions')
            
            body = {
                'values': rows
            }
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range='Positions!A1',
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            logger.info(f"Written {len(rows) - 1} positions to sheet")
            
            # Format the sheet
            self._format_positions_sheet(len(rows))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write positions: {str(e)}")
            return False
    
    def write_account_summary(self, balances: Dict[str, Any]) -> bool:
        """Write account summary to the Account Summary sheet"""
        try:
            # Prepare data
            headers = ['Metric', 'Value', 'Last Updated']
            rows = [
                headers,
                ['Account Number', balances.get('account_number', ''), balances.get('updated_at', '')],
                ['Cash Balance', f"${balances.get('cash_balance', 0):,.2f}", ''],
                ['Net Liquidating Value', f"${balances.get('net_liquidating_value', 0):,.2f}", ''],
                ['Equity Buying Power', f"${balances.get('equity_buying_power', 0):,.2f}", ''],
                ['Derivative Buying Power', f"${balances.get('derivative_buying_power', 0):,.2f}", ''],
                ['Day Trading Buying Power', f"${balances.get('day_trading_buying_power', 0):,.2f}", ''],
                ['Cash Available to Withdraw', f"${balances.get('cash_available_to_withdraw', 0):,.2f}", ''],
                ['Maintenance Requirement', f"${balances.get('maintenance_requirement', 0):,.2f}", ''],
                ['Pending Cash', f"${balances.get('pending_cash', 0):,.2f}", ''],
                ['Long Equity Value', f"${balances.get('long_equity_value', 0):,.2f}", ''],
                ['Short Equity Value', f"${balances.get('short_equity_value', 0):,.2f}", ''],
                ['Margin Equity', f"${balances.get('margin_equity', 0):,.2f}", ''],
            ]
            
            # Clear existing data and write new data
            self._clear_sheet('Account Summary')
            
            body = {
                'values': rows
            }
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range='Account Summary!A1',
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            logger.info("Written account summary to sheet")
            
            # Format the sheet
            self._format_account_summary_sheet()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write account summary: {str(e)}")
            return False
    
    def write_trades(self, trade_data: Dict[str, List[List]]) -> bool:
        """Write trade data to the Trades and Trade Legs sheets"""
        try:
            # Write Trades sheet with preservation of user notes
            if 'trades' in trade_data:
                # First, read existing notes if the sheet exists
                existing_notes = self._read_existing_trade_notes()
                
                # Update trade data with preserved notes
                updated_trades_data = self._merge_trade_notes(trade_data['trades'], existing_notes)
                
                self._clear_sheet('Trades')
                
                body = {'values': updated_trades_data}
                
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='Trades!A1',
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                
                logger.info(f"Written {len(updated_trades_data) - 1} trades to sheet")
                
                # Format the trades sheet with user interface enhancements
                self._format_trades_sheet_app(len(updated_trades_data))
            
            # Write Trade Legs sheet
            if 'trade_legs' in trade_data:
                self._clear_sheet('Trade Legs')
                
                body = {'values': trade_data['trade_legs']}
                
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='Trade Legs!A1',
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                
                logger.info(f"Written {len(trade_data['trade_legs']) - 1} trade legs to sheet")
                
                # Format the trade legs sheet
                self._format_trade_legs_sheet(len(trade_data['trade_legs']))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write trade data: {str(e)}")
            return False
    
    def _clear_sheet(self, sheet_name: str):
        """Clear all data from a sheet"""
        try:
            self.service.spreadsheets().values().clear(
                spreadsheetId=self.spreadsheet_id,
                range=f'{sheet_name}!A:Z'
            ).execute()
        except Exception as e:
            logger.warning(f"Failed to clear sheet {sheet_name}: {str(e)}")
    
    def _format_transactions_sheet(self, num_rows: int):
        """Apply formatting to the Transactions sheet"""
        try:
            sheet_id = self._get_sheet_id('Transactions')
            if sheet_id is None:
                return
            
            requests = [
                # Freeze header row
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'gridProperties': {
                                'frozenRowCount': 1
                            }
                        },
                        'fields': 'gridProperties.frozenRowCount'
                    }
                },
                # Bold header row
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat.bold'
                    }
                },
                # Format currency columns
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': 7,  # Price column
                            'endColumnIndex': 11     # Through Net Value column
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '$#,##0.00'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format Transactions sheet: {str(e)}")
    
    def _format_positions_sheet(self, num_rows: int):
        """Apply formatting to the Positions sheet"""
        try:
            sheet_id = self._get_sheet_id('Positions')
            if sheet_id is None:
                return
            
            requests = [
                # Freeze header row
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'gridProperties': {
                                'frozenRowCount': 1
                            }
                        },
                        'fields': 'gridProperties.frozenRowCount'
                    }
                },
                # Bold header row
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat.bold'
                    }
                },
                # Format currency columns
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': 5,  # Avg Open Price column
                            'endColumnIndex': 11    # Through Total P&L column
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '$#,##0.00'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format Positions sheet: {str(e)}")
    
    def _format_account_summary_sheet(self):
        """Apply formatting to the Account Summary sheet"""
        try:
            sheet_id = self._get_sheet_id('Account Summary')
            if sheet_id is None:
                return
            
            requests = [
                # Bold header row and first column
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat.bold'
                    }
                },
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startColumnIndex': 0,
                            'endColumnIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat.bold'
                    }
                }
            ]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format Account Summary sheet: {str(e)}")
    
    def _format_trades_sheet(self, num_rows: int):
        """Apply formatting to the Trades sheet"""
        try:
            sheet_id = self._get_sheet_id('Trades')
            if sheet_id is None:
                return
            
            requests = [
                # Freeze header row
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'gridProperties': {
                                'frozenRowCount': 1
                            }
                        },
                        'fields': 'gridProperties.frozenRowCount'
                    }
                },
                # Bold header row
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat.bold'
                    }
                },
                # Format currency columns (Net Premium, Current P&L)
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': 7,  # Net Premium column
                            'endColumnIndex': 9     # Through Current P&L column
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '$#,##0.00'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format Trades sheet: {str(e)}")
    
    def _format_trade_legs_sheet(self, num_rows: int):
        """Apply formatting to the Trade Legs sheet"""
        try:
            sheet_id = self._get_sheet_id('Trade Legs')
            if sheet_id is None:
                return
            
            requests = [
                # Freeze header row
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'gridProperties': {
                                'frozenRowCount': 1
                            }
                        },
                        'fields': 'gridProperties.frozenRowCount'
                    }
                },
                # Bold header row
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat.bold'
                    }
                },
                # Format price columns
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': 7,  # Entry Price column
                            'endColumnIndex': 9     # Through Exit Price column
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '$#,##0.00'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format Trade Legs sheet: {str(e)}")
    
    def _read_existing_trade_notes(self) -> Dict[str, Dict]:
        """Read existing trade notes from the Trades sheet"""
        try:
            # Try to read existing trades data
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Trades!A:L'  # Assuming notes are in columns J, K, L
            ).execute()
            
            values = result.get('values', [])
            if not values or len(values) < 2:
                return {}
            
            # Find column indices for notes
            headers = values[0]
            trade_id_col = headers.index('Trade ID') if 'Trade ID' in headers else 0
            
            notes_cols = {}
            for i, header in enumerate(headers):
                if 'Original Notes' in header:
                    notes_cols['original'] = i
                elif 'Current Notes' in header:
                    notes_cols['current'] = i
                elif 'Status' in header:
                    notes_cols['status'] = i
                elif 'Tags' in header:
                    notes_cols['tags'] = i
            
            # Extract existing notes by trade ID
            existing_notes = {}
            for row in values[1:]:
                if len(row) > trade_id_col:
                    trade_id = row[trade_id_col]
                    if trade_id:
                        existing_notes[trade_id] = {}
                        for note_type, col_idx in notes_cols.items():
                            if col_idx < len(row):
                                existing_notes[trade_id][note_type] = row[col_idx]
            
            return existing_notes
            
        except Exception as e:
            logger.warning(f"Could not read existing notes: {str(e)}")
            return {}
    
    def _merge_trade_notes(self, trades_data: List[List], existing_notes: Dict) -> List[List]:
        """Merge existing user notes with updated trade data"""
        if not trades_data:
            return trades_data
        
        # Find column indices
        headers = trades_data[0]
        trade_id_col = headers.index('Trade ID') if 'Trade ID' in headers else 0
        
        notes_cols = {}
        for i, header in enumerate(headers):
            if 'Original Notes' in header:
                notes_cols['original'] = i
            elif 'Current Notes' in header:
                notes_cols['current'] = i
            elif 'Status' in header:
                notes_cols['status'] = i
            elif 'Tags' in header:
                notes_cols['tags'] = i
        
        # Update data rows with preserved notes
        updated_data = [headers]  # Keep headers
        
        for row in trades_data[1:]:
            if len(row) > trade_id_col:
                trade_id = row[trade_id_col]
                
                # If we have existing notes for this trade, preserve them
                if trade_id in existing_notes:
                    for note_type, col_idx in notes_cols.items():
                        if col_idx < len(row) and note_type in existing_notes[trade_id]:
                            existing_value = existing_notes[trade_id][note_type]
                            if existing_value:  # Only preserve non-empty values
                                row[col_idx] = existing_value
            
            updated_data.append(row)
        
        return updated_data
    
    def _format_trades_sheet_app(self, num_rows: int):
        """Format Trades sheet as an application interface"""
        try:
            sheet_id = self._get_sheet_id('Trades')
            if sheet_id is None:
                return
            
            requests = [
                # Freeze header row and first few columns
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'gridProperties': {
                                'frozenRowCount': 1,
                                'frozenColumnCount': 3  # Freeze ID, Underlying, Strategy
                            }
                        },
                        'fields': 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount'
                    }
                },
                # Bold header row with background color
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True,
                                    'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}
                                },
                                'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.8}
                            }
                        },
                        'fields': 'userEnteredFormat.textFormat,userEnteredFormat.backgroundColor'
                    }
                },
                # Format currency columns
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': 7,  # Net Premium column
                            'endColumnIndex': 9     # Through Current P&L column
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '$#,##0.00'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
            
            # Add data validation for Status column
            status_col = self._find_column_index('Trades', 'Status')
            if status_col is not None:
                requests.append({
                    'setDataValidation': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': status_col,
                            'endColumnIndex': status_col + 1
                        },
                        'rule': {
                            'condition': {
                                'type': 'ONE_OF_LIST',
                                'values': [
                                    {'userEnteredValue': 'Open'},
                                    {'userEnteredValue': 'Closed'},
                                    {'userEnteredValue': 'Rolled'},
                                    {'userEnteredValue': 'Expired'},
                                    {'userEnteredValue': 'Assigned'},
                                    {'userEnteredValue': 'Partially Closed'}
                                ]
                            },
                            'showCustomUi': True,
                            'strict': False
                        }
                    }
                })
            
            # Add conditional formatting for status
            requests.extend(self._get_status_conditional_formatting(sheet_id, status_col, num_rows))
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format Trades sheet as app: {str(e)}")
    
    def _find_column_index(self, sheet_name: str, column_name: str) -> Optional[int]:
        """Find the index of a column by name"""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f'{sheet_name}!1:1'
            ).execute()
            
            headers = result.get('values', [[]])[0]
            return headers.index(column_name) if column_name in headers else None
            
        except Exception:
            return None
    
    def _get_status_conditional_formatting(self, sheet_id: int, status_col: Optional[int], num_rows: int) -> List[Dict]:
        """Get conditional formatting rules for trade status"""
        if status_col is None:
            return []
        
        return [
            # Green for Closed trades
            {
                'addConditionalFormatRule': {
                    'rule': {
                        'ranges': [{
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': status_col,
                            'endColumnIndex': status_col + 1
                        }],
                        'booleanRule': {
                            'condition': {
                                'type': 'TEXT_EQ',
                                'values': [{'userEnteredValue': 'Closed'}]
                            },
                            'format': {
                                'backgroundColor': {'red': 0.8, 'green': 1, 'blue': 0.8}
                            }
                        }
                    },
                    'index': 0
                }
            },
            # Orange for Open trades
            {
                'addConditionalFormatRule': {
                    'rule': {
                        'ranges': [{
                            'sheetId': sheet_id,
                            'startRowIndex': 1,
                            'endRowIndex': num_rows,
                            'startColumnIndex': status_col,
                            'endColumnIndex': status_col + 1
                        }],
                        'booleanRule': {
                            'condition': {
                                'type': 'TEXT_EQ',
                                'values': [{'userEnteredValue': 'Open'}]
                            },
                            'format': {
                                'backgroundColor': {'red': 1, 'green': 0.9, 'blue': 0.7}
                            }
                        }
                    },
                    'index': 1
                }
            }
        ]
    
    def create_dashboard_sheet(self) -> bool:
        """Create an interactive dashboard sheet"""
        try:
            # Dashboard data with formulas that reference other sheets
            dashboard_data = [
                ['TRADE JOURNAL DASHBOARD', '', '', '', '', ''],
                ['', '', '', '', '', ''],
                ['PERFORMANCE SUMMARY', '', '', '', '', ''],
                ['Total Trades', '=COUNTA(Trades!A:A)-1', '', '', '', ''],
                ['Open Trades', '=COUNTIF(Trades!F:F,"Open")', '', '', '', ''],
                ['Closed Trades', '=COUNTIF(Trades!F:F,"Closed")', '', '', '', ''],
                ['Total P&L', '=SUM(Trades!I:I)', '', '', '', ''],
                ['Win Rate', '=COUNTIFS(Trades!F:F,"Closed",Trades!I:I,">0")/COUNTIF(Trades!F:F,"Closed")', '', '', '', ''],
                ['', '', '', '', '', ''],
                ['STRATEGY BREAKDOWN', '', '', '', '', ''],
                ['Strategy', 'Count', 'Total P&L', 'Avg P&L', 'Win Rate', ''],
                ['Iron Condor', '=COUNTIF(Trades!C:C,"Iron Condor")', '=SUMIF(Trades!C:C,"Iron Condor",Trades!I:I)', '=AVERAGEIF(Trades!C:C,"Iron Condor",Trades!I:I)', '=COUNTIFS(Trades!C:C,"Iron Condor",Trades!I:I,">0")/COUNTIF(Trades!C:C,"Iron Condor")', ''],
                ['Vertical Spread', '=COUNTIF(Trades!C:C,"Vertical Spread")', '=SUMIF(Trades!C:C,"Vertical Spread",Trades!I:I)', '=AVERAGEIF(Trades!C:C,"Vertical Spread",Trades!I:I)', '=COUNTIFS(Trades!C:C,"Vertical Spread",Trades!I:I,">0")/COUNTIF(Trades!C:C,"Vertical Spread")', ''],
                ['Covered Call', '=COUNTIF(Trades!C:C,"Covered Call")', '=SUMIF(Trades!C:C,"Covered Call",Trades!I:I)', '=AVERAGEIF(Trades!C:C,"Covered Call",Trades!I:I)', '=COUNTIFS(Trades!C:C,"Covered Call",Trades!I:I,">0")/COUNTIF(Trades!C:C,"Covered Call")', ''],
                ['', '', '', '', '', ''],
                ['RECENT ACTIVITY', '', '', '', '', ''],
                ['Last Sync', '=NOW()', '', '', '', ''],
                ['', '', '', '', '', ''],
                ['QUICK ACTIONS', '', '', '', '', ''],
                ['Click Trade Journal menu to sync latest trades', '', '', '', '', ''],
            ]
            
            self._clear_sheet('Dashboard')
            
            body = {'values': dashboard_data}
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range='Dashboard!A1',
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            # Format the dashboard
            self._format_dashboard()
            
            logger.info("Created dashboard sheet")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create dashboard: {str(e)}")
            return False
    
    def _format_dashboard(self):
        """Format the dashboard sheet"""
        try:
            sheet_id = self._get_sheet_id('Dashboard')
            if sheet_id is None:
                return
            
            requests = [
                # Title formatting
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 0,
                            'endRowIndex': 1,
                            'startColumnIndex': 0,
                            'endColumnIndex': 6
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True,
                                    'fontSize': 16,
                                    'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}
                                },
                                'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.8},
                                'horizontalAlignment': 'CENTER'
                            }
                        },
                        'fields': 'userEnteredFormat'
                    }
                },
                # Section headers
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 2,
                            'endRowIndex': 3
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {
                                    'bold': True,
                                    'fontSize': 12
                                },
                                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                            }
                        },
                        'fields': 'userEnteredFormat'
                    }
                },
                # Currency formatting for P&L columns
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 6,
                            'endRowIndex': 7,
                            'startColumnIndex': 1,
                            'endColumnIndex': 2
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'CURRENCY',
                                    'pattern': '$#,##0.00'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                },
                # Percentage formatting for win rate
                {
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 7,
                            'endRowIndex': 8,
                            'startColumnIndex': 1,
                            'endColumnIndex': 2
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'PERCENT',
                                    'pattern': '0.0%'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
            
            body = {'requests': requests}
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=body
            ).execute()
            
        except Exception as e:
            logger.warning(f"Failed to format dashboard: {str(e)}")
    
    def _get_sheet_id(self, sheet_name: str) -> Optional[int]:
        """Get the sheet ID for a given sheet name"""
        try:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            for sheet in spreadsheet['sheets']:
                if sheet['properties']['title'] == sheet_name:
                    return sheet['properties']['sheetId']
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get sheet ID: {str(e)}")
            return None