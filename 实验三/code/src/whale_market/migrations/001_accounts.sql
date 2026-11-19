CREATE TABLE account (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL CHECK (username COLLATE "C" ~ '^[A-Za-z0-9_]{4,20}$'),
    username_key TEXT GENERATED ALWAYS AS (lower(username COLLATE "C")) STORED UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE account_session (
    token_digest BYTEA PRIMARY KEY CHECK (octet_length(token_digest) = 32),
    account_id BIGINT NOT NULL REFERENCES account (id) ON DELETE CASCADE,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > issued_at)
);
