from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Dict, Iterable, List, Optional

import numpy as np


class AssetKind(StrEnum):
    STRUCTURE = "Structure"
    PROP = "Prop"
    ITEM = "Item"
    CREATURE = "Creature"
    DEED = "Deed"
    LIGHT = "Light"
    OTHER = "Other"


@dataclass(frozen=True)
class AssetListItem:
    asset_id: int
    name: str
    kind: AssetKind


@dataclass(frozen=True)
class MeshPart:
    mesh_id: int
    texture_id: Optional[int]
    transform: np.ndarray  # 4x4
    source_render_id: int
    target_bone: Optional[str]


@dataclass(frozen=True)
class AssembledAsset:
    asset_id: int
    name: str
    kind: AssetKind
    render_ids: List[int]
    skeleton_id: Optional[int]
    parts: List[MeshPart]


# `arcane.enums.arc_object` type code -> browsable category.
TYPE_CODE_TO_KIND = {
    1: AssetKind.LIGHT,        # LIGHT
    2: AssetKind.STRUCTURE,    # DOOR
    3: AssetKind.PROP,         # STATIC
    4: AssetKind.STRUCTURE,    # STRUCTURE
    5: AssetKind.STRUCTURE,    # ASSETSTRUCTURE
    6: AssetKind.STRUCTURE,    # DUNGEONUNIT
    7: AssetKind.STRUCTURE,    # DUNGEONEXIT
    8: AssetKind.STRUCTURE,    # DUNGEONSTAIR
    9: AssetKind.ITEM,         # ITEM
    10: AssetKind.OTHER,       # TERRAIN
    11: AssetKind.CREATURE,    # PLAYER
    12: AssetKind.CREATURE,    # MOBILE
    13: AssetKind.CREATURE,    # RUNE
    14: AssetKind.ITEM,        # CONTAINER
    15: AssetKind.DEED,        # DEED
    16: AssetKind.ITEM,        # KEY
    17: AssetKind.STRUCTURE,   # ASSET (city asset template)
    19: AssetKind.OTHER,       # OBJECT
}


class AssetCatalog:
    """
    Catalog of assembled in-game assets built from COBJECTS + RENDER records.

    This intentionally hides low-level cache categories from the UI.
    """

    def __init__(self, asset_manager) -> None:
        self._asset_manager = asset_manager
        self._kind_index: Dict[AssetKind, List[int]] = {k: [] for k in AssetKind}
        self._name_cache: Dict[int, str] = {}
        self._kind_cache: Dict[int, AssetKind] = {}

        self._index_cobjects()

    def list_kinds(self) -> List[AssetKind]:
        return [k for k in AssetKind if self._kind_index.get(k)]

    def count_by_kind(self, kind: AssetKind) -> int:
        return len(self._kind_index.get(kind, []))

    def iter_asset_ids(self, kind: AssetKind) -> Iterable[int]:
        return iter(self._kind_index.get(kind, []))

    def search(self, *, kind: AssetKind, query: str, limit: int = 500) -> List[AssetListItem]:
        q = (query or "").strip().lower()
        out: List[AssetListItem] = []
        for asset_id in self._kind_index.get(kind, []):
            name = self._get_name(asset_id)
            if not q or q in name.lower() or q in str(asset_id):
                out.append(AssetListItem(asset_id=asset_id, name=name, kind=kind))
                if len(out) >= limit:
                    break
        return out

    def assemble(self, asset_id: int, pose=None) -> Optional[AssembledAsset]:
        """
        Build an asset's mesh parts in model space.

        The cache's rest pose is a zero pose — limbs fully extended, feet
        pointing at the floor — because in the client a character's stance comes
        from its animation. So creatures default to standing: their skeleton's
        calmest standing clip frame, via `AssetManager.stand_pose`. Rigs whose
        clips are all action keep the rest pose, as does everything that is not
        a creature.

        `pose` overrides that. A dict maps bone name -> local (x, y, z, w)
        quaternion, the form `AssetManager.load_motion_pose` returns; `False`
        forces the rest pose.
        """
        cobj = self._asset_manager.load_cobject(asset_id)
        if not cobj:
            return None

        render_ids, skeleton_id = self._resolve_render_ids(asset_id, cobj)

        parts: List[MeshPart] = []
        for rid in render_ids:
            parts.extend(self._flatten_render_to_parts(render_id=rid, parent_xform=np.identity(4, dtype=np.float32)))

        parts = self._drop_collision_hulls(parts)
        if skeleton_id is not None:
            if pose is None and self._get_kind(asset_id) is AssetKind.CREATURE:
                pose = self._asset_manager.stand_pose(skeleton_id)
            # False (rest pose was asked for) and {} (no clip stands this rig)
            # both mean the same thing downstream.
            parts = self._bind_parts_to_skeleton(parts, skeleton_id, pose or None)

        return AssembledAsset(
            asset_id=asset_id,
            name=self._get_name(asset_id),
            kind=self._get_kind(asset_id),
            render_ids=render_ids,
            skeleton_id=skeleton_id,
            parts=parts,
        )

    # Body parts a character has many interchangeable variants of; the client
    # picks one at creation time, so showing all of them stacks them up.
    _VARIANT_BONES = ("HAIR", "BEARD", "HELM")

    def _bind_parts_to_skeleton(self, parts: List[MeshPart], skeleton_id: int,
                                pose: Optional[Dict[str, tuple]] = None) -> List[MeshPart]:
        """
        Place body-part meshes on their skeleton joints.

        Character meshes are modelled about their own joint and carry a
        `target_bone`; without this every part sits at the origin in a heap.
        Attachment is rigid (one mesh per bone), not vertex skinning.

        Three quirks of the format are handled here:
        - Only one side of the body is stored. Bones flagged `flip` reuse the
          opposite side's mesh, mirrored across X onto their own joint.
        - Hair/beard/helm come as a set of alternatives, so only the first of
          each is kept.
        - The stored rest pose is a zero pose. `pose` lays a clip frame over it
          so the model stands; without one the limbs come out fully extended.
        """
        skeleton = self._asset_manager.load_skeleton(skeleton_id)
        if not skeleton or not getattr(skeleton, "bones", None):
            return parts

        joints = skeleton.pose(pose)
        if not joints:
            return parts

        flipped = {
            b.name.upper() for b in skeleton.bones
            if b.name and getattr(b, "flip", 0)
        }

        placed: List[MeshPart] = []
        seen_variants: set = set()
        by_bone: Dict[str, MeshPart] = {}

        for part in parts:
            bone = (part.target_bone or "").upper()
            if not bone:
                placed.append(part)
                continue

            variant = next((v for v in self._VARIANT_BONES if bone == v), None)
            if variant:
                if variant in seen_variants:
                    continue
                seen_variants.add(variant)

            joint = joints.get(bone)
            if joint is None:
                placed.append(part)
                continue

            placed.append(self._place_part(part, joint, bone))
            # Keep the unplaced part: a mirrored copy composes with its own joint.
            by_bone[bone] = part

        # Mirror the stored side onto the bones that only exist flipped.
        for bone in sorted(flipped):
            if bone in by_bone:
                continue
            counterpart = self._mirror_bone_name(bone)
            source = by_bone.get(counterpart) if counterpart else None
            joint = joints.get(bone)
            if source is None or joint is None:
                continue
            placed.append(self._place_part(source, joint, bone, mirror=True))

        return placed

    @staticmethod
    def _mirror_bone_name(bone: str) -> Optional[str]:
        if bone.startswith("L"):
            return "R" + bone[1:]
        if bone.startswith("R"):
            return "L" + bone[1:]
        return None

    @staticmethod
    def _place_part(part: MeshPart, joint, bone: str, mirror: bool = False) -> MeshPart:
        """
        Put a part on its joint: joint transform first, then the render's own.

        `joint` is the (rotation, position) pair `ArcSkeleton.pose` returns. A
        mirrored part reflects across X in mesh space *before* the joint applies,
        so it lands facing the right way on a joint that has its own rotation.
        """
        rotation, position = joint
        xform = np.identity(4, dtype=np.float32)
        xform[0, :3] = rotation[0:3]
        xform[1, :3] = rotation[3:6]
        xform[2, :3] = rotation[6:9]
        xform[0, 3], xform[1, 3], xform[2, 3] = position

        if mirror:
            reflect = np.identity(4, dtype=np.float32)
            reflect[0, 0] = -1.0
            xform = xform @ reflect

        return MeshPart(
            mesh_id=part.mesh_id,
            texture_id=part.texture_id,
            transform=xform @ part.transform,
            source_render_id=part.source_render_id,
            # Name the joint it actually sits on, not the side the mesh came from.
            target_bone=bone,
        )

    @staticmethod
    def _drop_collision_hulls(parts: List[MeshPart]) -> List[MeshPart]:
        """
        Discard untextured parts when the asset has textured geometry.

        Structure levels mix visible geometry with collision volumes — a box
        around the whole building, a flat footprint plane — and nothing in the
        render flags distinguishes them; only the absence of a texture set does.
        Left in, those hulls swallow the model. Assets that are untextured
        throughout keep every part rather than vanishing.
        """
        textured = [p for p in parts if p.texture_id is not None]
        return textured or parts

    def _resolve_render_ids(self, asset_id: int, cobj, _seen: Optional[set] = None) -> tuple:
        """
        Collect the render IDs that make up an asset, following COBJECT links.

        A city asset template carries no geometry itself: it lists the building
        COBJECT for each rank, and those hold the levels. Ranks usually share
        buildings, so IDs are deduplicated and recursion is depth-guarded.
        """
        seen = _seen if _seen is not None else set()
        if asset_id in seen:
            return [], None
        seen.add(asset_id)

        render_ids = list(getattr(cobj, "render_ids", []) or [])
        skeleton_id = getattr(cobj, "skeleton_id", None)

        for building_id in getattr(cobj, "building_ids", []) or []:
            building = self._asset_manager.load_cobject(building_id)
            if building is None:
                continue
            child_renders, child_skeleton = self._resolve_render_ids(building_id, building, seen)
            render_ids.extend(r for r in child_renders if r not in render_ids)
            skeleton_id = skeleton_id or child_skeleton

        # Only fall back to the distance proxy when nothing else resolved.
        if not render_ids:
            render_ids = list(getattr(cobj, "low_detail_render_ids", []) or [])

        return render_ids, skeleton_id

    # ---------------------------------------------------------------------
    # Indexing
    # ---------------------------------------------------------------------
    def _index_cobjects(self) -> None:
        # Reads only each record's type code and name, not its full body.
        for asset_id in self._asset_manager.list_assets("cobject"):
            self._read_summary(asset_id)
            kind = self._kind_cache.get(asset_id, AssetKind.OTHER)
            self._kind_index.setdefault(kind, []).append(asset_id)

        for k in self._kind_index:
            self._kind_index[k] = sorted(self._kind_index[k])

    def _read_summary(self, asset_id: int) -> None:
        """Populate the kind/name caches for one cobject."""
        summary = self._asset_manager.get_cobject_summary(asset_id)
        if summary is None:
            self._kind_cache[asset_id] = AssetKind.OTHER
            self._name_cache[asset_id] = f"Asset {asset_id}"
            return

        type_code, name = summary
        # A few records hold control bytes where a name should be; those would
        # otherwise leak into filenames and exported manifests.
        name = "".join(ch for ch in (name or "") if ch.isprintable()).strip()
        self._kind_cache[asset_id] = TYPE_CODE_TO_KIND.get(type_code, AssetKind.OTHER)
        self._name_cache[asset_id] = name or f"Asset {asset_id}"

    def _get_kind(self, asset_id: int) -> AssetKind:
        if asset_id not in self._kind_cache:
            self._read_summary(asset_id)
        return self._kind_cache[asset_id]

    def _get_name(self, asset_id: int) -> str:
        if asset_id not in self._name_cache:
            self._read_summary(asset_id)
        return self._name_cache[asset_id]

    # ---------------------------------------------------------------------
    # Assembly
    # ---------------------------------------------------------------------
    def _flatten_render_to_parts(self, *, render_id: int, parent_xform: np.ndarray) -> List[MeshPart]:
        # Some cobjects (city asset templates especially) reference IDs that are
        # not renders; skip them quietly rather than logging a miss per hop.
        if not self._asset_manager.has_asset("render", render_id):
            return []

        render = self._asset_manager.load_render(render_id)
        if not render:
            return []

        xform = parent_xform @ self._render_transform(render)
        target_bone = getattr(render, "render_target_bone", None) or None

        mesh_ids: List[int] = []
        try:
            mesh_set = render.render_template.template_mesh.mesh_set  # type: ignore[attr-defined]
            for m in mesh_set:
                mid = int(m.polymesh_id)
                if mid > 0:
                    mesh_ids.append(mid)
        except Exception:
            mesh_ids = []

        # A render carries one mesh with a stack of texture layers (base, detail,
        # normal, ...), so the first entry is the base map. Animated textures
        # name the field differently.
        texture_id: Optional[int] = None
        try:
            tex_set = render.render_texture_set  # type: ignore[attr-defined]
            if tex_set:
                data = tex_set[0].texture_data
                raw_id = getattr(data, "texture_id", None)
                if raw_id is None:
                    raw_id = getattr(data, "animated_texture_id", None)
                if raw_id:
                    texture_id = int(raw_id)
        except Exception:
            texture_id = None

        parts: List[MeshPart] = [
            MeshPart(
                mesh_id=mid,
                texture_id=texture_id,
                transform=xform,
                source_render_id=render_id,
                target_bone=target_bone,
            )
            for mid in mesh_ids
        ]

        # Recurse children renders if present
        child_ids: List[int] = []
        try:
            child_ids = [int(x) for x in getattr(render, "render_children", []) or []]
        except Exception:
            child_ids = []

        for cid in child_ids:
            parts.extend(self._flatten_render_to_parts(render_id=cid, parent_xform=xform))

        return parts

    @staticmethod
    def _render_transform(render) -> np.ndarray:
        m = np.identity(4, dtype=np.float32)

        # Scale
        try:
            sx, sy, sz = render.render_scale  # type: ignore[attr-defined]
            m = m @ np.array(
                [
                    [sx, 0.0, 0.0, 0.0],
                    [0.0, sy, 0.0, 0.0],
                    [0.0, 0.0, sz, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                dtype=np.float32,
            )
        except Exception:
            pass

        # Translation
        try:
            has_loc = bool(getattr(render, "render_has_loc", 0))
            if has_loc:
                tx, ty, tz = render.render_loc  # type: ignore[attr-defined]
                t = np.identity(4, dtype=np.float32)
                t[0, 3] = float(tx)
                t[1, 3] = float(ty)
                t[2, 3] = float(tz)
                m = m @ t
        except Exception:
            pass

        return m

