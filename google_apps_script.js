/**
 * Google Apps Script for Trade Journal
 * This script should be copied to your Google Sheet's Script Editor
 * 
 * Setup:
 * 1. Open your Google Sheet
 * 2. Go to Extensions > Apps Script
 * 3. Delete any existing code and paste this entire script
 * 4. Update the WEBHOOK_URL with your actual webhook endpoint
 * 5. Save and run onOpen() once to authorize
 */

// Configuration - Update this with your actual webhook URL
const WEBHOOK_URL = 'YOUR_WEBHOOK_URL_HERE'; // e.g., https://your-domain.com/webhook/sync-trades

/**
 * Creates custom menu when the spreadsheet opens
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Trade Journal')
    .addItem('🔄 Sync Trades (Last 30 Days)', 'syncTrades30Days')
    .addItem('📅 Sync Trades (Last 7 Days)', 'syncTrades7Days')
    .addItem('📊 Quick Sync (Today)', 'syncTradesToday')
    .addSeparator()
    .addItem('🎯 Go to Dashboard', 'goToDashboard')
    .addItem('📝 View All Trades', 'goToTrades')
    .addItem('🔍 Trade Lookup', 'showTradeLookup')
    .addSeparator()
    .addItem('✅ Mark Selected Trades as Closed', 'markTradesClosed')
    .addItem('🔄 Mark Selected Trades as Rolled', 'markTradesRolled')
    .addSeparator()
    .addItem('📈 Calculate Trade P&L', 'calculateTradePerformance')
    .addItem('🛠️ Settings', 'showSettings')
    .addToUi();
}

/**
 * Sync trades for the last 30 days
 */
function syncTrades30Days() {
  syncTrades(30);
}

/**
 * Sync trades for the last 7 days
 */
function syncTrades7Days() {
  syncTrades(7);
}

/**
 * Sync trades for today only
 */
function syncTradesToday() {
  syncTrades(1);
}

/**
 * Refresh all data (positions, balances, and last 30 days of trades)
 */
function refreshAllData() {
  syncTrades(30, true);
}

/**
 * Main sync function
 */
function syncTrades(days = 30, fullRefresh = false) {
  const ui = SpreadsheetApp.getUi();
  
  // Show loading message
  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  const loadingSheet = sheet.getSheetByName('Account Summary') || sheet.getActiveSheet();
  loadingSheet.getRange('E1').setValue('Syncing... Please wait.');
  
  try {
    // If webhook URL is not configured, use direct API method
    if (WEBHOOK_URL === 'YOUR_WEBHOOK_URL_HERE') {
      // Alternative: Direct Python script execution via Google Cloud Function
      ui.alert('Setup Required', 
        'Please configure your webhook URL in the script.\\n\\n' +
        'For now, you can run the sync manually from your computer using:\\n' +
        'python src/sync_trades.py --days ' + days, 
        ui.ButtonSet.OK);
      loadingSheet.getRange('E1').setValue('');
      return;
    }
    
    // Call webhook to trigger sync
    const payload = {
      'days': days,
      'fullRefresh': fullRefresh,
      'spreadsheetId': SpreadsheetApp.getActiveSpreadsheet().getId(),
      'timestamp': new Date().toISOString()
    };
    
    const options = {
      'method': 'post',
      'contentType': 'application/json',
      'payload': JSON.stringify(payload),
      'muteHttpExceptions': true
    };
    
    const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const responseCode = response.getResponseCode();
    
    if (responseCode === 200) {
      const result = JSON.parse(response.getContentText());
      loadingSheet.getRange('E1').setValue('Last sync: ' + new Date().toLocaleString());
      ui.alert('Success', 'Trade data synced successfully!', ui.ButtonSet.OK);
    } else {
      throw new Error('Sync failed with status: ' + responseCode);
    }
    
  } catch (error) {
    loadingSheet.getRange('E1').setValue('Sync failed: ' + error.toString());
    ui.alert('Error', 'Failed to sync trades: ' + error.toString(), ui.ButtonSet.OK);
  }
}

/**
 * Show settings dialog
 */
function showSettings() {
  const html = HtmlService.createHtmlOutputFromFile('settings')
    .setWidth(400)
    .setHeight(300);
  SpreadsheetApp.getUi().showModalDialog(html, 'Trade Journal Settings');
}

/**
 * Get current settings
 */
function getSettings() {
  const scriptProperties = PropertiesService.getScriptProperties();
  return {
    webhookUrl: scriptProperties.getProperty('WEBHOOK_URL') || WEBHOOK_URL,
    autoSyncEnabled: scriptProperties.getProperty('AUTO_SYNC_ENABLED') === 'true',
    autoSyncHour: parseInt(scriptProperties.getProperty('AUTO_SYNC_HOUR') || '9')
  };
}

/**
 * Save settings
 */
function saveSettings(settings) {
  const scriptProperties = PropertiesService.getScriptProperties();
  scriptProperties.setProperty('WEBHOOK_URL', settings.webhookUrl);
  scriptProperties.setProperty('AUTO_SYNC_ENABLED', settings.autoSyncEnabled.toString());
  scriptProperties.setProperty('AUTO_SYNC_HOUR', settings.autoSyncHour.toString());
  
  // Update or remove daily trigger based on settings
  if (settings.autoSyncEnabled) {
    installDailyTrigger(settings.autoSyncHour);
  } else {
    removeDailyTrigger();
  }
  
  return true;
}

/**
 * Install daily trigger for automatic sync
 */
function installDailyTrigger(hour) {
  // Remove existing triggers
  removeDailyTrigger();
  
  // Create new trigger
  ScriptApp.newTrigger('dailySync')
    .timeBased()
    .everyDays(1)
    .atHour(hour)
    .create();
}

/**
 * Remove daily trigger
 */
function removeDailyTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'dailySync') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

/**
 * Daily sync function (called by trigger)
 */
function dailySync() {
  syncTrades(1, false); // Sync last day's trades
}

/**
 * Navigation functions
 */
function goToDashboard() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Dashboard');
  if (sheet) {
    SpreadsheetApp.setActiveSheet(sheet);
    sheet.getRange('A1').activate();
  }
}

function goToTrades() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Trades');
  if (sheet) {
    SpreadsheetApp.setActiveSheet(sheet);
    sheet.getRange('A1').activate();
  }
}

/**
 * Trade management functions
 */
function markTradesClosed() {
  updateSelectedTradeStatus('Closed');
}

function markTradesRolled() {
  updateSelectedTradeStatus('Rolled');
}

function updateSelectedTradeStatus(newStatus) {
  const sheet = SpreadsheetApp.getActiveSheet();
  
  // Check if we're on the Trades sheet
  if (sheet.getName() !== 'Trades') {
    SpreadsheetApp.getUi().alert('Please select trades on the Trades sheet first.');
    return;
  }
  
  const selection = sheet.getActiveRange();
  const selectedRows = selection.getRow();
  const numRows = selection.getNumRows();
  
  // Find status column
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const statusCol = headers.indexOf('Status') + 1;
  
  if (statusCol === 0) {
    SpreadsheetApp.getUi().alert('Status column not found.');
    return;
  }
  
  // Update status for selected rows (skip header)
  if (selectedRows > 1) {
    const statusRange = sheet.getRange(selectedRows, statusCol, numRows, 1);
    
    // Create array of new status values
    const newValues = [];
    for (let i = 0; i < numRows; i++) {
      newValues.push([newStatus]);
    }
    
    statusRange.setValues(newValues);
    
    SpreadsheetApp.getUi().alert(`Updated ${numRows} trade(s) to ${newStatus} status.`);
  } else {
    SpreadsheetApp.getUi().alert('Please select trade rows (not the header).');
  }
}

/**
 * Trade lookup dialog
 */
function showTradeLookup() {
  const html = HtmlService.createHtmlOutputFromFile('tradeLookup')
    .setWidth(500)
    .setHeight(400);
  SpreadsheetApp.getUi().showModalDialog(html, 'Trade Lookup');
}

/**
 * Search for trades
 */
function searchTrades(searchTerm) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Trades');
  if (!sheet) return [];
  
  const data = sheet.getDataRange().getValues();
  const headers = data[0];
  const results = [];
  
  // Search in multiple columns
  const searchColumns = ['Trade ID', 'Underlying', 'Strategy', 'Original Notes', 'Current Notes'];
  const searchColIndices = searchColumns.map(col => headers.indexOf(col)).filter(idx => idx !== -1);
  
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    let found = false;
    
    for (const colIdx of searchColIndices) {
      if (row[colIdx] && row[colIdx].toString().toLowerCase().includes(searchTerm.toLowerCase())) {
        found = true;
        break;
      }
    }
    
    if (found) {
      results.push({
        row: i + 1,
        tradeId: row[0],
        underlying: row[1],
        strategy: row[2],
        status: row[5],
        pnl: row[8]
      });
    }
  }
  
  return results;
}

/**
 * Navigate to specific trade
 */
function goToTrade(rowNumber) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Trades');
  if (sheet) {
    SpreadsheetApp.setActiveSheet(sheet);
    sheet.getRange(rowNumber, 1).activate();
  }
}

/**
 * Performance calculation
 */
function calculateTradePerformance() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Trades');
  if (!sheet) {
    SpreadsheetApp.getUi().alert('Trades sheet not found.');
    return;
  }
  
  const data = sheet.getDataRange().getValues();
  const headers = data[0];
  
  // Find relevant columns
  const statusCol = headers.indexOf('Status');
  const strategyCol = headers.indexOf('Strategy');
  const pnlCol = headers.indexOf('Current P&L');
  
  if (statusCol === -1 || strategyCol === -1 || pnlCol === -1) {
    SpreadsheetApp.getUi().alert('Required columns not found.');
    return;
  }
  
  // Calculate statistics
  let totalTrades = 0;
  let closedTrades = 0;
  let winningTrades = 0;
  let totalPnL = 0;
  const strategies = {};
  
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    totalTrades++;
    
    const status = row[statusCol];
    const strategy = row[strategyCol];
    const pnl = parseFloat(row[pnlCol]) || 0;
    
    totalPnL += pnl;
    
    if (status === 'Closed') {
      closedTrades++;
      if (pnl > 0) winningTrades++;
    }
    
    if (!strategies[strategy]) {
      strategies[strategy] = { count: 0, pnl: 0, wins: 0 };
    }
    strategies[strategy].count++;
    strategies[strategy].pnl += pnl;
    if (pnl > 0) strategies[strategy].wins++;
  }
  
  const winRate = closedTrades > 0 ? (winningTrades / closedTrades * 100).toFixed(1) : 0;
  
  // Display results
  let message = `📊 PERFORMANCE SUMMARY\n\n`;
  message += `Total Trades: ${totalTrades}\n`;
  message += `Closed Trades: ${closedTrades}\n`;
  message += `Win Rate: ${winRate}%\n`;
  message += `Total P&L: $${totalPnL.toFixed(2)}\n\n`;
  
  message += `📈 BY STRATEGY:\n`;
  for (const [strategy, stats] of Object.entries(strategies)) {
    const strategyWinRate = stats.count > 0 ? (stats.wins / stats.count * 100).toFixed(1) : 0;
    message += `${strategy}: ${stats.count} trades, $${stats.pnl.toFixed(2)}, ${strategyWinRate}% win rate\n`;
  }
  
  SpreadsheetApp.getUi().alert(message);
}

/**
 * Auto-save notes when user edits cells
 */
function onEdit(e) {
  const sheet = e.source.getActiveSheet();
  
  // Only monitor the Trades sheet
  if (sheet.getName() !== 'Trades') return;
  
  const range = e.range;
  const column = range.getColumn();
  const row = range.getRow();
  
  // Skip header row
  if (row === 1) return;
  
  // Check if edited column is a notes column
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const editedHeader = headers[column - 1];
  
  if (editedHeader && (editedHeader.includes('Notes') || editedHeader === 'Status')) {
    // Add timestamp to indicate when last edited
    const timestampCol = headers.indexOf('Last Updated');
    if (timestampCol !== -1) {
      sheet.getRange(row, timestampCol + 1).setValue(new Date());
    }
  }
}

/**
 * Create a button in the sheet for quick sync
 */
function createSyncButton() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Dashboard');
  if (!sheet) return;
  
  // Add a button-like cell
  const buttonRange = sheet.getRange('A18:F18');
  buttonRange.merge();
  buttonRange.setValue('🔄 SYNC LATEST TRADES');
  buttonRange.setBackground('#4285f4');
  buttonRange.setFontColor('#ffffff');
  buttonRange.setFontWeight('bold');
  buttonRange.setHorizontalAlignment('center');
  buttonRange.setVerticalAlignment('middle');
  buttonRange.setFontSize(12);
  
  // Note: Actual button functionality requires the user to use the menu
  sheet.getRange('A19').setValue('Use Trade Journal menu to sync data');
  sheet.getRange('A19').setFontSize(10);
  sheet.getRange('A19').setFontColor('#666666');
}