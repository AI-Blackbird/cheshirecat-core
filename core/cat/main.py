import os
import uvicorn

from cat.env import get_env
from cat.utils import get_plugins_path

# RUN!
if __name__ == "__main__":
    # debugging utilities, to deactivate put `DEBUG=false` in .env
    debug_config = {}
    if get_env("CCAT_DEBUG") == "true":
        debug_config = {
            "reload": True,
            "reload_excludes": ["*test_*.*", "*mock_*.*", os.path.join(get_plugins_path(), "*", "*.*")],
        }
    # uvicorn running behind an https proxy
    proxy_pass_config = {}
    if get_env("CCAT_HTTPS_PROXY_MODE") in ("1", "true"):
        proxy_pass_config = {
            "proxy_headers": True,
            "forwarded_allow_ips": get_env("CCAT_CORS_FORWARDED_ALLOW_IPS"),
        }
    # cast workers and limit_max_requests to int if they are set
    workers = None
    limit_max_requests = None
    if get_env("CCAT_WORKERS"):
        workers = int(get_env("CCAT_WORKERS"))

    if get_env("CCAT_LIMIT_MAX_REQUESTS"):
        limit_max_requests = int(get_env("CCAT_LIMIT_MAX_REQUESTS"))

    uvicorn.run(
        "cat.startup:cheshire_cat_api",
        host="0.0.0.0",
        port=80,
        use_colors=True,
        workers=workers,
        limit_max_requests=limit_max_requests,
        log_level=get_env("CCAT_LOG_LEVEL").lower(),
        **debug_config,
        **proxy_pass_config,
    )
