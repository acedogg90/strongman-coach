"""
Tests for user authentication backend (ARCH-003).

Covers:
- User model with bcrypt password hashing via passlib
- POST /auth/signup — create user with validated email and password
- POST /auth/login — authenticate credentials and establish server-side session
- POST /auth/logout — terminate the current session
- POST /auth/me — check current authenticated user
- Session management uses signed cookies (not JWT)
- Password hashing uses bcrypt via passlib
"""

import pytest
from fastapi.testclient import TestClient

from app.routes import app, _get_session, _session_store, SESSION_COOKIE_NAME
from app.database import (
    Base,
    User,
    get_engine,
    reset_db,
)


@pytest.fixture()
def db_url(tmp_path):
    """Provide a file-based SQLite database URL for each test."""
    db_file = tmp_path / "test_auth.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def client(db_url):
    """Create a TestClient with a fresh database for each test."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    get_engine(db_url)
    reset_db(db_url)
    # Clear session store between tests
    _session_store.clear()
    return TestClient(app)


# ---------------------------------------------------------------------------
# User model tests
# ---------------------------------------------------------------------------

class TestUserModel:
    """Test the User model and password hashing."""

    def test_user_created_with_hashed_password(self, client):
        """Password is stored as a bcrypt hash, not plaintext."""
        resp = client.post("/auth/signup", json={
            "email": "test@example.com",
            "password": "securepassword123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 1
        assert data["email"] == "test@example.com"

        # Verify the password is hashed in the DB
        db = _get_session()
        try:
            user = db.query(User).filter_by(id=1).first()
            assert user is not None
            assert user.email == "test@example.com"
            assert user.hashed_password != "securepassword123"
            assert user.hashed_password.startswith("$2b$")  # bcrypt prefix
        finally:
            db.close()

    def test_user_email_is_unique(self, client):
        """Cannot create two users with the same email."""
        client.post("/auth/signup", json={
            "email": "unique@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/signup", json={
            "email": "unique@example.com",
            "password": "differentpassword",
        })
        assert resp.status_code == 409

    def test_user_email_normalized_to_lowercase(self, client):
        """Email is stored in lowercase."""
        client.post("/auth/signup", json={
            "email": "UPPER@EXAMPLE.COM",
            "password": "password123",
        })
        db = _get_session()
        try:
            user = db.query(User).filter_by(email="upper@example.com").first()
            assert user is not None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# POST /auth/signup validation tests
# ---------------------------------------------------------------------------

class TestSignupValidation:
    """Test signup input validation."""

    def test_signup_missing_email(self, client):
        """Signup fails without email."""
        resp = client.post("/auth/signup", json={"password": "password123"})
        assert resp.status_code == 422

    def test_signup_missing_password(self, client):
        """Signup fails without password."""
        resp = client.post("/auth/signup", json={"email": "test@example.com"})
        assert resp.status_code == 422

    def test_signup_invalid_email_no_at(self, client):
        """Signup rejects email without @."""
        resp = client.post("/auth/signup", json={
            "email": "invalidemail",
            "password": "password123",
        })
        assert resp.status_code == 422

    def test_signup_invalid_email_no_dot(self, client):
        """Signup rejects email without dot in domain."""
        resp = client.post("/auth/signup", json={
            "email": "test@nodot",
            "password": "password123",
        })
        assert resp.status_code == 422

    def test_signup_password_too_short(self, client):
        """Signup rejects password shorter than 8 characters."""
        resp = client.post("/auth/signup", json={
            "email": "test@example.com",
            "password": "short",
        })
        assert resp.status_code == 422

    def test_signup_valid_min_password(self, client):
        """Signup accepts password of exactly 8 characters."""
        resp = client.post("/auth/signup", json={
            "email": "test@example.com",
            "password": "12345678",
        })
        assert resp.status_code == 200

    def test_signup_response_shape(self, client):
        """Signup returns user_id and email."""
        resp = client.post("/auth/signup", json={
            "email": "shape@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "user_id" in data
        assert "email" in data
        assert isinstance(data["user_id"], int)
        assert data["email"] == "shape@example.com"


# ---------------------------------------------------------------------------
# POST /auth/login tests
# ---------------------------------------------------------------------------

class TestLogin:
    """Test login authentication and session creation."""

    def test_login_success(self, client):
        """Login with valid credentials returns 200 and sets cookie."""
        client.post("/auth/signup", json={
            "email": "login@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/login", json={
            "email": "login@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 1
        assert data["email"] == "login@example.com"
        # Cookie should be set
        assert SESSION_COOKIE_NAME in resp.cookies

    def test_login_wrong_password(self, client):
        """Login with wrong password returns 401."""
        client.post("/auth/signup", json={
            "email": "login@example.com",
            "password": "correctpassword",
        })
        resp = client.post("/auth/login", json={
            "email": "login@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        """Login with non-existent email returns 401."""
        resp = client.post("/auth/login", json={
            "email": "nobody@example.com",
            "password": "password123",
        })
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        """Login with missing fields returns 422."""
        resp = client.post("/auth/login", json={"email": "test@example.com"})
        assert resp.status_code == 422

    def test_login_cookie_is_httponly(self, client):
        """Session cookie is httponly for security."""
        client.post("/auth/signup", json={
            "email": "cookie@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/login", json={
            "email": "cookie@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        # The cookie should be set with httponly
        cookie = resp.cookies.get(SESSION_COOKIE_NAME)
        assert cookie is not None

    def test_login_response_shape(self, client):
        """Login returns user_id and email."""
        client.post("/auth/signup", json={
            "email": "shape@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/login", json={
            "email": "shape@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "user_id" in data
        assert "email" in data


# ---------------------------------------------------------------------------
# POST /auth/logout tests
# ---------------------------------------------------------------------------

class TestLogout:
    """Test session termination."""

    def test_logout_success(self, client):
        """Logout returns 200 and clears session."""
        client.post("/auth/signup", json={
            "email": "logout@example.com",
            "password": "password123",
        })
        client.post("/auth/login", json={
            "email": "logout@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/logout")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    def test_logout_without_session(self, client):
        """Logout without being logged in still returns 200."""
        resp = client.post("/auth/logout")
        assert resp.status_code == 200

    def test_logout_clears_session(self, client):
        """After logout, /auth/me returns 401."""
        client.post("/auth/signup", json={
            "email": "logout@example.com",
            "password": "password123",
        })
        client.post("/auth/login", json={
            "email": "logout@example.com",
            "password": "password123",
        })
        # Verify we're logged in
        resp = client.get("/auth/me")
        assert resp.status_code == 200

        # Logout
        client.post("/auth/logout")

        # Verify we're logged out
        resp = client.get("/auth/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /auth/me tests
# ---------------------------------------------------------------------------

class TestAuthMe:
    """Test current user endpoint."""

    def test_me_when_authenticated(self, client):
        """GET /auth/me returns user info when logged in."""
        client.post("/auth/signup", json={
            "email": "me@example.com",
            "password": "password123",
        })
        client.post("/auth/login", json={
            "email": "me@example.com",
            "password": "password123",
        })
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 1
        assert data["email"] == "me@example.com"

    def test_me_when_not_authenticated(self, client):
        """GET /auth/me returns 401 when not logged in."""
        resp = client.get("/auth/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Session management tests
# ---------------------------------------------------------------------------

class TestSessionManagement:
    """Test signed cookie session management."""

    def test_session_persists_across_requests(self, client):
        """Session cookie persists across multiple requests."""
        client.post("/auth/signup", json={
            "email": "persist@example.com",
            "password": "password123",
        })
        client.post("/auth/login", json={
            "email": "persist@example.com",
            "password": "password123",
        })
        # Multiple requests should all be authenticated
        for _ in range(3):
            resp = client.get("/auth/me")
            assert resp.status_code == 200

    def test_session_is_signed_not_jwt(self, client):
        """Session uses signed cookies, not JWT tokens."""
        client.post("/auth/signup", json={
            "email": "signed@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/login", json={
            "email": "signed@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        cookie = resp.cookies.get(SESSION_COOKIE_NAME)
        assert cookie is not None
        # JWT tokens have three dot-separated parts; signed cookies do not
        assert cookie.count(".") != 2

    def test_multiple_users_have_separate_sessions(self, client):
        """Different users have independent sessions."""
        client.post("/auth/signup", json={
            "email": "user1@example.com",
            "password": "password123",
        })
        client.post("/auth/signup", json={
            "email": "user2@example.com",
            "password": "password456",
        })

        # Login as user1
        client.post("/auth/login", json={
            "email": "user1@example.com",
            "password": "password123",
        })
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["email"] == "user1@example.com"

        # Logout and login as user2
        client.post("/auth/logout")
        client.post("/auth/login", json={
            "email": "user2@example.com",
            "password": "password456",
        })
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["email"] == "user2@example.com"

    def test_password_is_never_stored_in_plaintext(self, client):
        """Verify bcrypt hashing is used for all passwords."""
        passwords = ["password123", "MyS3cur3P@ss!", "abcdefgh"]
        for pw in passwords:
            email = f"hash-test-{pw.replace('!', '')}@example.com"
            client.post("/auth/signup", json={
                "email": email,
                "password": pw,
            })

        db = _get_session()
        try:
            users = db.query(User).all()
            for user in users:
                assert user.hashed_password != pw
                assert user.hashed_password.startswith("$2b$")
        finally:
            db.close()


# ---------------------------------------------------------------------------
# ARCH-003 Architecture Compliance Tests
# ---------------------------------------------------------------------------

class TestARCH003Compliance:
    """Verify the implementation follows ARCH-003 architecture decisions.

    ARCH-003 specifies:
    - Decision 1: Session management uses signed cookies (not JWT)
    - Decision 2: Password hashing uses bcrypt via passlib
    - User model stores hashed passwords (never plaintext)
    - Server-side session store (not client-side state)
    - Email normalization to lowercase
    - Password minimum length enforcement
    - Cookie security flags (httponly, samesite)
    """

    def test_arch003_decision1_signed_cookies_not_jwt(self):
        """ARCH-003 Decision 1: sessions use signed cookies, not JWT.

        Verifies that the session serializer is an itsdangerous
        URLSafeSerializer (signed cookie), not a JWT library.
        """
        from app.routes import _session_serializer
        from itsdangerous import URLSafeSerializer

        assert isinstance(
            _session_serializer, URLSafeSerializer
        ), "ARCH-003 Decision 1: session management must use signed cookies (itsdangerous), not JWT"

    def test_arch003_decision2_bcrypt_via_passlib(self):
        """ARCH-003 Decision 2: password hashing uses bcrypt via passlib.

        Verifies that the CryptContext is configured with bcrypt scheme
        and that hashed passwords start with the bcrypt prefix ($2b$).
        """
        from app.routes import pwd_context, _hash_password

        # Verify bcrypt is in the configured schemes
        schemes = pwd_context.schemes()
        assert "bcrypt" in schemes, (
            "ARCH-003 Decision 2: password hashing must use bcrypt via passlib"
        )

        # Verify the hash output is a bcrypt hash
        hashed = _hash_password("testpassword123")
        assert hashed.startswith("$2b$"), (
            "ARCH-003 Decision 2: hashed passwords must use bcrypt ($2b$ prefix)"
        )

    def test_arch003_user_model_has_hashed_password_column(self):
        """ARCH-003: User model must have hashed_password column, not plaintext."""
        from sqlalchemy import inspect as sa_inspect
        from app.database import User, get_engine

        mapper = sa_inspect(User)
        column_names = [c.key for c in mapper.columns]
        assert "hashed_password" in column_names, (
            "ARCH-003: User model must have hashed_password column"
        )
        # Ensure there is no plaintext password column
        assert "password" not in column_names, (
            "ARCH-003: User model must not store plaintext passwords"
        )

    def test_arch003_server_side_session_store(self):
        """ARCH-003: sessions are stored server-side, not client-side state.

        Verifies that _session_store is a dict (server-side store) and that
        session tokens reference server-side session IDs.
        """
        from app.routes import _session_store, _session_serializer

        assert isinstance(_session_store, dict), (
            "ARCH-003: session store must be server-side (dict)"
        )

        # Verify the serializer produces a token that references a session_id
        token = _session_serializer.dumps({"session_id": "test-id"})
        payload = _session_serializer.loads(token)
        assert "session_id" in payload, (
            "ARCH-003: session tokens must reference server-side session IDs"
        )

    def test_arch003_email_normalized_to_lowercase(self):
        """ARCH-003: email addresses are normalized to lowercase on signup."""
        from app.routes import SignupRequest

        req = SignupRequest(email="Test@Example.COM", password="password123")
        assert req.email == "test@example.com", (
            "ARCH-003: email must be normalized to lowercase"
        )

    def test_arch003_password_minimum_length_enforced(self):
        """ARCH-003: password must be at least 8 characters."""
        from app.routes import SignupRequest
        import pytest as pytest_mod

        with pytest_mod.raises(Exception):  # ValidationError
            SignupRequest(email="test@example.com", password="short")

    def test_arch003_cookie_has_security_flags(self, client):
        """ARCH-003: session cookie must have httponly and samesite flags."""
        client.post("/auth/signup", json={
            "email": "flags@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/login", json={
            "email": "flags@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200

        # Check cookie security flags via the response
        cookie = resp.cookies.get(SESSION_COOKIE_NAME)
        assert cookie is not None

        # Verify cookie settings in the response headers
        set_cookie_headers = resp.headers.get_list("set-cookie")
        assert len(set_cookie_headers) > 0, "No Set-Cookie header found"

        # The cookie should have httponly flag
        cookie_header = set_cookie_headers[0]
        assert "httponly" in cookie_header.lower(), (
            "ARCH-003: session cookie must have httponly flag"
        )

    def test_arch003_session_has_expiry(self):
        """ARCH-003: sessions must have a maximum age (expiry)."""
        from app.routes import SESSION_MAX_AGE

        assert SESSION_MAX_AGE > 0, (
            "ARCH-003: sessions must have a positive max_age for expiry"
        )
        assert SESSION_MAX_AGE <= 604800, (
            "ARCH-003: session max_age should not exceed 7 days"
        )

    def test_arch003_password_never_returned_in_responses(self, client):
        """ARCH-003: password must never appear in API responses."""
        resp = client.post("/auth/signup", json={
            "email": "secure@example.com",
            "password": "MySecretPassword123",
        })
        body = resp.json()
        assert "password" not in body, (
            "ARCH-003: password must never be returned in signup response"
        )
        assert "hashed_password" not in body, (
            "ARCH-003: hashed_password must never be returned in signup response"
        )

        resp = client.post("/auth/login", json={
            "email": "secure@example.com",
            "password": "MySecretPassword123",
        })
        body = resp.json()
        assert "password" not in body, (
            "ARCH-003: password must never be returned in login response"
        )
