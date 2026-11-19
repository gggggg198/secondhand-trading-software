CREATE TABLE product (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seller_id BIGINT NOT NULL REFERENCES account(id),
    title TEXT NOT NULL DEFAULT '' CHECK (char_length(title) <= 60),
    description TEXT NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
    category TEXT NOT NULL DEFAULT '' CHECK (category IN
        ('', '书籍', '电子产品', '生活用品', '运动用品', '其他')),
    condition TEXT NOT NULL DEFAULT '' CHECK (condition IN
        ('', '全新', '九成新', '八成新', '七成新', '有明显使用痕迹')),
    price NUMERIC(8, 2) CHECK (price BETWEEN 0.01 AND 100000.00),
    status TEXT NOT NULL CHECK (status IN
        ('DRAFT', 'PENDING', 'REJECTED', 'PUBLISHED', 'RESERVED', 'SOLD', 'OFFLINE', 'BANNED')),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    approved_digest TEXT,
    CHECK ((published_at IS NULL) = (approved_digest IS NULL)),
    CHECK (status NOT IN ('PUBLISHED', 'RESERVED', 'SOLD', 'OFFLINE') OR published_at IS NOT NULL),
    CHECK (status NOT IN ('PUBLISHED', 'RESERVED', 'SOLD', 'PENDING') OR
        (title <> '' AND description <> '' AND category <> '' AND condition <> '' AND price IS NOT NULL))
);

CREATE INDEX product_public_order ON product (published_at DESC, id) WHERE status = 'PUBLISHED';
CREATE INDEX product_seller_order ON product (seller_id, published_at DESC NULLS LAST, id);

CREATE TABLE uploaded_image (
    id UUID PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES account(id),
    media_type TEXT NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png')),
    content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 5242880)
);

CREATE TABLE product_image (
    product_id BIGINT NOT NULL REFERENCES product(id),
    image_id UUID NOT NULL REFERENCES uploaded_image(id),
    position SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 5),
    PRIMARY KEY (product_id, position),
    UNIQUE (product_id, image_id)
);

CREATE INDEX product_image_reverse ON product_image (image_id, product_id);

CREATE TABLE review_submission (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product(id),
    content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN')),
    submitted_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolved_by BIGINT REFERENCES account(id),
    reason TEXT NOT NULL DEFAULT '',
    CHECK ((status = 'PENDING') = (resolved_at IS NULL)),
    CHECK ((resolved_at IS NULL) = (resolved_by IS NULL))
);

CREATE UNIQUE INDEX review_pending ON review_submission (product_id) WHERE status = 'PENDING';
CREATE INDEX review_latest ON review_submission (product_id, id DESC);

CREATE TABLE reservation (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product(id),
    buyer_id BIGINT NOT NULL REFERENCES account(id),
    product_title TEXT NOT NULL,
    price NUMERIC(8, 2) NOT NULL CHECK (price BETWEEN 0.01 AND 100000.00),
    location TEXT NOT NULL CHECK (char_length(location) BETWEEN 2 AND 100),
    meeting_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN
        ('PENDING', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'REJECTED', 'EXPIRED')),
    reason TEXT NOT NULL DEFAULT '',
    platform_cancelled BOOLEAN NOT NULL DEFAULT false,
    CHECK (meeting_at > created_at),
    CHECK ((status = 'COMPLETED') = (completed_at IS NOT NULL)),
    CHECK (NOT platform_cancelled OR status = 'CANCELLED')
);

CREATE UNIQUE INDEX reservation_active ON reservation(product_id)
    WHERE status IN ('PENDING', 'CONFIRMED');
CREATE UNIQUE INDEX reservation_completed ON reservation(product_id) WHERE status = 'COMPLETED';
CREATE INDEX reservation_by_buyer ON reservation (buyer_id, id DESC);
CREATE INDEX reservation_by_product ON reservation (product_id, id DESC);
CREATE INDEX reservation_pending_scan ON reservation (created_at, meeting_at) WHERE status = 'PENDING';
CREATE INDEX reservation_close_time ON reservation (completed_at) WHERE status = 'COMPLETED';

CREATE TABLE operation_result (
    actor_ref TEXT NOT NULL,
    action TEXT NOT NULL,
    submission_key UUID NOT NULL,
    request_digest TEXT NOT NULL,
    product_id BIGINT REFERENCES product(id),
    reservation_id BIGINT REFERENCES reservation(id),
    review_id BIGINT REFERENCES review_submission(id),
    http_status SMALLINT NOT NULL CHECK (http_status BETWEEN 200 AND 499),
    body JSONB NOT NULL CHECK (jsonb_typeof(body) = 'object'),
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (actor_ref, action, submission_key)
);

CREATE TABLE audit_entry (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id BIGINT REFERENCES account(id),
    action TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('product', 'reservation', 'review', 'account')),
    target_id BIGINT,
    product_id BIGINT REFERENCES product(id),
    reservation_id BIGINT REFERENCES reservation(id),
    before_state TEXT,
    after_state TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('SUCCESS', 'FAILURE', 'ACCESS')),
    reason TEXT NOT NULL DEFAULT '',
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX audit_time ON audit_entry (recorded_at DESC, id DESC);
CREATE INDEX audit_product ON audit_entry (product_id, id DESC);
CREATE INDEX audit_reservation ON audit_entry (reservation_id, id DESC);

CREATE TABLE product_violation (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product(id),
    administrator_id BIGINT NOT NULL REFERENCES account(id),
    reason TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE favorite (
    account_id BIGINT NOT NULL REFERENCES account(id),
    product_id BIGINT NOT NULL REFERENCES product(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, product_id)
);

CREATE INDEX favorite_count ON favorite (product_id);
