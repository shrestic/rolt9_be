"""Pure template rendering for welcome/leave messages.

Supports three placeholders: {user}, {server}, {count}. Uses plain str.replace
(not str.format) so stray braces in an admin's template can never raise.
"""


def render_template(template: str, *, user: str, server: str, count: int) -> str:
    """Substitute {user}/{server}/{count} into `template`."""
    return (
        template.replace("{user}", user).replace("{server}", server).replace("{count}", str(count))
    )
