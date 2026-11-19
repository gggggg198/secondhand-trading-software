from io import BytesIO
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from .accounts import Account
from .db import open_database
from .domain import IMAGE_LIMIT, Problem, missing
from .queries import actor_id, has_admin_access

FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG"}


def save_upload(
    database_url: str, actor: Account, media_type: str, content: bytes
) -> UUID:
    if not 1 <= len(content) <= IMAGE_LIMIT:
        raise Problem(413, "image_size", "请选择大小在 5 MiB 以内的 JPEG 或 PNG 图片。")
    expected = FORMATS.get(media_type)
    if expected is None:
        raise Problem(415, "image_type", "请选择 JPEG 或 PNG 图片。")
    try:
        with Image.open(BytesIO(content), formats=[expected]) as image:
            image.verify()
        with Image.open(BytesIO(content), formats=[expected]) as image:
            image.load()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
    ):
        raise Problem(
            422, "invalid_image", "图片无法正确读取，请重新选择图片。"
        ) from None
    image_id = uuid4()
    with open_database(database_url) as connection:
        connection.execute(
            "INSERT INTO uploaded_image (id, owner_id, media_type, content) VALUES (%s, %s, %s, %s)",
            (image_id, actor.id, media_type, content),
        )
    return image_id


def get_upload(
    database_url: str, actor: Account | None, image_id: UUID
) -> tuple[str, bytes]:
    with open_database(database_url) as connection:
        admin = has_admin_access(connection, actor)
        row = connection.execute(
            """
            SELECT i.media_type, i.content FROM uploaded_image i
            WHERE i.id = %s AND (i.owner_id = %s OR %s OR EXISTS(
                SELECT 1 FROM product_image pi JOIN product p ON p.id = pi.product_id
                WHERE pi.image_id = i.id AND p.status = 'PUBLISHED'
            ))
            """,
            (image_id, actor_id(actor), admin),
        ).fetchone()
    if row is None:
        raise missing("图片")
    return row["media_type"], row["content"]
