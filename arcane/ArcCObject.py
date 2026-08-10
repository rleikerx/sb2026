from __future__ import annotations

"""Arcane COBJECT parser.

The Shadowbane *cobjects.cache* entries categorise all in-game 3D assets.
Each record starts with a *flag* that maps to the legacy types discovered in
`objects.cpp`:

    0x03  Static props (pillars, rocks,…)
    0x04  Static structures (buildings)
    0x05  Interactive structures (doors, gates,…)
    0x09  Items / equipment
    0x0D  Creatures / NPCs (runes)
    0x0F  Deeds (land-claim parchments)
    0x13  Particle / environment stubs

The exporter’s JSON format is not standardised across dumps; keys differ by
client build.  The goal is *robust ID extraction*, not perfect fidelity—any
field we don’t understand is preserved in `extras` for future research.
"""

from collections import OrderedDict
from typing import Any, Dict, List, Tuple
import re

__all__ = ["ArcCObject"]


class ArcCObject:
    """High-level view of a COBJECT entry."""

    # High-detail render references. `obj_render_object_low_detail` is handled
    # separately: it is a distance proxy, not an additional piece of the model.
    _RENDER_KEYS = (
        "obj_render_object",
        "obj_render_object_high_detail",
        "obj_render_template_id",
        "render_template_id",
        "render_id",
    )
    _LOW_DETAIL_KEYS = (
        "obj_render_object_low_detail",
    )
    _SKELETON_KEYS = (
        "obj_skeleton",
        "obj_skeleton_id",
        "skeleton_id",
        # Creature runes
        "rune_skeleton",
    )
    _DECIMAL_ID = re.compile(r"^\d{4,8}$")

    # ------------------------------------------------------------------
    def __init__(self) -> None:  # noqa: D401
        self.flag: int | None = None
        self.name: str | None = None
        self.render_ids: List[int] = []
        self.low_detail_render_ids: List[int] = []
        self.skeleton_id: int | None = None
        self.inv_tex_id: int | None = None
        self.map_tex_id: int | None = None
        # Inventory/UI icon, and the class crest carried by character runes.
        self.icon_id: int | None = None
        self.class_icon_id: int | None = None
        # Structures reference a city asset template (a COBJECT, not a render);
        # that template in turn lists the building COBJECT for each rank.
        self.template_id: int | None = None
        self.building_ids: List[int] = []
        self.extras: Dict[str, Any] = {}

        self._raw: Dict[str, Any] | None = None

    # ------------------------------------------------------------------
    def load_json(self, data: Dict[str, Any]) -> None:  # noqa: D401
        self._raw = data

        self.flag = data.get("obj_type") or data.get("flag")
        self.name = data.get("obj_name") or data.get("name")

        # Skeleton
        for k in self._SKELETON_KEYS:
            if k in data and isinstance(data[k], int):
                self.skeleton_id = data[k]
                break

        # Render/template IDs
        ids: set[int] = set()
        for k in self._RENDER_KEYS:
            v = data.get(k)
            if isinstance(v, int):
                if v > 0:
                    ids.add(v)
            elif isinstance(v, list):
                ids.update(i for i in v if isinstance(i, int) and i > 0)
        # Fallback heuristic: any key containing "render" and ending with _id
        for k, v in data.items():
            if (
                "render" in k.lower()
                and k.lower().endswith("id")
                and isinstance(v, int)
            ):
                if v > 0:
                    ids.add(v)

        # Creature assembly: runes define per-body-part render IDs
        rune_body_parts = data.get("rune_body_parts")
        if isinstance(rune_body_parts, list):
            for part in rune_body_parts:
                if isinstance(part, dict):
                    rid = part.get("body_part_render")
                    if isinstance(rid, int) and rid > 0:
                        ids.add(rid)

        # Hair/beard render IDs (if present)
        for k in ("rune_hair", "rune_beard"):
            v = data.get(k)
            if isinstance(v, list):
                for rid in v:
                    if isinstance(rid, int) and rid > 0:
                        ids.add(rid)

        # Building geometry: a structure is built from levels (the exterior
        # shell plus each interior floor), and every `level_value` is a render.
        # Without these a building has only its low-detail proxy to show.
        structure_levels = data.get("structure_levels")
        if isinstance(structure_levels, list):
            for level in structure_levels:
                if isinstance(level, dict):
                    rid = level.get("level_value")
                    if isinstance(rid, int) and rid > 0:
                        ids.add(rid)

        self.render_ids = sorted(ids)

        # Low-detail proxies are only worth showing when nothing else resolved,
        # otherwise they draw on top of the real geometry.
        low_ids: set[int] = set()
        for k in self._LOW_DETAIL_KEYS:
            v = data.get(k)
            if isinstance(v, int) and v > 0:
                low_ids.add(v)
        self.low_detail_render_ids = sorted(low_ids - ids)

        # City asset template linkage
        template_id = data.get("asset_structure_template_id") or data.get("asset_template_id")
        if isinstance(template_id, int) and template_id > 0:
            self.template_id = template_id

        rank_info = data.get("template_rank_info")
        if isinstance(rank_info, list):
            buildings: set[int] = set()
            for rank in rank_info:
                if not isinstance(rank, dict):
                    continue
                for entry in rank.get("rank_building_id") or []:
                    # entry is [kind_flag, cobject_id]
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        bid = entry[1]
                        if isinstance(bid, int) and bid > 0:
                            buildings.add(bid)
            self.building_ids = sorted(buildings)

        # Textures
        self.inv_tex_id = data.get("inv_tex") or data.get("invTex") or data.get("inventory_texture_id")
        self.map_tex_id = data.get("map_tex") or data.get("mapTex") or data.get("minimap_texture_id")

        for attr, key in (("icon_id", "obj_icon"), ("class_icon_id", "rune_class_icon")):
            v = data.get(key)
            setattr(self, attr, v if isinstance(v, int) and v > 0 else None)

        # Preserve unknowns for debugging
        known_keys = {
            *self._RENDER_KEYS,
            *self._LOW_DETAIL_KEYS,
            *self._SKELETON_KEYS,
            "asset_structure_template_id",
            "asset_template_id",
            "structure_levels",
            "template_rank_info",
            "obj_icon",
            "rune_class_icon",
            "obj_type",
            "flag",
            "obj_name",
            "name",
            "inv_tex",
            "invTex",
            "inventory_texture_id",
            "map_tex",
            "mapTex",
            "minimap_texture_id",
        }
        self.extras = {k: v for k, v in data.items() if k not in known_keys}

    def save_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = OrderedDict()
        if self.flag is not None:
            out["flag"] = self.flag
        if self.name is not None:
            out["name"] = self.name
        out["render_ids"] = self.render_ids
        if self.low_detail_render_ids:
            out["low_detail_render_ids"] = self.low_detail_render_ids
        if self.template_id is not None:
            out["template_id"] = self.template_id
        if self.building_ids:
            out["building_ids"] = self.building_ids
        if self.skeleton_id is not None:
            out["skeleton_id"] = self.skeleton_id
        if self.icon_id is not None:
            out["icon_id"] = self.icon_id
        if self.class_icon_id is not None:
            out["class_icon_id"] = self.class_icon_id
        if self.inv_tex_id is not None:
            out["inv_tex_id"] = self.inv_tex_id
        if self.map_tex_id is not None:
            out["map_tex_id"] = self.map_tex_id
        if self.extras:
            out["extras"] = self.extras
        return out 