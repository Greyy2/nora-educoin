"""Router aggregator for COIN backend system routes.

This module re-exports routers and utilities from domain-specific route modules:
- engine: engine_router, version/check_update
- home: home_router, summary
- overview: overview_router, studio overview, series, rolling sharpe
- auth: users_router, current_user, set_uid_cookie, clear_uid_cookie, schemas
- market_edu: edu_router, warm_market_cache, etc.
"""
from backend.routes.engine import engine_router
from backend.routes.home import home_router
from backend.routes.overview import overview_router
from backend.routes.auth import (
    users_router,
    current_user,
    set_uid_cookie,
    clear_uid_cookie,
    _get_cookie_key_for_request,
    CreateUserReq,
    EnterReq,
    LoginReq,
    UpdateProfileReq,
)
from backend.routes.market_edu import (
    edu_router,
    warm_market_cache,
    _public_user,
    _market_rows,
)

ROUTERS = [engine_router, home_router, overview_router, users_router, edu_router]

__all__ = [
    "engine_router",
    "home_router",
    "overview_router",
    "users_router",
    "edu_router",
    "current_user",
    "set_uid_cookie",
    "clear_uid_cookie",
    "_get_cookie_key_for_request",
    "CreateUserReq",
    "EnterReq",
    "LoginReq",
    "UpdateProfileReq",
    "warm_market_cache",
    "ROUTERS",
]
