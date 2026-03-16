from fastapi import APIRouter, Depends, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db, setting
from middleware.auth import get_current_user
from utils.response import ok, created, err, paged
import aiofiles, os, secrets, mimetypes

router = APIRouter()

ALLOWED = {
    "image/jpeg","image/png","image/gif","image/webp","image/svg+xml",
    "video/mp4","video/webm","video/quicktime",
    "audio/mpeg","audio/ogg","audio/wav",
    "application/pdf","application/zip","text/plain","text/csv",
}


@router.post("/")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    plan = user["plan"]
    max_mb = int(await setting(db, "free_max_upload_mb" if plan=="free" else "pro_max_upload_mb", "100"))
    max_bytes = max_mb * 1024 * 1024

    content = await file.read()
    if len(content) > max_bytes:
        return err(f"File too large. Max {max_mb} MB on your plan.")

    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if mime not in ALLOWED:
        return err(f"File type '{mime}' not allowed.")

    # Storage quota
    storage_gb = int(await setting(db, "free_storage_gb" if plan=="free" else "pro_storage_gb", "50"))
    quota = storage_gb * 1024 * 1024 * 1024
    used = user.get("storage_used", 0)
    if used + len(content) > quota:
        return err("Storage quota exceeded. Upgrade your plan.")

    ext = os.path.splitext(file.filename or "file")[1].lower() or ".bin"
    stored_name = secrets.token_hex(16) + ext
    share_token = secrets.token_hex(12)
    upload_dir = "/tmp/mfp_uploads"
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, stored_name)

    async with aiofiles.open(path, "wb") as f:
        await f.write(content)

    site_url = await setting(db, "site_url", "https://yourdomain.cpanelfree.com")
    public_url = f"{site_url}/storage/uploads/{stored_name}"

    r = await db.execute(
        text("""
            INSERT INTO files(user_id,original_name,stored_name,file_path,public_url,
                              mime_type,size_bytes,share_token)
            VALUES(:uid,:on,:sn,:fp,:pu,:mt,:sb,:st)
        """),
        {"uid": user["id"], "on": file.filename, "sn": stored_name,
         "fp": path, "pu": public_url, "mt": mime,
         "sb": len(content), "st": share_token}
    )
    await db.execute(
        text("UPDATE users SET storage_used=storage_used+:s WHERE id=:id"),
        {"s": len(content), "id": user["id"]}
    )

    return created({
        "id": r.lastrowid, "name": file.filename, "url": public_url,
        "share_url": f"{site_url}/share/{share_token}",
        "size": len(content), "mime": mime,
    })


@router.get("/list")
async def list_files(page: int=1, per_page: int=20,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    uid = user["id"]
    total = (await db.execute(text("SELECT COUNT(*) FROM files WHERE user_id=:id AND is_deleted=0"), {"id": uid})).scalar()
    offset = (page-1)*per_page
    rows = await db.execute(
        text("SELECT id,uuid,original_name,public_url,share_token,mime_type,size_bytes,created_at FROM files WHERE user_id=:id AND is_deleted=0 ORDER BY created_at DESC LIMIT :l OFFSET :o"),
        {"id": uid, "l": per_page, "o": offset}
    )
    return paged([dict(r._mapping) for r in rows], total, page, per_page)


@router.delete("/{file_id}")
async def delete_file(file_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    f = (await db.execute(
        text("SELECT id,size_bytes FROM files WHERE id=:id AND user_id=:uid AND is_deleted=0"),
        {"id": file_id, "uid": user["id"]}
    )).fetchone()
    if not f:
        return err("File not found.", 404)
    await db.execute(text("UPDATE files SET is_deleted=1 WHERE id=:id"), {"id": file_id})
    await db.execute(text("UPDATE users SET storage_used=GREATEST(0,storage_used-:s) WHERE id=:id"),
                     {"s": f.size_bytes, "id": user["id"]})
    return ok(msg="File deleted.")
