from enum import StrEnum


class LevelRoleMode(StrEnum):
    STACKING = "stacking"
    REPLACING = "replacing"


class NotificationMode(StrEnum):
    CHANNEL = "channel"
    DM = "dm"
    OFF = "off"


class BgType(StrEnum):
    SOLID = "solid"
    GRADIENT = "gradient"
