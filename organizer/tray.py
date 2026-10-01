"""System tray icon and menu."""
from PIL import Image, ImageDraw
import pystray


def icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(37, 99, 235))
    d.rectangle((28, 14, 36, 34), fill="white")  # arrow shaft
    d.polygon([(18, 32), (46, 32), (32, 46)], fill="white")  # arrow head
    d.rectangle((16, 49, 48, 53), fill="white")  # tray
    return img


def create(app) -> pystray.Icon:
    menu = pystray.Menu(
        pystray.MenuItem(lambda _item: app.status_text(), None, enabled=False),
        pystray.MenuItem("Review pending…", lambda _i, _m: app.open_review(), default=True),
        pystray.MenuItem("Pause", lambda _i, _m: app.toggle_pause(), checked=lambda _m: app.paused),
        pystray.MenuItem("Undo last move", lambda _i, _m: app.undo_last()),
        pystray.MenuItem("Rescan folders", lambda _i, _m: app.refresh_folders(force=True)),
        pystray.MenuItem("Open log folder", lambda _i, _m: app.open_state_dir()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda _i, _m: app.quit()),
    )
    return pystray.Icon("download_organizer", icon_image(), "Download Organizer", menu)
