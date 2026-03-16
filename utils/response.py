from fastapi.responses import JSONResponse
from typing import Any


def ok(data: Any = None, msg: str = "Success", status: int = 200):
    return JSONResponse({"success": True, "message": msg, "data": data}, status_code=status)

def created(data: Any = None, msg: str = "Created"):
    return ok(data, msg, 201)

def err(msg: str, status: int = 400, errors: Any = None):
    body = {"success": False, "message": msg}
    if errors: body["errors"] = errors
    return JSONResponse(body, status_code=status)

def paged(items: list, total: int, page: int, per: int):
    return JSONResponse({"success": True, "data": items,
        "pagination": {"total": total, "page": page, "per_page": per,
                       "total_pages": -(-total // per) if per else 1}})
