"""Tool server_info — server info from the snapshot the cog assembles (member_count/roles/channels)."""

_VALID = ("member_count", "roles", "channels")


def run_server_info(kind: str, snapshot: dict | None) -> str:
    snap = snapshot or {}
    if kind == "member_count":
        return f"Member count: {snap.get('member_count', 0)}"
    if kind == "roles":
        roles = snap.get("roles") or []
        return "Roles: " + (", ".join(roles) if roles else "(none)")
    if kind == "channels":
        chans = snap.get("channels") or []
        return "Channels: " + (", ".join(chans) if chans else "(none)")
    return f"Invalid kind. Valid: {', '.join(_VALID)}"
