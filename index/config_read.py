from configparser import ConfigParser
import os
from typing import Any, Callable

def _get(config: ConfigParser, section: str, key: str,
         *, default: Any = None, required: bool = False,
         cast: Callable[[str], Any] | None = None,
         env_prefix: str | None = "IGSR",
         env_alt: list[str] | None = None) -> Any:
    """
    Read a value from config with flexible env overrides.

    Precedence:
      1) Environment variable: {env_prefix}_{section}_{key} (e.g., IGSR_ELASTICSEARCH_API_KEY)
      2) Any 'env_alt' names provided (e.g., ES_API_KEY)
      3) config.ini [{section}] key
      4) default (or error if required and default is None)
    """
    # Primary env var: IGSR_<SECTION>_<KEY>
    env_name = f"{env_prefix}_{section}_{key}".upper() if env_prefix else None
    if env_name and env_name in os.environ:
        val = os.environ[env_name]
    else:
        # Alternate env names (e.g. ES_HOST / ES_API_KEY)
        if env_alt:
            for alt in env_alt:
                if alt in os.environ:
                    val = os.environ[alt]
                    break
            else:
                val = None
        else:
            val = None

        if val is None:
            if not config.has_section(section) or not config.has_option(section, key):
                if required and default is None:
                    raise KeyError(f"Missing [{section}] {key} in config and no env override")
                return default
            val = config.get(section, key)

    return cast(val) if (cast and isinstance(val, str)) else val

def read_from_config_file(config_file: str) -> dict[str, Any]:
    """
    Returns a dict with:
      - top-level DB + site keys (back-compat with your current fetchers)
      - 'elasticsearch' nested block with host/cloud_id/api_key/username/password
    """
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
    data["site_root"] = _get(cfg, "site", "site_root", required=True)
    data["site_base"] = _get(cfg, "site", "site_base", required=True)

    # elasticsearch config
    es_cfg = {
        "host":     _get(cfg, "elasticsearch", "host",     default=None, env_alt=["ES_HOST"]),
        "cloud_id": _get(cfg, "elasticsearch", "cloud_id", default=None, env_alt=["ES_CLOUD_ID"]),
        "api_key":  _get(cfg, "elasticsearch", "api_key",  default=None, env_alt=["ES_API_KEY"]),
        "username": _get(cfg, "elasticsearch", "username", default=None, env_alt=["ES_USERNAME"]),
        "password": _get(cfg, "elasticsearch", "password", default=None, env_alt=["ES_PASSWORD"]),
    }
    # Drop None values so callers can do .get() safely
    data["elasticsearch"] = {k: v for k, v in es_cfg.items() if v is not None}

    return data