"""Settings routes — strategy targets and OAuth credentials."""

import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.dependencies import db, connection_manager, get_current_user_id
from src.schemas import StrategyTarget, CredentialUpdate

router = APIRouter()


@router.get("/api/settings/targets")
async def get_strategy_targets(user_id: str = Depends(get_current_user_id)):
    """Get all strategy P&L targets"""
    targets = db.get_strategy_targets()
    return targets


@router.post("/api/settings/targets")
async def save_strategy_targets(targets: List[StrategyTarget], user_id: str = Depends(get_current_user_id)):
    """Save strategy P&L targets"""
    target_dicts = [t.model_dump() for t in targets]
    success = db.save_strategy_targets(target_dicts)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save targets")
    return {"message": "Targets saved successfully"}


@router.post("/api/settings/targets/reset")
async def reset_strategy_targets(user_id: str = Depends(get_current_user_id)):
    """Reset strategy targets to defaults"""
    success = db.reset_strategy_targets()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reset targets")
    return {"message": "Targets reset to defaults"}


@router.get("/api/settings/credentials")
async def get_credentials_status(user_id: str = Depends(get_current_user_id)):
    """Check if OAuth credentials are configured (never expose actual secrets)"""
    return {"configured": connection_manager.is_configured()}


@router.post("/api/settings/credentials")
async def save_credentials(creds: CredentialUpdate, user_id: str = Depends(get_current_user_id)):
    """Save OAuth credentials to .env file"""
    try:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')

        # Read existing .env content
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()

        # Update or add credential lines
        new_lines = []
        found_secret = False
        found_token = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('TASTYTRADE_PROVIDER_SECRET'):
                new_lines.append(f'TASTYTRADE_PROVIDER_SECRET={creds.provider_secret}\n')
                found_secret = True
            elif stripped.startswith('TASTYTRADE_REFRESH_TOKEN'):
                new_lines.append(f'TASTYTRADE_REFRESH_TOKEN={creds.refresh_token}\n')
                found_token = True
            else:
                new_lines.append(line)

        if not found_secret:
            new_lines.append(f'TASTYTRADE_PROVIDER_SECRET={creds.provider_secret}\n')
        if not found_token:
            new_lines.append(f'TASTYTRADE_REFRESH_TOKEN={creds.refresh_token}\n')

        with open(env_path, 'w') as f:
            f.writelines(new_lines)

        logger.info("OAuth credentials saved to .env")
        return {"message": "Credentials saved successfully"}
    except Exception as e:
        logger.error(f"Failed to save credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))
