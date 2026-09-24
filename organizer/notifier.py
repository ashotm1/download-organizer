"""Windows toast notifications with buttons; falls back to Tk popups."""
import logging
from typing import Callable

from .ui import UI

log = logging.getLogger(__name__)

APP_NAME = "Download Organizer"


class Notifier:
    def __init__(self, mode: str, ui: UI):
        self.ui = ui
        self._toaster = None
        if mode == "toast":
            try:
                from windows_toasts import InteractableWindowsToaster
                self._toaster = InteractableWindowsToaster(APP_NAME)
            except Exception as e:
                log.warning("toasts unavailable, using popups: %s", e)

    def show(self, title: str, body: str, buttons: list[tuple[str, str]],
             on_choice: Callable[[str], None] | None = None, sticky: bool = False) -> None:
        """buttons: (label, key). on_choice gets the key, "body" for a click on the toast, or "dismiss".

        on_choice may run on a notification thread; callers must hand real work off.
        """
        on_choice = on_choice or (lambda _key: None)
        if self._toaster is not None:
            try:
                self._show_toast(title, body, buttons, on_choice, sticky)
                return
            except Exception as e:
                log.warning("toast failed, using popup: %s", e)
        self.ui.call(self.ui.popup, title, body, buttons, on_choice, None if sticky else 12)

    def _show_toast(self, title, body, buttons, on_choice, sticky) -> None:
        from windows_toasts import Toast, ToastButton, ToastDuration

        toast = Toast([title, body], duration=ToastDuration.Long if sticky else ToastDuration.Default)
        for label, key in buttons[:5]:
            toast.AddAction(ToastButton(label, arguments=key))
        toast.on_activated = lambda args: on_choice(args.arguments or "body")
        self._toaster.show_toast(toast)
