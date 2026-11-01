from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["org_name"] = settings.org_name


def _dt(v, fmt="%d/%m/%Y %H:%M"):
    return v.strftime(fmt) if v else "—"


templates.env.filters["dt"] = _dt
