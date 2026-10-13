"""Resolve Vite-built assets for Django templates (see issue #15).

The manifest is read once per request from ``static/build``. When the manifest
is missing or empty and no dev server is configured, the tag renders nothing so
pages keep working without a built bundle.
"""

import json
import logging
from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

register = template.Library()

# ``build.manifest = true`` writes ``.vite/manifest.json``; older/unusual setups
# use ``manifest.json``. Accept either so the resolver is not brittle.
_MANIFEST_RELATIVE_PATHS = (
    Path("build") / ".vite" / "manifest.json",
    Path("build") / "manifest.json",
)


def _manifest_path():
    for static_dir in getattr(settings, "STATICFILES_DIRS", []) or []:
        base = Path(static_dir)
        for relative in _MANIFEST_RELATIVE_PATHS:
            candidate = base / relative
            if candidate.is_file():
                return candidate
    return None


def _load_manifest():
    path = _manifest_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Could not read Vite manifest at %s", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _find_entry(manifest, entry):
    """Match an entry by name, source path, manifest key, or basename."""
    if entry in manifest:
        return manifest[entry]
    wanted_basename = Path(entry).name
    for key, value in manifest.items():
        if not isinstance(value, dict):
            continue
        if value.get("name") == entry or value.get("src") == entry:
            return value
        if key == entry or Path(key).name == wanted_basename:
            return value
        if Path(key).name == entry:
            return value
    return None


def _dev_tags(dev_server, source):
    base = dev_server.rstrip("/")
    module = source.lstrip("/")
    return [
        f'<script type="module" src="{base}/@vite/client"></script>',
        f'<script type="module" src="{base}/{module}"></script>',
    ]


def _build_tags(entry):
    tags = []
    for css in entry.get("css", []) or []:
        tags.append(f'<link rel="stylesheet" href="{static(css)}">')
    file = entry.get("file")
    if file and file.endswith(".css"):
        tags.append(f'<link rel="stylesheet" href="{static(file)}">')
    elif file:
        tags.append(f'<script type="module" src="{static(file)}"></script>')
    return tags


@register.simple_tag
def vite_asset(entry="main"):
    """Render the ``<link>``/``<script>`` tags for a Vite entry.

    ``entry`` may be the entry name (``"main"``) or its source path
    (``"frontend/main.js"``). Later tasks add their own entries without
    touching this tag.
    """
    dev_server = getattr(settings, "VITE_DEV_SERVER_URL", "") or ""
    if dev_server:
        source = entry if Path(entry).suffix else f"frontend/{entry}.js"
        return mark_safe("\n    ".join(_dev_tags(dev_server, source)))

    manifest = _load_manifest()
    if not manifest:
        return ""
    resolved = _find_entry(manifest, entry)
    if not resolved:
        return ""
    tags = _build_tags(resolved)
    if not tags:
        return ""
    return mark_safe("\n    ".join(tags))
