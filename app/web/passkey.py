"""
Allfiledown — WebAuthn / Passkey 通行密钥
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from fastapi import APIRouter, Request
from webauthn import (
    generate_registration_options,
    generate_authentication_options,
    verify_registration_response,
    verify_authentication_response,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    RegistrationCredential,
    AuthenticationCredential,
    AuthenticatorAttestationResponse,
    AuthenticatorAssertionResponse,
    PublicKeyCredentialType,
)

from app.config import config
from app.database import get_db
from app.security import create_web_session

logger = logging.getLogger("afd.passkey")

router: APIRouter = APIRouter(prefix="/api/auth/passkey")

_challenge_store: dict[str, bytes] = {}

_RP_ID = "af.ll264a.xyz"
_RP_NAME = "AFD · Allfiledown"
_ORIGIN = "https://af.ll264a.xyz"


def _serialize_webauthn(obj: Any) -> Any:
    """递归将 WebAuthn dataclass 序列化为前端期望的 JSON"""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        return bytes_to_base64url(obj)
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        result: dict[str, Any] = {}
        for f in fields(obj):
            val = getattr(obj, f.name)
            if val is None:
                continue
            key = {
                "pub_key_cred_params": "pubKeyCredParams",
                "exclude_credentials": "excludeCredentials",
                "authenticator_selection": "authenticatorSelection",
                "allow_credentials": "allowCredentials",
                "user_verification": "userVerification",
                "rp_id": "rpId",
                "display_name": "displayName",
                "client_data_json": "clientDataJSON",
                "attestation_object": "attestationObject",
                "authenticator_data": "authenticatorData",
                "user_handle": "userHandle",
            }.get(f.name, f.name)
            result[key] = _serialize_webauthn(val)
        return result
    if isinstance(obj, list):
        return [_serialize_webauthn(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_webauthn(v) for k, v in obj.items()}
    return str(obj)


def _json_to_credential(j: dict[str, Any]) -> dict[str, Any]:
    """将 credential.toJSON() 的 snake_case 字段标准化为代码字段"""
    result = dict(j)
    resp = result.get("response", {})
    result["raw_id"] = result.get("rawId", result.get("id", ""))
    # response 字段名映射
    resp_map = {
        "client_data_json": resp.get("clientDataJSON", resp.get("client_data_json", "")),
        "clientDataJSON": resp.get("clientDataJSON", resp.get("client_data_json", "")),
        "attestation_object": resp.get("attestationObject", resp.get("attestation_object", "")),
        "attestationObject": resp.get("attestationObject", resp.get("attestation_object", "")),
        "authenticator_data": resp.get("authenticatorData", resp.get("authenticator_data", "")),
        "authenticatorData": resp.get("authenticatorData", resp.get("authenticator_data", "")),
        "signature": resp.get("signature", ""),
        "user_handle": resp.get("userHandle", resp.get("user_handle", "")),
        "userHandle": resp.get("userHandle", resp.get("user_handle", "")),
        "transports": resp.get("transports", []),
    }
    result["response"] = resp_map
    return result


def _get_credentials(user_id: str = "admin") -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        "SELECT id, credential_id, name, created_at FROM passkey_credentials WHERE user_id = ? ORDER BY created_at",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── 注册流程 ──


@router.post("/register/begin")
async def passkey_register_begin(request: Request) -> dict[str, Any]:
    from app.web.routes import _check_auth
    if not _check_auth(request):
        return {"error": "未登录"}

    data: dict[str, Any] = await request.json()
    user_id: str = data.get("user_id", "admin")

    existing = _get_credentials(user_id)
    exclude_creds = []
    for cred in existing:
        try:
            exclude_creds.append(base64url_to_bytes(cred["credential_id"]))
        except Exception:
            pass

    options = generate_registration_options(
        rp_id=_RP_ID,
        rp_name=_RP_NAME,
        user_id=user_id.encode("utf-8"),
        user_name=user_id,
        user_display_name=user_id,
        exclude_credentials=exclude_creds,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    challenge_id = str(uuid.uuid4())
    _challenge_store[challenge_id] = options.challenge

    return {
        "challenge_id": challenge_id,
        "publicKey": _serialize_webauthn(options),
    }


@router.post("/register/complete")
async def passkey_register_complete(request: Request) -> dict[str, Any]:
    from app.web.routes import _check_auth
    if not _check_auth(request):
        return {"error": "未登录"}

    data: dict[str, Any] = await request.json()
    challenge_id: str = data.get("challenge_id", "")
    cred_json: dict[str, Any] = _json_to_credential(data.get("credential", {}))
    cred_name: str = data.get("name", "我的通行密钥")

    challenge = _challenge_store.pop(challenge_id, None)
    if not challenge:
        return {"error": "挑战已过期，请重新开始"}

    try:
        raw_id: bytes = base64url_to_bytes(cred_json["raw_id"])
        resp = cred_json["response"]
        attestation_resp = AuthenticatorAttestationResponse(
            client_data_json=base64url_to_bytes(resp["client_data_json"]),
            attestation_object=base64url_to_bytes(resp["attestation_object"]),
            transports=resp.get("transports", []),
        )
        credential = RegistrationCredential(
            id=cred_json.get("id", ""),
            raw_id=raw_id,
            response=attestation_resp,
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_RP_ID,
            expected_origin=_ORIGIN,
        )
    except Exception as e:
        logger.warning("Passkey registration verify failed: %s", e)
        import traceback
        logger.warning(traceback.format_exc())
        return {"error": f"验证失败: {str(e)}"}

    cred_id_b64 = bytes_to_base64url(verification.credential_id)
    pub_key_b64 = bytes_to_base64url(verification.credential_public_key)
    cred_uid = str(uuid.uuid4())

    db = get_db()
    db.execute(
        "INSERT INTO passkey_credentials (id, user_id, credential_id, public_key, sign_count, name) VALUES (?, ?, ?, ?, ?, ?)",
        (cred_uid, "admin", cred_id_b64, pub_key_b64, verification.sign_count, cred_name),
    )
    db.commit()

    return {"success": True, "credential_id": cred_uid, "name": cred_name}


# ── 认证（登录）流程 ──


@router.post("/login/begin")
async def passkey_login_begin(request: Request) -> dict[str, Any]:
    user_id: str = "admin"

    existing = _get_credentials(user_id)
    if not existing:
        return {"error": "没有已注册的通行密钥"}

    allow_creds = []
    for cred in existing:
        try:
            allow_creds.append(base64url_to_bytes(cred["credential_id"]))
        except Exception:
            pass

    options = generate_authentication_options(
        rp_id=_RP_ID,
        allow_credentials=allow_creds,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    challenge_id = str(uuid.uuid4())
    _challenge_store[challenge_id] = options.challenge

    return {
        "challenge_id": challenge_id,
        "publicKey": _serialize_webauthn(options),
    }


@router.post("/login/complete")
async def passkey_login_complete(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = await request.json()
    challenge_id: str = data.get("challenge_id", "")
    cred_json: dict[str, Any] = _json_to_credential(data.get("credential", {}))

    challenge = _challenge_store.pop(challenge_id, None)
    if not challenge:
        return {"error": "挑战已过期，请重新开始"}

    cred_id_from_request: str = cred_json.get("id", "")
    if not cred_id_from_request:
        return {"error": "缺少凭据 ID"}

    db = get_db()
    row = db.execute(
        "SELECT * FROM passkey_credentials WHERE credential_id = ? AND user_id = ?",
        (cred_id_from_request, "admin"),
    ).fetchone()

    if not row:
        return {"error": "凭据未找到，请重新注册"}

    try:
        raw_id: bytes = base64url_to_bytes(cred_json["raw_id"])
        resp = cred_json["response"]
        assertion_resp = AuthenticatorAssertionResponse(
            client_data_json=base64url_to_bytes(resp["client_data_json"]),
            authenticator_data=base64url_to_bytes(resp["authenticator_data"]),
            signature=base64url_to_bytes(resp["signature"]),
            user_handle=base64url_to_bytes(resp.get("user_handle", "")),
        )
        credential = AuthenticationCredential(
            id=cred_id_from_request,
            raw_id=raw_id,
            response=assertion_resp,
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_RP_ID,
            expected_origin=_ORIGIN,
            credential_public_key=base64url_to_bytes(row["public_key"]),
            credential_current_sign_count=row["sign_count"],
        )
    except Exception as e:
        logger.warning("Passkey auth verify failed: %s", e)
        import traceback
        logger.warning(traceback.format_exc())
        return {"error": f"验证失败: {str(e)}"}

    db.execute(
        "UPDATE passkey_credentials SET sign_count = ? WHERE id = ?",
        (verification.new_sign_count, row["id"]),
    )
    db.commit()

    token: str = create_web_session("admin")

    return {
        "authenticated": True,
        "token": token,
        "redirect": "/",
        "credential_name": row["name"],
    }


# ── 辅助 ──


@router.post("/list")
async def passkey_list(request: Request) -> dict[str, Any]:
    from app.web.routes import _check_auth
    if not _check_auth(request):
        return {"error": "未登录"}
    return {"credentials": _get_credentials()}


@router.post("/remove")
async def passkey_remove(request: Request) -> dict[str, Any]:
    from app.web.routes import _check_auth
    if not _check_auth(request):
        return {"error": "未登录"}
    data: dict[str, Any] = await request.json()
    cred_id: str = data.get("id", "")
    if not cred_id:
        return {"error": "缺少凭据 ID"}
    db = get_db()
    db.execute("DELETE FROM passkey_credentials WHERE id = ? AND user_id = ?", (cred_id, "admin"))
    db.commit()
    return {"success": True}
