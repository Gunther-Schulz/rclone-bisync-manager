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
| pystray             | python-pystray  | extra | |
| PyGObject           | python-gobject  | extra | Not “pygobject” |
| CairoSVG            | python-cairosvg | extra | |

## Build (make deps for PKGBUILD)

| PyPI / usage      | Arch package        | Repo  |
|-------------------|---------------------|-------|
| setuptools, wheel | python-setuptools   | extra |
|                   | python-wheel        | extra |
| build             | python-build        | extra |
| installer         | python-installer    | extra |

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
  'python-pillow'      # for tray
  'python-pystray'     # for tray
  'python-gobject'     # for tray (AppIndicator)
  'python-cairosvg'    # for tray
)
makedepends=(
  'python-build'
  'python-installer'
  'python-setuptools'
  'python-wheel'
)
optdepends=(
  'cpulimit: limit CPU usage of rclone processes'
)
```

Use `pacman -Ss <name>` to confirm package names on your mirror. Install croniter from AUR: `yay -S python-croniter-git` or `paru -S python-croniter-git`.
