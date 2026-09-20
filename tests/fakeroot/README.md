# Fake roots

Synthetic `/etc`, `/usr/share` and `/boot` trees that providers are pointed at instead of the real
system, so a provider can be tested — applied *and* rolled back — without that distribution being
installed and without root. **Tests never touch the real system.**

- `base/` — the empty skeleton (M0). Copied into a temp directory by the `fakeroot` fixture in
  `tests/conftest.py`, so tests can write into it freely.
- `<distro-shape>/` — Mint Cinnamon, Ubuntu GNOME, Debian Xfce, Kubuntu, MX: probe tests from M3,
  apply/revert golden tests from M4–M6. A `linwp doctor --json` dump from a real machine seeds a new shape.
