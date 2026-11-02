import hashlib
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["org_name"] = settings.org_name
# Cache-busting token for the stylesheet: changes whenever style.css changes,
# so browsers fetch the new file after a deploy instead of using a stale copy.
templates.env.globals["css_v"] = hashlib.sha256(
    (Path(__file__).parent / "static" / "style.css").read_bytes()).hexdigest()[:10]


def _dt(v, fmt="%d/%m/%Y %H:%M"):
    return v.strftime(fmt) if v else "—"


templates.env.filters["dt"] = _dt
