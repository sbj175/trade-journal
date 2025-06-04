"""
Strategy Configuration Loader
Loads strategy definitions from JSON configuration file
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

@dataclass
class StrategyConfig:
    """Configuration for a single strategy type"""
    key: str
    name: str
    code: str
    category: str
    direction: str
    legs: int
    description: str
    recognition_rules: Dict[str, Any]


class StrategyConfigLoader:
    """Loads and manages strategy configurations from JSON file"""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # Default to config/strategies.json relative to project root
            base_path = Path(__file__).parent.parent.parent
            config_path = base_path / "config" / "strategies.json"
        
        self.config_path = Path(config_path)
        self.config_data = self._load_config()
        self.strategies = self._parse_strategies()
    
    def _load_config(self) -> Dict:
        """Load configuration from JSON file"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Strategy config file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            return json.load(f)
    
    def _parse_strategies(self) -> Dict[str, StrategyConfig]:
        """Parse strategy configurations"""
        strategies = {}
        
        for key, data in self.config_data.get('strategy_types', {}).items():
            strategies[key] = StrategyConfig(
                key=key,
                name=data['name'],
                code=data['code'],
                category=data['category'],
                direction=data['direction'],
                legs=data['legs'],
                description=data['description'],
                recognition_rules=data['recognition_rules']
            )
        
        return strategies
    
    def get_strategy(self, key: str) -> Optional[StrategyConfig]:
        """Get a specific strategy configuration"""
        return self.strategies.get(key)
    
    def get_strategies_by_category(self, category: str) -> List[StrategyConfig]:
        """Get all strategies in a category"""
        return [s for s in self.strategies.values() if s.category == category]
    
    def get_categories(self) -> Dict[str, Dict]:
        """Get category definitions"""
        return self.config_data.get('categories', {})
    
    def get_direction_indicators(self) -> Dict[str, Dict]:
        """Get direction indicator definitions"""
        return self.config_data.get('direction_indicators', {})
    
    def get_recognition_priority(self) -> List[str]:
        """Get strategy recognition priority order"""
        return self.config_data.get('recognition_priority', [])
    
    def get_all_strategies(self) -> List[StrategyConfig]:
        """Get all strategy configurations"""
        # Return in recognition priority order if available
        priority = self.get_recognition_priority()
        if priority:
            ordered = []
            for key in priority:
                if key in self.strategies:
                    ordered.append(self.strategies[key])
            # Add any remaining strategies not in priority list
            for key, strategy in self.strategies.items():
                if key not in priority:
                    ordered.append(strategy)
            return ordered
        return list(self.strategies.values())
    
    def reload(self):
        """Reload configuration from file"""
        self.config_data = self._load_config()
        self.strategies = self._parse_strategies()
    
    def get_strategy_choices(self) -> List[tuple]:
        """Get strategy choices for dropdowns (value, display_name)"""
        choices = []
        categories = self.get_categories()
        
        # Sort categories by order
        sorted_cats = sorted(categories.items(), key=lambda x: x[1].get('order', 999))
        
        for cat_key, cat_info in sorted_cats:
            cat_strategies = self.get_strategies_by_category(cat_key)
            for strategy in cat_strategies:
                choices.append((strategy.name, strategy.name))
        
        return choices
    
    def save_config(self):
        """Save current configuration back to file"""
        # Rebuild config data from current strategies
        self.config_data['strategy_types'] = {}
        
        for key, strategy in self.strategies.items():
            self.config_data['strategy_types'][key] = {
                'name': strategy.name,
                'code': strategy.code,
                'category': strategy.category,
                'direction': strategy.direction,
                'legs': strategy.legs,
                'description': strategy.description,
                'recognition_rules': strategy.recognition_rules
            }
        
        with open(self.config_path, 'w') as f:
            json.dump(self.config_data, f, indent=2)
    
    def add_strategy(self, strategy: StrategyConfig):
        """Add a new strategy to the configuration"""
        self.strategies[strategy.key] = strategy
        self.save_config()
    
    def update_strategy(self, key: str, updates: Dict[str, Any]):
        """Update an existing strategy"""
        if key in self.strategies:
            strategy = self.strategies[key]
            for field, value in updates.items():
                if hasattr(strategy, field):
                    setattr(strategy, field, value)
            self.save_config()
    
    def delete_strategy(self, key: str):
        """Delete a strategy from the configuration"""
        if key in self.strategies:
            del self.strategies[key]
            self.save_config()


# Singleton instance
_strategy_config = None

def get_strategy_config() -> StrategyConfigLoader:
    """Get the singleton strategy configuration loader"""
    global _strategy_config
    if _strategy_config is None:
        _strategy_config = StrategyConfigLoader()
    return _strategy_config