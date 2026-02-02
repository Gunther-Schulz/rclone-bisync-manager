# AUR / Arch package dependencies

Reference for PKGBUILD: use these Arch native packages instead of PyPI wheels so installs use repo builds (e.g. for Python 3.12/3.13 that Arch ships).

All package names were checked with `pacman -Ss` / Arch package database. Repo = **extra** unless noted.

## Runtime (from pyproject.toml)

| PyPI / project name | Arch package      | Repo  | Notes |
|---------------------|-------------------|-------|--------|
| croniter            | python-croniter-git | AUR   | Use AUR package `python-croniter-git` |
| pydantic            | python-pydantic  | extra | Pulls in python-pydantic-core |
| python_daemon       | python-daemon    | extra | |
| PyYAML              | python-yaml      | extra | Provides python-pyyaml |
| psutil              | python-psutil   | extra | |
| Pillow              | python-pillow   | extra | |
| PyGObject           | python-gobject  | extra | Not “pygobject” |
| CairoSVG            | python-cairosvg | extra | |

## Build (make deps for PKGBUILD)

| PyPI / usage      | Arch package        | Repo  |
|-------------------|---------------------|-------|
| setuptools, wheel | python-setuptools   | extra |
|                   | python-wheel        | extra |
| build             | python-build        | extra |
| installer         | python-installer    | extra |

## Tray (system packages)

The tray uses AppIndicator3 (SNI), GTK3 windows, and libnotify. **On KDE or minimal installs these are often not installed**; add them so the tray works.

| Purpose           | Arch package    | Repo  | Notes |
|-------------------|-----------------|-------|--------|
| System tray (SNI) | libappindicator | extra | AppIndicator3; works on GNOME and KDE |
| Status/config UI | gtk3            | extra | Status window, config editor, dialogs |
| Notifications     | libnotify       | extra | Works with GNOME/KDE notification daemon |

## Other

| Purpose        | Arch package | Repo  | Notes |
|----------------|--------------|-------|--------|
| Sync backend   | rclone       | extra | Required |
| CPU limiting  | cpulimit     | AUR   | Optional |

## Example PKGBUILD dependency arrays

```bash
depends=(
  'python'
  'python-croniter-git'
  'python-daemon'
  'python-psutil'
  'python-pydantic'
  'python-yaml'
  'rclone'
  'python-pillow'      # for tray icon
  'python-gobject'     # for tray (AppIndicator + GTK)
  'python-cairosvg'    # for tray icon
)
makedepends=(
  'python-build'
  'python-installer'
  'python-setuptools'
  'python-wheel'
)
optdepends=(
  'cpulimit: limit CPU usage of rclone processes'
  'libappindicator: system tray icon (needed on KDE/minimal)'
  'gtk3: status window and config editor (needed on KDE/minimal)'
  'libnotify: tray notifications (needed on KDE/minimal)'
)
```

Use `pacman -Ss <name>` to confirm package names on your mirror. Install croniter from AUR: `yay -S python-croniter-git` or `paru -S python-croniter-git`.

**Tray on KDE:** The tray uses AppIndicator (SNI) and GTK3. On KDE Plasma, `libappindicator` and `gtk3` are often not installed by default. Include the tray system packages in `optdepends` (or `depends` if you want the tray to work out of the box on KDE); then `pacman -S libappindicator gtk3 libnotify` (or install the metapackage that pulls them in) so the tray icon and windows work.
