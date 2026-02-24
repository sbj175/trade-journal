"""Settings routes — strategy targets and OAuth credentials."""

import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.dependencies import db, connection_manager, get_current_user_id, AUTH_ENABLED
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
    if AUTH_ENABLED:
        from src.database.models import UserCredential
        with db.get_session(user_id=user_id) as session:
            row = session.query(UserCredential).filter(
                UserCredential.provider == "tastytrade",
                UserCredential.is_active.is_(True),
            ).first()
            return {"configured": row is not None}
    return {"configured": connection_manager.is_configured()}


@router.post("/api/settings/credentials")
async def save_credentials(creds: CredentialUpdate, user_id: str = Depends(get_current_user_id)):
    """Save OAuth credentials — to DB (auth enabled) or .env (auth disabled)"""
    try:
        if AUTH_ENABLED:
            from src.database.models import UserCredential
            from src.utils.credential_encryption import encrypt_credential
            from src.database.engine import dialect_insert

            enc_secret = encrypt_credential(creds.provider_secret)
            enc_token = encrypt_credential(creds.refresh_token)
            now = datetime.now().isoformat()

            with db.get_session(user_id=user_id) as session:
                stmt = dialect_insert(UserCredential).values(
                    user_id=user_id,
                    provider="tastytrade",
                    encrypted_provider_secret=enc_secret,
                    encrypted_refresh_token=enc_token,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                # Upsert: on conflict update the encrypted values
                if session.bind.dialect.name == "sqlite":
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["user_id", "provider"],
                        set_={
                            "encrypted_provider_secret": enc_secret,
                            "encrypted_refresh_token": enc_token,
                            "is_active": True,
                            "updated_at": now,
                        },
                    )
                else:
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_user_credentials_user_provider",
                        set_={
                            "encrypted_provider_secret": enc_secret,
                            "encrypted_refresh_token": enc_token,
                            "is_active": True,
                            "updated_at": now,
                        },
                    )
                session.execute(stmt)

            # Evict cached connection so next request uses the new credentials
            connection_manager.disconnect_user(user_id)
            logger.info(f"Saved encrypted credentials for user {user_id[:8]}...")
            return {"message": "Credentials saved successfully"}
        else:
            # Legacy: write to .env file
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')

            lines = []
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    lines = f.readlines()

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


@router.delete("/api/settings/credentials")
async def delete_credentials(user_id: str = Depends(get_current_user_id)):
    """Remove stored OAuth credentials (auth-enabled only)"""
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Credential deletion only available in multi-user mode")

    try:
        from src.database.models import UserCredential

        with db.get_session(user_id=user_id) as session:
            deleted = session.query(UserCredential).filter(
                UserCredential.provider == "tastytrade",
            ).delete()

        connection_manager.disconnect_user(user_id)
        logger.info(f"Deleted credentials for user {user_id[:8]}... ({deleted} row(s))")
        return {"message": "Credentials removed"}
    except Exception as e:
        logger.error(f"Failed to delete credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))
