"""Tool server_info — thông tin server từ snapshot cog gom (member_count/roles/channels)."""

_VALID = ("member_count", "roles", "channels")


def run_server_info(kind: str, snapshot: dict | None) -> str:
    snap = snapshot or {}
    if kind == "member_count":
        return f"Số thành viên: {snap.get('member_count', 0)}"
    if kind == "roles":
        roles = snap.get("roles") or []
        return "Roles: " + (", ".join(roles) if roles else "(không có)")
    if kind == "channels":
        chans = snap.get("channels") or []
        return "Kênh: " + (", ".join(chans) if chans else "(không có)")
    return f"kind không hợp lệ. Hợp lệ: {', '.join(_VALID)}"
