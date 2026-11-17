"""HTTP composition for the extracted authentication and workspace services."""

import os
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import Field, SecretStr
from pwdlib import PasswordHash
from app_core.auth.identity import (
    IdentityVerificationUnavailableError,
    InvalidAuthenticationError,
    TokenAuthenticationBackend,
)
from app_core.auth.onboarding import (
    InvitationIdentityMismatchError,
    InvitationUnavailableError,
    OnboardingService,
)
from app_core.auth.workspace_admin import (
    LastWorkspaceAdminError,
    SelfRemovalError,
    WorkspaceAdminConflictError,
    WorkspaceAdminForbiddenError,
    WorkspaceAdminNotFoundError,
    WorkspaceAdminService,
)
from app_core.domain.models import (
    Feedback,
    FeedbackCreate,
    FeedbackPage,
    FeedbackSupport,
    InvitationAcceptanceRequest,
    InvitationResolveRequest,
    StrictModel,
    UserPreferencesPatch,
    WorkspaceInvitationCreateRequest,
    WorkspaceMemberPatch,
    WorkspaceRole,
)
from app_core.store import PostgresStore
from app_core.comments import CommentCreate
from app_core.request_links import RequestLinks, RequestStatus
from app_core.request_approvals import ApprovalRequest
from app_core.entitlements import Entitlements
from app_core.platform_admin import PlatformAccess, register_platform_routes

HASHER = PasswordHash.recommended()
DUMMY_HASH = HASHER.hash("unavailable-account-password")
COOKIE = "app_session"


class Login(StrictModel):
    email: Annotated[str, Field(min_length=3, max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=256)]


class RecordCreate(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionVerifier:
    def __init__(self, store):
        self.store = store

    def verify(self, token):
        return self.store.identity_for_session(token)


def create_app(store=None, verifier=None, billing_service=None):
    auth_mode = os.getenv("AUTH_PROVIDER", "local")
    if auth_mode == "google":
        auth_mode = "firebase"
    if auth_mode not in {"local", "firebase", "custom"}:
        raise RuntimeError("Unknown AUTH_PROVIDER")
    if auth_mode == "custom" and verifier is None:
        raise RuntimeError("Inject a custom IdentityTokenVerifier")
    if os.getenv("APP_ENV", "development") != "development":
        if os.getenv("COOKIE_SECURE", "false").lower() != "true":
            raise RuntimeError("COOKIE_SECURE=true is required outside development")
        if not os.getenv("APP_ALLOWED_ORIGINS"):
            raise RuntimeError("Set APP_ALLOWED_ORIGINS outside development")
    platform_access = PlatformAccess.from_env()
    owns_store = store is None
    store = store or PostgresStore(os.getenv("DATABASE_URL", ""))
    if verifier is None and auth_mode == "firebase":
        from app_core.auth.google import FirebaseIdentityTokenVerifier

        verifier = FirebaseIdentityTokenVerifier(os.environ["GOOGLE_PROJECT_ID"])
    local = TokenAuthenticationBackend(SessionVerifier(store), store)
    external = TokenAuthenticationBackend(verifier, store) if verifier else None
    admin = WorkspaceAdminService(store)
    entitlements = Entitlements(store)
    onboarding = OnboardingService(
        store,
        terms_version=os.getenv("TERMS_VERSION", "starter-v1"),
        privacy_version=os.getenv("PRIVACY_VERSION", "starter-v1"),
    )
    origins = [
        v.strip()
        for v in os.getenv(
            "APP_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
        ).split(",")
        if v.strip()
    ]
    if not origins or "*" in origins:
        raise RuntimeError("Use explicit APP_ALLOWED_ORIGINS")

    @asynccontextmanager
    async def lifespan(app):
        import asyncio
        from app_core.auto_triage import dispatch_loop
        from app_core.auto_priority import dispatch_priority_loop

        app.state.triage_service.dispatcher = asyncio.create_task(
            dispatch_loop(app.state.triage_service)
        )
        app.state.priority_service.dispatcher = asyncio.create_task(
            dispatch_priority_loop(app.state.priority_service)
        )
        try:
            yield
        finally:
            if hasattr(app.state, "priority_service"):
                await app.state.priority_service.close()
            if hasattr(app.state, "triage_service"):
                await app.state.triage_service.close()
            if owns_store:
                store.close()

    app = FastAPI(title="Workspace App Core", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Workspace", "X-App-Request"],
    )

    @app.middleware("http")
    async def security(request, call_next):
        stripe_webhook = (
            request.method == "POST" and request.url.path == "/api/v1/billing/webhook"
        )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not stripe_webhook:
            if request.headers.get("X-App-Request") != "1" or (
                request.headers.get("origin")
                and request.headers["origin"] not in origins
            ):
                return Response(status_code=403)
        if request.method in {"POST", "PATCH", "PUT"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > (262144 if stripe_webhook else 65536):
                    return Response(status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
        )
        return response

    def identity(request: Request):
        try:
            if external and request.headers.get("authorization"):
                ident = external.verify_identity(request.headers["authorization"])
                if (
                    ident.tenant_id is not None
                    or not ident.email
                    or not ident.email_verified
                ):
                    raise InvalidAuthenticationError
                store.ensure_external_user(ident)
                return ident
            if auth_mode != "local":
                raise InvalidAuthenticationError
            token = request.cookies.get(COOKIE)
            if not token:
                raise InvalidAuthenticationError
            return local.verify_identity(f"Bearer {token}")
        except InvalidAuthenticationError:
            raise HTTPException(401, "Please sign in") from None
        except IdentityVerificationUnavailableError:
            raise HTTPException(
                503, "Identity verification is temporarily unavailable"
            ) from None

    register_platform_routes(app, store, identity, platform_access, entitlements)

    Identity = Annotated[Any, Depends(identity)]

    def principal(
        ident: Identity,
        workspace: Annotated[str | None, Header(alias="X-Workspace")] = None,
    ):
        access = store.get_active_global_access(ident.subject, workspace)
        if not access:
            raise HTTPException(404, "Workspace not found or not selected")
        from app_core.auth.identity import _principal_from_access

        return _principal_from_access(access)

    PrincipalDep = Annotated[Any, Depends(principal)]

    from app_core.billing_routes import register_billing_routes

    register_billing_routes(app, store, PrincipalDep, entitlements, billing_service)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        from fastapi.responses import JSONResponse

        # Do not echo credentials or invitation tokens in validation responses.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
        )

    @app.exception_handler(WorkspaceAdminForbiddenError)
    async def forbidden(request, error):
        return Response(status_code=403)

    @app.exception_handler(WorkspaceAdminNotFoundError)
    @app.exception_handler(InvitationUnavailableError)
    async def missing(request, error):
        return Response(status_code=404)

    @app.exception_handler(WorkspaceAdminConflictError)
    @app.exception_handler(LastWorkspaceAdminError)
    @app.exception_handler(SelfRemovalError)
    async def conflict(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409,
            content={
                "detail": "Change conflicts with membership or last administrator policy"
            },
        )

    @app.exception_handler(InvitationIdentityMismatchError)
    async def mismatch(request, error):
        return Response(status_code=403)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/auth/config")
    def config():
        return {
            "provider": auth_mode,
            **(
                {"projectId": os.environ["GOOGLE_PROJECT_ID"]}
                if auth_mode == "firebase"
                else {}
            ),
        }

    @app.post("/api/v1/auth/login")
    def login(payload: Login, request: Request, response: Response):
        if auth_mode != "local":
            raise HTTPException(404, "Local sign-in is not enabled")
        email = payload.email.strip().casefold()
        host = request.client.host if request.client else "unknown"
        if not store.allow_login("ip:" + host) or not store.allow_login(
            "email:" + email
        ):
            raise HTTPException(429, "Too many attempts; try again in five minutes")
        user = store.user_by_email(email)
        candidate = (
            user["password_hash"] if user and user["password_hash"] else DUMMY_HASH
        )
        valid = HASHER.verify(payload.password.get_secret_value(), candidate)
        if not valid or not user or not user["password_hash"]:
            raise HTTPException(401, "Email or password is incorrect")
        previous = request.cookies.get(COOKIE)
        if previous:
            store.revoke_session(previous)
        token = store.new_session(user["id"])
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
            samesite="lax",
            max_age=28800,
            path="/",
        )
        return {"subject": user["id"], "email": user["email"]}

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        if token:
            store.revoke_session(token)
        response.delete_cookie(COOKIE, path="/")
        response.status_code = 204
        return response

    @app.get("/api/v1/me")
    def me(ident: Identity):
        return {
            "subject": ident.subject,
            "email": ident.email,
            "email_verified": ident.email_verified,
            "platform_role": platform_access.role(ident.subject),
        }

    @app.get("/api/v1/me/workspaces")
    def workspaces(ident: Identity):
        return [
            {
                "workspace_slug": a.workspace_slug,
                "workspace_name": a.workspace.display_name,
                "role": a.role,
                "theme_color": a.theme_color,
            }
            for a in store.list_active_global_access(ident.subject)
        ]

    @app.get("/api/v1/me/preferences")
    def preferences(ident: Identity):
        return store.get_preferences(ident.subject)

    @app.patch("/api/v1/me/preferences")
    def preferences_patch(payload: UserPreferencesPatch, ident: Identity):
        return store.update_preferences(ident.subject, payload)

    @app.get("/api/v1/workspace/members")
    def members(p: PrincipalDep):
        return admin.list_members(p)

    @app.patch("/api/v1/workspace/members/{membership_id}")
    def update_member(
        membership_id: UUID, payload: WorkspaceMemberPatch, p: PrincipalDep
    ):
        return admin.update_member(p, membership_id, payload.role, payload.status)

    @app.delete("/api/v1/workspace/members/{membership_id}", status_code=204)
    def remove_member(membership_id: UUID, p: PrincipalDep):
        admin.remove_member(p, membership_id)
        return Response(status_code=204)

    @app.get("/api/v1/workspace/invitations")
    def invitations(p: PrincipalDep):
        return admin.list_invitations(p)

    @app.post("/api/v1/workspace/invitations", status_code=201)
    def invite(payload: WorkspaceInvitationCreateRequest, p: PrincipalDep):
        try:
            return admin.create_invitation(
                p, payload.invited_email, payload.role, payload.expires_in_days
            )
        except ValueError:
            raise HTTPException(422, "Invalid invitation") from None

    @app.delete("/api/v1/workspace/invitations/{invitation_id}")
    def revoke_invite(invitation_id: UUID, p: PrincipalDep):
        return admin.revoke_invitation(p, invitation_id)

    @app.post("/api/v1/onboarding/invitations/resolve")
    def resolve(payload: InvitationResolveRequest):
        return onboarding.resolve(payload.invitation_token.get_secret_value())

    @app.post("/api/v1/onboarding/invitations/accept")
    def accept(payload: InvitationAcceptanceRequest, ident: Identity):
        return onboarding.accept(payload.invitation_token.get_secret_value(), ident)

    @app.get("/api/v1/entitlements")
    def workspace_entitlements(p: PrincipalDep):
        return entitlements.snapshot(p)

    @app.get("/api/v1/feedback", response_model=FeedbackPage)
    def feedback(
        p: PrincipalDep,
        search: Annotated[str, Query(max_length=200)] = "",
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
        status: Annotated[
            str,
            Query(pattern="^(all|new|needs_clarification|triaged|rejected|archived)$"),
        ] = "all",
        feedback_id: UUID | None = None,
    ):
        return store.list_feedback(
            p, search.strip(), limit, offset, status, feedback_id
        )

    @app.post("/api/v1/feedback", response_model=Feedback, status_code=201)
    def submit_feedback(payload: FeedbackCreate, p: PrincipalDep):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Read-only membership")
        try:
            return store.create_feedback(
                p, payload.title, payload.description, payload.submission_key
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/feedback/{feedback_id}/approval", status_code=202)
    def approve_request(feedback_id: UUID, payload: ApprovalRequest, p: PrincipalDep):
        return store.request_approval(p, feedback_id, payload.expected_status)

    @app.get("/api/v1/feedback/{feedback_id}/approval")
    def request_approval_state(feedback_id: UUID, p: PrincipalDep):
        return store.approval_state(p, feedback_id)

    @app.put("/api/v1/feedback/{feedback_id}/status")
    def update_request_status(
        feedback_id: UUID, payload: RequestStatus, p: PrincipalDep
    ):
        return store.set_request_status(p, feedback_id, payload)

    @app.put("/api/v1/feedback/{feedback_id}/opportunities")
    def update_request_links(feedback_id: UUID, payload: RequestLinks, p: PrincipalDep):
        return store.set_request_links(p, feedback_id, payload)

    @app.get("/api/v1/feedback/{feedback_id}/comments")
    def request_comments(feedback_id: UUID, p: PrincipalDep):
        return store.feedback_comments(p, feedback_id)

    @app.post("/api/v1/feedback/{feedback_id}/comments", status_code=201)
    def add_request_comment(feedback_id: UUID, payload: CommentCreate, p: PrincipalDep):
        return store.feedback_comments(p, feedback_id, payload)

    @app.get("/api/v1/opportunities/{opportunity_id}/comments")
    def opportunity_discussion(opportunity_id: UUID, p: PrincipalDep):
        return store.opportunity_comments(p, opportunity_id)

    @app.post("/api/v1/opportunities/{opportunity_id}/comments", status_code=201)
    def add_opportunity_comment(
        opportunity_id: UUID, payload: CommentCreate, p: PrincipalDep
    ):
        return store.opportunity_comments(p, opportunity_id, payload)

    @app.post("/api/v1/feedback/{feedback_id}/support", response_model=FeedbackSupport)
    def support_feedback(feedback_id: UUID, p: PrincipalDep):
        result = store.set_feedback_support(p, feedback_id, True)
        if result is None:
            raise HTTPException(404, "Feedback not found")
        return result

    @app.delete(
        "/api/v1/feedback/{feedback_id}/support", response_model=FeedbackSupport
    )
    def withdraw_feedback_support(feedback_id: UUID, p: PrincipalDep):
        result = store.set_feedback_support(p, feedback_id, False)
        if result is None:
            raise HTTPException(404, "Feedback not found")
        return result

    @app.get("/api/v1/records")
    def records(p: PrincipalDep):
        return store.scoped_records(p)

    @app.get("/api/v1/records/{record_id}")
    def record(record_id: UUID, p: PrincipalDep):
        rows = store.scoped_records(p, str(record_id))
        if not rows:
            raise HTTPException(404, "Record not found")
        return rows[0]

    @app.post("/api/v1/records", status_code=201)
    def add_record(payload: RecordCreate, p: PrincipalDep):
        if p.role == WorkspaceRole.VIEWER:
            raise HTTPException(403, "Read-only membership")
        entitlements.require(p, "records.write")
        return store.create_record(p, payload.title, payload.payload)

    @app.delete("/api/v1/records/{record_id}", status_code=204)
    def delete_record(record_id: UUID, p: PrincipalDep):
        if p.role == WorkspaceRole.VIEWER:
            raise HTTPException(403, "Read-only membership")
        entitlements.require(p, "records.write")
        if not store.delete_record(p, str(record_id)):
            raise HTTPException(404, "Record not found")
        return Response(status_code=204)

    @app.get("/api/v1/activity")
    def activity(p: PrincipalDep):
        return store.activity(p)

    from app_core.agent import register_agent_routes

    def refresh_agent_principal(request):
        return principal(identity(request), request.headers.get("X-Workspace"))

    register_agent_routes(app, store, PrincipalDep, refresh_agent_principal)
    from app_core.triage import register_triage_routes

    register_triage_routes(app, store, PrincipalDep, refresh_agent_principal)
    from app_core.bulk import register_bulk_routes

    register_bulk_routes(app, store, PrincipalDep)

    from app_core.tasks import register_task_routes

    register_task_routes(app, store, PrincipalDep)

    from app_core.task_drafts import register_task_draft_routes

    register_task_draft_routes(app, store, PrincipalDep, app.state.triage_service)
    from app_core.submitter_updates import register_submitter_update_routes

    register_submitter_update_routes(app, store, PrincipalDep, app.state.triage_service)

    from app_core.priority import register_priority_routes

    register_priority_routes(app, store, PrincipalDep, refresh_agent_principal)

    static_dir = os.getenv("APP_STATIC_DIR")
    if static_dir:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app
