# Strategy Configuration Guide

## Overview

The Trade Journal uses a JSON-based configuration system for defining and recognizing options strategies. This allows you to customize strategy definitions without modifying the source code.

## Configuration Files

### Main Configuration File
- **Location**: `config/strategies.json`
- **Purpose**: Defines all strategy types, recognition rules, and categorization

### Accessing the Configuration
1. **Web Interface**: Navigate to http://localhost:8000/strategy-config
2. **Direct File Edit**: Edit `config/strategies.json` directly
3. **API**: Use the `/api/strategy-config` endpoint

## Configuration Structure

### Strategy Definition
Each strategy in `strategy_types` contains:
```json
{
  "STRATEGY_KEY": {
    "name": "Display Name",
    "code": "SHORT_CODE",
    "category": "category_key",
    "direction": "bullish|bearish|neutral|volatility",
    "legs": 2,
    "description": "Brief description",
    "recognition_rules": {
      // Recognition patterns
    }
  }
}
```

### Recognition Rules
The `recognition_rules` object can contain:
- `leg_count`: Number of option legs required
- `option_type`: "Put" or "Call" (for single-type strategies)
- `requires_calls`: Number of call options required
- `requires_puts`: Number of put options required
- `pattern`: String describing the position pattern
- `same_strike`: Boolean for strategies requiring same strikes
- `different_strikes`: Boolean for strategies requiring different strikes
- `same_type`: Boolean for strategies requiring all same option type
- `different_types`: Boolean for strategies requiring mixed types
- `unique_strikes`: Number of unique strikes required
- `uneven_strikes`: Boolean for strategies with uneven strike spacing

### Categories
Define how strategies are grouped in the UI:
```json
"categories": {
  "category_key": {
    "name": "Display Name",
    "order": 1  // Display order
  }
}
```

### Direction Indicators
Define the directional bias indicators:
```json
"direction_indicators": {
  "bullish": {
    "code": "B",
    "color": "green",
    "description": "Profits from upward movement"
  }
}
```

## Adding a New Strategy

1. **Edit the JSON file** directly or use the web interface
2. **Add to strategy_types**:
```json
"NEW_STRATEGY": {
  "name": "New Strategy Name",
  "code": "NS",
  "category": "vertical_spread",
  "direction": "bullish",
  "legs": 2,
  "description": "Description here",
  "recognition_rules": {
    "leg_count": 2,
    "option_type": "Call",
    "pattern": "long_lower/short_higher"
  }
}
```

3. **Add to recognition_priority** array to set when it's checked

## Recognition Priority

The `recognition_priority` array determines the order in which strategies are checked during recognition. More specific strategies should be listed before more general ones.

Example:
```json
"recognition_priority": [
  "IRON_BUTTERFLY",    // Check before Iron Condor
  "IRON_CONDOR",
  "BROKEN_WING_BUTTERFLY",
  "BUTTERFLY",
  // ... etc
]
```

## Modifying Existing Strategies

1. **Via Web Interface**: 
   - Navigate to http://localhost:8000/strategy-config
   - Click edit on any strategy
   - Make changes and save

2. **Direct File Edit**:
   - Open `config/strategies.json`
   - Modify the strategy definition
   - Save the file
   - Restart the application or reload configuration

## Best Practices

1. **Test Recognition**: After adding/modifying strategies, test with real trade data
2. **Backup**: Keep a backup of your configuration before major changes
3. **Naming**: Use consistent naming conventions for codes and keys
4. **Documentation**: Update descriptions to be clear and helpful
5. **Priority**: Order recognition rules from most specific to least specific

## Example: Adding a Custom Butterfly Variant

```json
"JADE_LIZARD": {
  "name": "Jade Lizard",
  "code": "JL",
  "category": "multi_leg_complex",
  "direction": "neutral",
  "legs": 3,
  "description": "Short put + short call spread",
  "recognition_rules": {
    "leg_count": 3,
    "requires_calls": 2,
    "requires_puts": 1,
    "pattern": "short_put/short_call/long_call"
  }
}
```

## Troubleshooting

1. **Strategy Not Recognized**: 
   - Check recognition_priority order
   - Verify recognition_rules match your trade pattern
   - Check leg counts and option types

2. **Configuration Not Loading**:
   - Verify JSON syntax is valid
   - Check file permissions
   - Look for errors in application logs

3. **Changes Not Taking Effect**:
   - Reload configuration via web interface
   - Restart the application
   - Clear browser cache