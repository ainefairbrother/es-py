# index/config_read.py
from configparser import ConfigParser
import os
from typing import Any, Callable

def _get(config: ConfigParser, section: str, key: str,
         *, default: Any = None, required: bool = False,
         cast: Callable[[str], Any] | None = None,
         env_prefix: str | None = "IGSR") -> Any:
    env_name = f"{env_prefix}_{section}_{key}".upper() if env_prefix else None
    if env_name and env_name in os.environ:
        val = os.environ[env_name]
    else:
        if not config.has_section(section) or not config.has_option(section, key):
            if required and default is None:
                raise KeyError(f"Missing [{section}] {key} in config and no env override")
            return default
        val = config.get(section, key)

    return cast(val) if cast else val

def read_from_config_file(config_file: str) -> dict[str, Any]:
    cfg = ConfigParser()
    cfg.read(config_file)

    data: dict[str, Any] = {}

    # database connection config
    data["host"]     = _get(cfg, "database", "host", required=True)
    data["port"]     = _get(cfg, "database", "port", required=True)
    data["user"]     = _get(cfg, "database", "user", required=True)
    data["database"] = _get(cfg, "database", "name", required=True)
    data["password"] = _get(cfg, "database", "password", required=True)

    # site config (used by the sitemap fetcher)
    data["site_root"]     = _get(cfg, "site", "site_root", required=True)
    data["site_base"]     = _get(cfg, "site", "site_base", required=True)

    return data