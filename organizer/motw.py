"""Mark of the Web: the Zone.Identifier stream browsers attach to downloaded files."""
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ZONE_INTERNET = 3


@dataclass
class Motw:
    zone_id: int | None
    host_url: str | None
    referrer_url: str | None

    @property
    def from_internet(self) -> bool:
        return self.zone_id is not None and self.zone_id >= ZONE_INTERNET


def parse(raw: str) -> Motw:
    values = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.replace("\x00", "").strip()
    zone = values.get("zoneid")
    return Motw(
        zone_id=int(zone) if zone and zone.isdigit() else None,
        host_url=values.get("hosturl") or None,
        referrer_url=values.get("referrerurl") or None,
    )


def read(path: Path) -> Motw | None:
    try:
        with open(f"{path}:Zone.Identifier", encoding="utf-8", errors="replace") as f:
            return parse(f.read())
    except OSError:
        return None


def read_with_retry(path: Path, attempts: int = 4, delay_s: float = 1.0) -> Motw | None:
    """The browser can annotate the file a moment after the final rename."""
    for i in range(attempts):
        motw = read(path)
        if motw is not None:
            return motw
        if i < attempts - 1:
            time.sleep(delay_s)
    return None


def clean_url(url: str | None) -> str | None:
    """Drops query string and fragment, which often carry download tokens."""
    if not url:
        return None
    u = urlsplit(url)
    if not u.netloc:
        return None
    return f"{u.scheme}://{u.netloc}{u.path}"


_COURSE_PATH = re.compile(r"/courses/(\d+)")


def source_key(motw: Motw | None) -> str | None:
    """A stable identifier for where a download came from, e.g. a Canvas course.

    Only URLs that identify a course are used; a bare host like smallpdf.com says
    nothing about which folder a file belongs in.
    """
    if motw is None:
        return None
    for url in (motw.referrer_url, motw.host_url):
        if not url:
            continue
        u = urlsplit(url)
        m = _COURSE_PATH.search(u.path)
        if m and u.hostname:
            return f"{u.hostname}/courses/{m.group(1)}"
    return None
