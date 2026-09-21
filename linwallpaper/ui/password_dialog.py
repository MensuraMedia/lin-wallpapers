"""In-app password dialog for the privileged (root) surfaces.

This machine has ``pkexec``/``polkitd`` but no *session* polkit authentication
agent running, so the normal pkexec GUI prompt never appears. We therefore
collect the password ourselves in a small modal and hand it to the privileged
helper:

  * If a polkit **authentication agent** is detected, prefer ``pkexec`` (its own
    agent does the prompting; the typed password is not needed and is cleared).
  * Otherwise fall back to ``sudo -S -k -p ''`` and pipe the password on
    **stdin only** — never as an argument, never logged, never persisted.

The password lives only in a local variable for the duration of one subprocess
call and is dropped immediately afterwards. A toast reports success or failure;
a wrong password makes sudo/pkexec exit non-zero and yields
"Authentication failed" with no crash.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from ..privileged import HELPER

# Human labels for the three privileged surfaces.
SURFACE_LABELS = {
    "login": "the login screen",
    "splash": "the boot splash",
    "grub": "the boot menu",
}

# update-initramfs / update-grub can take a couple of minutes.
_TIMEOUT = 600

_PY = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"


def _has_polkit_agent() -> bool:
    """True if a *session* polkit authentication agent is running.

    We look for a process whose name/cmdline contains
    ``authentication-agent`` (polkit-gnome, polkit-mate, lxpolkit,
    polkit-kde, …). ``polkitd`` alone is NOT an agent.
    """
    try:
        out = subprocess.run(
            ["pgrep", "-fa", "authentication-agent"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def detect_auth_method() -> str:
    """Return ``"pkexec"`` if an agent is present and usable, else ``"sudo"``."""
    if _has_polkit_agent() and shutil.which("pkexec"):
        return "pkexec"
    return "sudo"


def _helper_argv(surface: str, image: str, fit: str, res: str) -> list[str]:
    return [
        _PY,
        str(HELPER),
        surface,
        "--image",
        image,
        "--fit",
        fit,
        "--res",
        res,
    ]


def build_command(method: str, helper_argv: list[str]) -> list[str]:
    """Wrap the helper invocation in the chosen privilege escalator."""
    if method == "pkexec":
        return ["pkexec", *helper_argv]
    # -S: read password from stdin; -k: ignore any cached credential;
    # -p '': suppress sudo's own prompt text (we prompt in the GUI).
    return ["sudo", "-S", "-k", "-p", "", *helper_argv]


def _run_privileged_blocking(
    method: str, argv: list[str], password: str | None
) -> tuple[bool, str]:
    """Run ``argv`` once; return ``(ok, message)``. Never raises.

    ``password`` is fed on stdin for the sudo path and is dropped when this
    function returns.
    """
    try:
        stdin_text = None
        if method == "sudo" and password is not None:
            stdin_text = password + "\n"
        proc = subprocess.run(
            argv,
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "The privileged helper timed out."
    except OSError as exc:
        return False, f"Could not launch the privileged helper: {exc}"
    finally:
        # Do not keep the secret around a moment longer than needed.
        password = None

    if proc.returncode == 0:
        return True, "Applied."
    # A non-zero exit from sudo/pkexec on bad auth, or a helper error.
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = tail[-1] if tail else ""
    if proc.returncode in (1,) and ("password" in detail.lower() or "auth" in detail.lower()):
        return False, "Authentication failed."
    if not detail:
        return False, "Authentication failed."
    return False, detail


class PasswordDialog(Adw.Window):
    """A masked-password modal with Cancel / Apply.

    :param on_submit: called with the entered password string when the user
        confirms; the dialog does not itself run anything.
    """

    def __init__(
        self,
        parent: Gtk.Window | None,
        *,
        surface: str,
        method: str,
        on_submit: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._on_submit = on_submit
        self.set_modal(True)
        if parent is not None:
            self.set_transient_for(parent)
        self.set_title("Administrator password")
        self.set_default_size(420, -1)
        self.add_css_class("linwallpaper")

        where = SURFACE_LABELS.get(surface, "a system surface")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        heading = Gtk.Label(xalign=0.0)
        heading.add_css_class("lw-card-title")
        heading.set_text(f"Apply the wallpaper to {where}")
        box.append(heading)

        via = "your desktop's polkit agent" if method == "pkexec" else "sudo"
        blurb = Gtk.Label(xalign=0.0)
        blurb.add_css_class("lw-sub")
        blurb.set_wrap(True)
        blurb.set_text(
            "This changes a system file and needs administrator rights "
            f"(via {via}). Enter your password to continue."
        )
        box.append(blurb)

        self._entry = Gtk.PasswordEntry()
        self._entry.set_show_peek_icon(True)
        self._entry.set_hexpand(True)
        # If the agent handles the prompt, the field is not needed.
        self._entry.set_sensitive(method == "sudo")
        if method == "pkexec":
            self._entry.set_placeholder_text("Handled by the polkit agent")
        self._entry.connect("activate", self._on_apply)
        box.append(self._entry)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        buttons.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("lw-ghost")
        cancel.connect("clicked", lambda *_: self.close())
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("lw-primary")
        apply_btn.connect("clicked", self._on_apply)
        buttons.append(cancel)
        buttons.append(apply_btn)
        box.append(buttons)

        self.set_content(box)
        self._entry.grab_focus()

    def _on_apply(self, *_a) -> None:
        password = self._entry.get_text()
        # Wipe the visible field immediately; the caller gets the value.
        self._entry.set_text("")
        self.close()
        self._on_submit(password)


def run_privileged(
    win,
    surface: str,
    image: str,
    fit: str,
    res: str = "1920x1080",
    on_success: Callable[[], None] | None = None,
) -> PasswordDialog:
    """Open the password dialog and, on confirm, run the helper as root.

    ``win`` is the :class:`AppWindow` (used for ``toast`` and as the modal
    parent). ``on_success`` — if given — is invoked on the GTK main thread only
    when the privileged apply succeeds (lets the page persist what it wrote).
    Returns the dialog so callers/tests can inspect it.
    """
    method = detect_auth_method()
    argv = build_command(method, _helper_argv(surface, image, fit, res))
    where = SURFACE_LABELS.get(surface, "the surface")

    def on_submit(password: str) -> None:
        win.toast(f"Applying to {where}…")

        def worker() -> None:
            ok, message = _run_privileged_blocking(method, argv, password)
            # Back to the GTK main thread: persist-on-success, then toast.
            if ok and on_success is not None:
                GLib.idle_add(on_success)
            GLib.idle_add(win.toast, message)

        threading.Thread(target=worker, daemon=True).start()

    parent = win if isinstance(win, Gtk.Window) else None
    dialog = PasswordDialog(
        parent,
        surface=surface,
        method=method,
        on_submit=on_submit,
    )
    dialog.present()
    return dialog
