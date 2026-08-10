"""
Asset Manager - Central registry for loading and caching Shadowbane assets.

Assets are read straight out of the `*.cache` archives in `arcane_dump/`; there
is no extraction step. Each archive's index is parsed once at startup and
individual records are decompressed on demand (see `assets.cache_archive`).
"""

import math
import struct
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from PIL import Image, ImageOps

# What counts as "standing" when picking a creature's default pose. Substrings,
# because rigs name the pair L/R (LFEMUR, RFOOT). The tilts are generous enough
# for a golem's braced knees and tight enough to reject a lunge: measured across
# the sampled rigs, genuine stands sit at 6-27 degrees of leg tilt and the
# action frames that fool a legs-only test at 37-46.
STAND_LEG_BONES = ('FEMUR', 'TIBIA')
STAND_FOOT_BONES = ('FOOT',)
STAND_MAX_LEG_TILT = 30.0    # degrees off vertical
STAND_MAX_FOOT_TILT = 10.0   # degrees off horizontal

# An ogre, a troll, a wight: a biped that never straightens its legs, so every
# frame it has is past the 30 degrees a walking stance is judged by. Widening
# that threshold instead was tried and re-admits sprawl, because leg tilt alone
# cannot tell a crouch from a body lying down with its knees up. So this is a
# separate rung carrying three further conditions — feet still flat, body still
# taller than it is wide, feet still the lowest thing on it — and only what the
# upright gate has already rejected reaches it.
#
# Measured over the rigs that had no pose at all: their best flat-footed upright
# frame sits at 25-51 degrees, and the next rig up needs 75. Anything from 55 to
# 65 selects exactly the same eight skeletons, so this sits in a gap rather than
# on a cliff edge.
STAND_MAX_HUNCH_TILT = 55.0

# Rigs the upright test cannot describe — snakes, drakes, quadrupeds — are judged
# on the shape the whole skeleton makes instead. Their rest pose stacks every
# bone up one axis, so a viper 22 units long reads as a 33-unit pole; what marks
# a real pose is that the body lies within its own footprint rather than above
# it, and that whatever the creature walks on ends up underneath.
STAND_GROUND_BONES = ('FOOT', 'TOE', 'CLAW', 'PAW', 'HOOF')
STAND_SPINE_BONES = ('BACK', 'NECK', 'TAIL', 'SPINE')
# A settled creature does not hold its forelimbs up. Measured on the chosen
# frames: poses that read correctly sit at -0.35 to +0.28, the ones that read as
# a shrug or a sprawl at +0.44 to +0.83.
STAND_ARM_BONES = ('HUMERUS', 'RADIUS')
STAND_MAX_ARM_RISE = 0.35      # sine of how far a forelimb may rise above horizontal
# Feet apart, as a fraction of body height: what separates a stance from a
# stride. Both pass every gate about legs and feet — a walk frame has both soles
# flat on the ground and both legs under the body — so without this the calmest
# frame is regularly somebody caught mid-step. Measured on the frames these
# rules chose: the ones that read as standing sit at 0.09-0.33 and the ones that
# read as walking at 0.46-0.52.
STAND_MAX_FOOT_GAP = 0.35
# A standing biped does not hold a forelimb above horizontal — it lets the arm
# hang. `STAND_MAX_ARM_RISE` is deliberately not reused here: that number was
# measured on quadruped forelimbs, where +0.35 is a settled dog, and on two legs
# the same value is a figure reaching out in front of itself. Measured on the
# frames these rules chose: the ones that read as standing sit at -0.82 to -0.06
# and the ones that read as reaching or swinging at +0.35 to +0.58.
STAND_MAX_BIPED_ARM_RISE = 0.0
STAND_MAX_GROUND_LIFT = 0.25   # fraction of body height the feet may sit above the lowest point
# A standing figure holds its spine near vertical.
#
# Nothing else here asks about the body at all — every gate above is about legs,
# feet or arms — so a frame can put both soles flat, both legs under the body and
# both arms down while the torso is rolled onto one shoulder, and pass all of
# them. Skeleton 117 (Nelchael) was doing exactly that: its chosen frame stands
# on legs tilted 28.6 degrees with the soles 3.2 degrees off flat and the feet
# 0.245 body-heights apart — inside every bound on this page — with the spine
# **39.4 degrees off vertical**, rolled sideways rather than bowed forward. Drawn,
# it is a figure collapsing onto its own shoulder. Measured on the exported
# vertices rather than the bones, its head sits 0.834 units to one side of its
# feet and its chest mesh leans 40.8 degrees, against 11.7 for the same mesh in
# the rest pose.
#
# The bound sits in a gap 34 degrees wide: anything from 6 to 39 picks the same
# frame on the one rig that reaches this rung and changes nothing anywhere else.
# 30 is chosen inside it because it is also above every torso lean this ladder
# already accepts on a two-legged rig (worst 26.8 degrees, skeletons 98 and 131)
# and below Nelchael's 39.4 — and because it is the bound the legs are already
# held to, so the rule reads "a standing figure's spine is as near vertical as
# its legs are". Stated as its own constant and not as a reference to
# STAND_MAX_LEG_TILT: they answer different questions and only coincide today.
#
# The two names are matched as substrings like every other group here, which
# also picks up the numbered spines (UPPERBACK2, LOWERBACK1). A bare 'BACK'
# would have been the obvious spelling and is a trap: 68 skeletons in this cache
# carry BACKSHEATHSPACER, a sword-mount pointing back and down at 73 degrees,
# which would fail this test on every frame of every clip.
STAND_TORSO_BONES = ('UPPERBACK', 'LOWERBACK')
STAND_MAX_TORSO_LEAN = 30.0    # degrees off vertical, worst of the spine bones
STAND_FRAME_SAMPLES = 6        # frames probed per clip on the non-bipedal path
# Legs-to-spine above this reads as a biped. Measured: bipeds 1.34-1.71,
# quadrupeds and serpents 0.00-0.34.
STAND_BIPED_LEG_RATIO = 1.0

# ---------------------------------------------------------------------------
# Authored wing fold
#
# THIS IS THE ONE PLACE THIS EXPORTER INVENTS SOURCE DATA. Everything else here
# selects a frame the cache already holds; the rotations below are written by
# us, on the project owner's explicit decision, and a reader looking at a
# Griffon later must be able to tell which part of its pose came from the client
# and which did not. `stand_layer` reports `+wingfold` for exactly these rigs.
#
# Why it is needed. These rigs export with the wings splayed, and no frame
# selection can fix it: measured over all 185 frames of all 7 of the Griffon's
# clips, every one of the 6 ground clips holds the wings at 1.07-1.10 body
# heights of lateral reach in its calmest frame, and the only folded-wing frames
# belong to the flight clip, where they are a dive and a landing with the head
# near the ground -- correctly rejected by the grounded stance test. Grafting the
# wing rotations out of one frame onto the body of another was measured too and
# is not a fix: the Griffon's best graft still reads 0.553, and drawn, it is a
# wing held up rather than folded.
#
# What a folded wing is here: every wing bone laid along one direction. That is
# what the source's own closed-wing frames do -- the Griffon's clips rotate
# WING03/04/05 about X until all three point the same way -- so the shape is the
# cache's; only the direction is ours.
#
# The direction is stated in MODEL space, not in the torso's frame, and that is
# the whole of why one constant serves three rigs. A folded wing lies back along
# the ground the creature stands on, and these bodies stand very differently: the
# Griffon's spine is horizontal and the Aracoix's is vertical, so "along the
# spine" means level for one and straight down through the floor for the other.
# Measured in the torso's frame the two want 180 and 120 degrees and no single
# value works; measured in model space they are the same answer. It rests on the
# rig facing +Z, which is this format's convention (see `tools/pose_render.py`)
# and which was checked on all four rigs in scope: the torso's yaw in the chosen
# frame is 0.6 degrees or less.
#
# The pitch was picked by rendering, not by scoring. Measured, in body heights,
# for how far the wing tips end up below the lowest part of the body:
#
#            pitch      0      10      20      30
#   Griffon (70)    +0.884  +0.333  -0.203  -0.705
#   Aracoix (18)    +0.889  +0.665  +0.447  +0.243
#
# so the Griffon puts its wings through the ground past ~15 degrees. At 0 the
# mesh still clears the crown of the back by so little that the wingtips read as
# two spikes above the head, which the bone-tip figures do not show and a
# picture does. 10 is the value where neither happens on any of the three.
WING_FOLD_SKELETONS = (18, 20, 70, 117)   # Aracoix, Aracoix, Hunting Griffon, Nelchael
# A wing is the bone subtree hanging from one of these. Named rather than matched
# on "WING", because 15 skeletons in this cache carry wing bones and only these
# four are in scope. Nelchael's wings are its second pair of arms, and the source
# spells the two sides differently -- LSHOULDERJB against RSHOULDERJ_B.
WING_ROOT_BONES = ('LWINGJOINT', 'RWINGJOINT', 'LSHOULDERJB', 'RSHOULDERJ_B')
WING_FOLD_PITCH_DEG = 10.0     # below horizontal, sweeping backward (-Z)

# Import arcane asset classes
import sys
from pathlib import Path as PathLib

# Add parent directory to path for arcane imports
parent_dir = PathLib(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

try:
    from arcane.ArcMesh import ArcMesh
    from arcane.ArcImage import ArcTexture
    from arcane.ArcSkeleton import ArcSkeleton, IDENTITY_3X3, _mat_mul, _quat_to_mat
    from arcane.ArcMotion import ArcMotion
    from arcane.ArcRender import ArcRender
    from arcane.ArcCObject import ArcCObject
    from arcane.util import ResStream
    from arcane.objects import (
        ArcAssetStructureObject,
        ArcCharacter,
        ArcCityAssetTemplate,
        ArcContainerObject,
        ArcDeed,
        ArcDoorObject,
        ArcDungeonExitObject,
        ArcDungeonStairObject,
        ArcDungeonUnitObject,
        ArcItem,
        ArcKey,
        ArcObj,
        ArcRune,
        ArcStaticObject,
        ArcStructureObject,
    )
except ImportError as e:
    raise ImportError(
        f"Failed to import arcane package. Make sure the 'arcane' package is available in the parent directory ({parent_dir}). "
        f"Original error: {e}"
    )

from assets.cache_archive import CacheArchive


# ---------------------------------------------------------------------------
# Rotation helpers for the authored wing fold. The matrix side is borrowed from
# `ArcSkeleton` rather than restated, so the fold composes rotations exactly the
# way `ArcSkeleton.pose` resolves them; only the two directions that module has
# no use for live here.
# ---------------------------------------------------------------------------
def _unit(v):
    """Normalise a direction, or None if it has no length."""
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-9 else None


def _transpose(m):
    """A rotation matrix's inverse."""
    return (m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8])


def _quat_from_to(a, b):
    """
    The shortest rotation taking unit vector `a` onto unit vector `b`.

    Shortest, and therefore mirror-safe without a left/right branch: reflecting
    both arguments across X reflects the answer, so a wing bone and its opposite
    number get quaternions that are each other's mirror by construction. That is
    the whole of why nothing here reads a bone name for its side.
    """
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    if dot > 1.0 - 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    if dot < -1.0 + 1e-9:
        # Antipodal: every perpendicular axis is a half turn onto `b`, so state
        # one instead of letting a zero cross product choose. X is always
        # perpendicular here because the fold direction has no lateral part, and
        # a half turn about X is its own mirror.
        return (1.0, 0.0, 0.0, 0.0)
    cross = (a[1] * b[2] - a[2] * b[1],
             a[2] * b[0] - a[0] * b[2],
             a[0] * b[1] - a[1] * b[0])
    q = (cross[0], cross[1], cross[2], 1.0 + dot)
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def _mat_to_quat(m):
    """Row-major 3x3 -> (x, y, z, w), inverse of `ArcSkeleton._quat_to_mat`."""
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = m
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


# COBJECT records are prefixed with a magic and an `arcane.enums.arc_object`
# type code, then the body of the matching ArcObj subclass.
COBJECT_MAGIC = b"TNLC"
COBJECT_HEADER_SIZE = 8

# Object type code -> parser. Confirmed against CObjects.cache: every record of
# each present type parses and consumes its body exactly.
COBJECT_TYPE_PARSERS = {
    1: ArcObj,                      # LIGHT
    2: ArcDoorObject,               # DOOR
    3: ArcStaticObject,             # STATIC
    4: ArcStructureObject,          # STRUCTURE
    5: ArcAssetStructureObject,     # ASSETSTRUCTURE
    6: ArcDungeonUnitObject,        # DUNGEONUNIT
    7: ArcDungeonExitObject,        # DUNGEONEXIT
    8: ArcDungeonStairObject,       # DUNGEONSTAIR
    9: ArcItem,                     # ITEM
    10: ArcObj,                     # TERRAIN
    11: ArcCharacter,               # PLAYER
    12: ArcCharacter,               # MOBILE
    13: ArcRune,                    # RUNE
    14: ArcContainerObject,         # CONTAINER
    15: ArcDeed,                    # DEED
    16: ArcKey,                     # KEY
    17: ArcCityAssetTemplate,       # ASSET
    19: ArcObj,                     # OBJECT
}


class AssetManager:
    """
    Manages loading and caching of game assets from the arcane_dump/ cache archives.
    """

    # asset type -> the cache file stems that can back it, in preference order
    CACHE_STEMS = {
        'mesh': ('mesh',),
        'texture': ('textures', 'texture'),
        'skeleton': ('skeleton',),
        'motion': ('motion',),
        'render': ('render',),
        'cobject': ('cobjects', 'cobject'),
    }

    def __init__(self, arcane_dump_path: str):
        """
        Initialize asset manager.

        Args:
            arcane_dump_path: Path to arcane_dump/ directory
        """
        self.arcane_dump_path = Path(arcane_dump_path)

        # asset type -> CacheArchive
        self.archives: Dict[str, CacheArchive] = {}
        self._open_archives()

        # Asset caches
        self.meshes: Dict[int, ArcMesh] = {}
        self.textures: Dict[int, ArcTexture] = {}
        self.skeletons: Dict[int, ArcSkeleton] = {}
        self.motions: Dict[int, ArcMotion] = {}
        self.renders: Dict[int, ArcRender] = {}
        self.cobjects: Dict[int, ArcCObject] = {}

        # Image cache for texture records
        self.texture_images: Dict[int, Image.Image] = {}

        # asset_id -> (type_code, name), populated lazily
        self._cobject_summaries: Dict[int, Tuple[int, str]] = {}

        # skeleton_id -> standing rotations, populated lazily (see stand_pose)
        self._stand_poses: Dict[int, Dict[str, tuple]] = {}
        # skeleton_id -> which rung of stand_pose answered, for reporting
        self._stand_layers: Dict[int, str] = {}

    # ------------------------------------------------------------------
    # Archive discovery
    # ------------------------------------------------------------------
    def _open_archives(self) -> None:
        """
        Locate and index every required cache archive.

        Fails fast with a specific message so a wrong path surfaces as an error
        rather than a silently empty UI.
        """
        if not self.arcane_dump_path.exists():
            raise FileNotFoundError(f"arcane_dump not found|path={self.arcane_dump_path}")

        # Cache layouts vary (flat, or one folder per category), so match on stem.
        found: Dict[str, Path] = {}
        for path in self.arcane_dump_path.rglob("*.cache"):
            found.setdefault(path.stem.lower(), path)

        missing: List[str] = []
        for asset_type, stems in self.CACHE_STEMS.items():
            path = next((found[s] for s in stems if s in found), None)
            if path is None:
                missing.append(f"{asset_type}({'|'.join(stems)}.cache)")
                continue
            self.archives[asset_type] = CacheArchive(path)

        if missing:
            raise FileNotFoundError(
                f"arcane_dump missing caches|path={self.arcane_dump_path}|missing={','.join(missing)}"
            )

    def has_asset(self, asset_type: str, asset_id: int) -> bool:
        """
        Check whether an ID is present, without reading or reporting a miss.

        Asset graphs reference IDs that legitimately live in caches this dump
        does not ship, so callers walking those references use this instead of
        provoking a "missing" diagnostic per hop.
        """
        archive = self.archives.get(asset_type)
        return archive is not None and asset_id in archive

    def get_source_path(self, asset_type: str, asset_id: int) -> Optional[str]:
        """
        Return a human-readable location for an asset ID (`<cache>#<id>`).

        Useful for debugging and for higher-level catalog/index layers.
        """
        if not self.has_asset(asset_type, asset_id):
            return None
        return f"{self.archives[asset_type].path.name}#{asset_id}"

    def _load_record(self, asset_type: str, asset_id: int, cls, label: str):
        """Read one record and run its binary parser."""
        archive = self.archives.get(asset_type)
        if archive is None:
            return None

        stream = archive.stream(asset_id)
        if stream is None:
            print(f"{label} missing|id={asset_id}")
            return None

        try:
            obj = cls()
            obj.load_binary(stream)
            return obj
        except Exception as e:
            print(f"Error loading {label.lower()} {asset_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Typed loaders
    # ------------------------------------------------------------------
    def load_mesh(self, asset_id: int) -> Optional[ArcMesh]:
        """
        Load mesh from the mesh cache.

        Args:
            asset_id: Mesh ID

        Returns:
            ArcMesh object or None if not found
        """
        if asset_id in self.meshes:
            return self.meshes[asset_id]

        mesh = self._load_record('mesh', asset_id, ArcMesh, "Mesh")
        if mesh is not None:
            self.meshes[asset_id] = mesh
        return mesh

    def load_texture(self, asset_id: int) -> Optional[ArcTexture]:
        """
        Load texture metadata and pixel data.

        Args:
            asset_id: Texture ID

        Returns:
            ArcTexture object or None if not found
        """
        if asset_id in self.textures:
            return self.textures[asset_id]

        texture = self._load_record('texture', asset_id, ArcTexture, "Texture")
        if texture is not None:
            self.textures[asset_id] = texture
        return texture

    def load_texture_image(self, asset_id: int) -> Optional[Image.Image]:
        """
        Load a texture record as a PIL image.

        Note: the Shadowbane mirror/rotate transform is *not* applied here;
        TextureManager does that on upload.

        Args:
            asset_id: Texture ID

        Returns:
            PIL Image object or None if not found
        """
        if asset_id in self.texture_images:
            return self.texture_images[asset_id]

        texture = self.load_texture(asset_id)
        if texture is None:
            return None

        try:
            img = self._texture_to_image(texture)
        except Exception as e:
            print(f"Texture image decode error|id={asset_id}|err={e}")
            return None

        if img is None:
            return None

        self.texture_images[asset_id] = img
        return img

    @staticmethod
    def _texture_to_image(texture: ArcTexture) -> Optional[Image.Image]:
        """Rebuild a PIL image from the raw pixel buffer in a texture record."""
        key = (texture.image_color_depth, texture.image_alpha, texture.image_type)
        mode = ArcTexture.VALUE_TO_MODE.get(key)
        if mode is None:
            print(
                f"Texture mode unknown|depth={texture.image_color_depth}"
                f"|alpha={texture.image_alpha}|type={texture.image_type}"
            )
            return None

        size = (texture.image_width, texture.image_height)
        expected = texture.image_width * texture.image_height * texture.image_color_depth
        if len(texture.image_data) < expected:
            print(f"Texture data short|have={len(texture.image_data)}|want={expected}")
            return None

        if mode == 'P':
            # Palette records live in Palette.cache, which the dump does not
            # ship; render the indices as greyscale rather than dropping the
            # texture entirely.
            return Image.frombytes('L', size, texture.image_data[:expected])

        return Image.frombytes(mode, size, texture.image_data[:expected])

    def save_texture_image(self, asset_id: int, dest_path: str) -> Optional[str]:
        """
        Write a texture record out as a standalone image file.

        Textures live inside Textures.cache, so exporters that need a real file
        on disk (OBJ/MTL, glTF) materialise one here. The Shadowbane mirror +
        180° rotate is applied so the result matches the viewport.

        Args:
            asset_id: Texture ID
            dest_path: Where to write the image

        Returns:
            The written path, or None on failure
        """
        img = self.load_texture_image(asset_id)
        if img is None:
            return None

        img = ImageOps.mirror(img.rotate(180))
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        try:
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest)
        except Exception as e:
            print(f"Texture export failed|id={asset_id}|dest={dest_path}|err={e}")
            return None
        return str(dest)

    def load_skeleton(self, asset_id: int) -> Optional[ArcSkeleton]:
        """
        Load skeleton from the skeleton cache.

        Args:
            asset_id: Skeleton ID

        Returns:
            ArcSkeleton object or None if not found
        """
        if asset_id in self.skeletons:
            return self.skeletons[asset_id]

        skeleton = self._load_record('skeleton', asset_id, ArcSkeleton, "Skeleton")
        if skeleton is not None:
            self.skeletons[asset_id] = skeleton
        return skeleton

    def load_motion(self, asset_id: int) -> Optional[ArcMotion]:
        """
        Load motion/animation from the motion cache.

        Args:
            asset_id: Motion ID

        Returns:
            ArcMotion object or None if not found
        """
        if asset_id in self.motions:
            return self.motions[asset_id]

        motion = self._load_record('motion', asset_id, ArcMotion, "Motion")
        if motion is not None:
            self.motions[asset_id] = motion
        return motion

    def load_motion_pose(self, asset_id: int, frame: int = 0) -> Dict[str, tuple]:
        """
        One frame of a clip as bone name -> local (x, y, z, w) quaternion.

        Feeds `ArcSkeleton.pose`. The cache's rest pose is a zero pose, so a
        character only stands once a clip frame is laid over it. Clips animate a
        subset of the skeleton — the bones absent here stay at rest.

        Returns an empty map for metadata-only clips, which carry no frames.
        """
        motion = self.load_motion(asset_id)
        frames = getattr(motion, 'frames', None) if motion else None
        if not frames:
            return {}

        out: Dict[str, tuple] = {}
        for name, track in (frames.get('bones') or {}).items():
            rotations = track.get('rot') or []
            if rotations:
                out[name.upper()] = tuple(rotations[min(frame, len(rotations) - 1)])
        return out

    def stand_pose(self, skeleton_id: int) -> Dict[str, tuple]:
        """
        A clip frame that stands this skeleton up, or {} if none of its clips does.

        The rest pose is already most of a standing figure: every limb hangs
        straight down, which is where a still character's arms belong. Only the
        feet are wrong, pointing at the floor. So a frame qualifies on geometry
        — legs near vertical, feet near flat — and among those the one that
        disturbs the rest pose least wins. Choosing on footing alone lets
        through clips that stand perfectly well with their arms in the air.

        Three body plans, tried in order and never in parallel: **upright** for
        anything that can straighten its legs, **hunched** for a biped that
        cannot, **grounded** for everything that is not standing on two legs at
        all. Each is a fallback for the one before it, so widening the question
        can never cost a rig the pose it already had.

        Returning {} is the honest answer for the rigs whose clips are all
        action: better the rest pose than a lunge frozen mid-swing.

        Cached per skeleton; judging one costs a parse of each of its clips.
        """
        if skeleton_id in self._stand_poses:
            return self._stand_poses[skeleton_id]

        skeleton = self.load_skeleton(skeleton_id)
        # Upright first, so a rig that reads as bipedal is never judged on the
        # looser shape test. Only what that rejects falls through.
        #
        # Sampled at the same rate as every other rung. It used to probe frame 0
        # alone, which judged bipeds on a sixth of the evidence the other paths
        # get: two rigs had frames passing this very gate, untouched, and were
        # sitting at rest because nobody had looked past the first frame of their
        # clips. A clip does not put its calmest frame first.
        layer = 'upright'
        best, rung = self._best_frame(skeleton,
                                      self._stance_ladder(self._stands_upright))
        if not best:
            if self._is_bipedal(skeleton):
                # A biped that cannot straighten its legs. Tried after the
                # upright gate and never instead of it, so a rig that already
                # stands keeps the stance it had.
                layer = 'hunched'
                best, rung = self._best_frame(
                    skeleton, self._stance_ladder(self._stands_hunched))
            else:
                # The shape test asks the body to be no taller than it is wide,
                # which is true of a hound and false of anything standing on two
                # legs — run it on a biped and the only frames that pass are the
                # sprawled ones.
                #
                # Ask for settled forelimbs first and drop the requirement only
                # if the rig has no such frame, so wanting better arms can never
                # cost a rig the pose it already had.
                # Not a ladder, so it has no rung tag of its own; stated rather
                # than inherited from the upright attempt above.
                rung = ''
                layer = 'grounded+limbs'
                best = self._calmest_frame(skeleton, self._rests_with_limbs_down,
                                           samples=STAND_FRAME_SAMPLES)
                if not best:
                    layer = 'grounded'
                    best = self._calmest_frame(skeleton, self._rests_on_ground,
                                               samples=STAND_FRAME_SAMPLES)

        # The layer is decided before the wings are touched, because it names
        # which rung stood the *body* up and the fold answers a different
        # question. It gains a suffix so that every picture and every report
        # says out loud which rigs carry rotations this exporter wrote.
        layer = (layer + rung) if best else 'rest'
        best, folded = self._fold_wings(skeleton_id, skeleton, best)

        self._stand_poses[skeleton_id] = best
        self._stand_layers[skeleton_id] = layer + ('+wingfold' if folded else '')
        return best

    def wing_fold_pose(self, skeleton_id: int) -> Dict[str, tuple]:
        """
        Just the authored wing fold, over the cache's rest pose — nothing else.

        For a consumer that re-poses the body itself and only needs the wings not
        to be splayed. Aegisfall is that consumer: it bakes its own rest-relative
        transforms and stretches limbs onto its own rig, so a baked stance breaks
        it (see `dev_log/081026.md`) — but the wings are the one thing no frame in
        this cache supplies, which is why `_fold_wings` authors them at all.

        `_fold_wings` composes against whatever base it is handed, so handing it an
        empty one leaves every non-wing bone at rest and turns only the wing
        subtree. Rigs outside `WING_FOLD_SKELETONS` get an empty dict, which
        `assemble` reads as the rest pose.
        """
        skeleton = self.load_skeleton(skeleton_id)
        if skeleton is None:
            return {}
        folded, did = self._fold_wings(skeleton_id, skeleton, {})
        return folded if did else {}

    def _fold_wings(self, skeleton_id, skeleton, rotations):
        """
        Lay a winged rig's wings back along the ground, and say whether it did.

        **Authored, not selected.** Every other rotation this class returns is a
        frame out of a motion clip; these are written here. See the block above
        `WING_FOLD_SKELETONS` for why no frame can supply them, and for how the
        one constant was arrived at.

        The rule is one sentence: *every bone in the wing points backward and
        `WING_FOLD_PITCH_DEG` below horizontal*. The root joints are exempt —
        those are the shoulder the wing hangs from, and turning one moves the
        wing's attachment rather than the wing.

        Nothing outside the wing subtrees is touched, and the rotations that
        remain are the chosen frame's, so a folded Griffon still stands on the
        legs the stance ladder picked for it.
        """
        if skeleton is None or skeleton_id not in WING_FOLD_SKELETONS:
            return rotations, False

        bones = getattr(skeleton, 'bones', None) or []
        names = [(b.name or '').upper() for b in bones]
        roots = {i for i, name in enumerate(names) if name in WING_ROOT_BONES}
        if not roots:
            return rotations, False

        wing = set()
        for i in range(len(bones)):
            j, guard = i, 0
            while j >= 0 and guard <= len(bones):
                if j in roots:
                    wing.add(i)
                    break
                j = bones[j].parent_index
                guard += 1

        pitch = math.radians(WING_FOLD_PITCH_DEG)
        target = (0.0, -math.sin(pitch), -math.cos(pitch))
        # Accumulated rotations under the *chosen* frame, so a wing hanging off a
        # torso the clip has turned folds along the ground rather than along the
        # torso. Asked of `ArcSkeleton.pose` instead of walked again here: two
        # accumulations of one hierarchy would eventually disagree.
        base = skeleton.pose(rotations)
        out = dict(rotations)
        accumulated = {}
        folded = 0

        for i, bone in enumerate(bones):
            if i not in wing:
                continue
            parent = bone.parent_index
            parent_rot = accumulated.get(parent)
            if parent_rot is None:
                entry = base.get(names[parent]) if 0 <= parent < len(names) else None
                parent_rot = entry[0] if entry else IDENTITY_3X3

            direction = _unit(bone.direction) if bone.length > 1e-6 else None
            if i in roots or direction is None or not names[i]:
                # Not a bone the fold turns. Carry the frame's own rotation
                # through anyway, so anything hanging below it still resolves
                # against what it is really attached to.
                local = out.get(names[i]) if names[i] else None
                accumulated[i] = (_mat_mul(parent_rot, _quat_to_mat(local))
                                  if local else parent_rot)
                continue

            world = _quat_to_mat(_quat_from_to(direction, target))
            out[names[i]] = _mat_to_quat(_mat_mul(_transpose(parent_rot), world))
            accumulated[i] = world
            folded += 1

        return out, folded > 0

    def stand_layer(self, skeleton_id: int) -> str:
        """
        Which rung of `stand_pose` answered for this rig: upright, hunched,
        grounded+limbs, grounded, or rest, with up to two suffixes.

        `+torso` means the stance was settled by the spine rung rather than by
        the arm and stride preferences above it — still a frame out of a clip,
        chosen by a question the ladder did not used to ask. One rig in this
        cache reaches it (117, Nelchael).

        `+wingfold` means something different in kind and the distinction is the
        whole point of printing either: those wings carry rotations this
        exporter *authored* rather than read out of a clip. A Griffon is the
        only sort of asset here whose pose is not wholly the cache's, and every
        picture and report that prints a layer says so.

        Reported by the code that made the choice rather than reconstructed by
        the caller. A reporting tool that re-ran the gates itself would be a
        second answer to the same question, and the two would drift the first
        time a rung moved.
        """
        if skeleton_id not in self._stand_layers:
            self.stand_pose(skeleton_id)
        return self._stand_layers.get(skeleton_id, 'rest')

    def _best_frame(self, skeleton, ladder) -> Tuple[Dict[str, tuple], str]:
        """
        The calmest frame the first satisfiable rung of `ladder` accepts, and
        that rung's tag.

        The tag is reported rather than re-derived for `stand_layer`'s stated
        reason: a caller that worked out which rung must have answered would be
        a second answer to a question this loop has already answered, and the
        two would drift the first time a rung moved.
        """
        for tag, accepts in ladder:
            best = self._calmest_frame(skeleton, accepts, samples=STAND_FRAME_SAMPLES)
            if best:
                return best, tag
        return {}, ''

    def _calmest_frame(self, skeleton, accepts, samples: int) -> Dict[str, tuple]:
        """The accepted frame that disturbs the rest pose least, or {} if none is."""
        best: Dict[str, tuple] = {}
        calmest = None

        for token in sorted(set(getattr(skeleton, 'motion_tokens', None) or [])):
            motion = self.load_motion(token)
            data = getattr(motion, 'frames', None) if motion else None
            if not data:
                continue
            total = max(1, data.get('frame_count') or 1)
            if samples <= 1:
                probes = (0,)
            else:
                probes = range(0, total, max(1, total // samples))

            for frame in probes:
                rotations = self.load_motion_pose(token, frame)
                if not rotations or not accepts(skeleton, rotations):
                    continue
                # Feet are exempt from "calm": turning them is the whole point.
                turns = [
                    2.0 * math.acos(min(1.0, abs(q[3])))
                    for name, q in rotations.items()
                    if not any(k in name for k in STAND_FOOT_BONES)
                ]
                calm = sum(turns) / len(turns) if turns else 0.0
                if calmest is None or calm < calmest:
                    calmest, best = calm, rotations

        return best

    @staticmethod
    def _stance_angles(segments: Dict[str, tuple]) -> Optional[Tuple[float, float]]:
        """
        Worst leg tilt off vertical and worst foot roll off horizontal, in degrees.

        A leg points down (-Y); a foot lies in the ground plane. Both are taken
        as the *worst* of their group, so one leg lifted mid-stride disqualifies
        the frame however good the other one is.
        """
        legs, feet = [], []
        for name, (direction, _tip) in segments.items():
            if any(k in name for k in STAND_LEG_BONES):
                legs.append(direction)
            elif any(k in name for k in STAND_FOOT_BONES):
                feet.append(direction)
        if not legs or not feet:
            return None

        def clamp(v):
            return max(-1.0, min(1.0, v))

        return (max(math.degrees(math.acos(clamp(-d[1]))) for d in legs),
                max(math.degrees(math.asin(clamp(abs(d[1])))) for d in feet))

    @staticmethod
    def _body_shape(segments: Dict[str, tuple]) -> Tuple[float, float, float]:
        """
        Height, widest horizontal spread, and how far the feet sit above the lowest point.

        The lift is a fraction of the height, so it means the same thing on a rat
        and on a giant. With nothing to stand on — a snake — it is zero, which
        lets a caller ask about it without first asking whether the creature has
        feet.
        """
        tips = [tip for _direction, tip in segments.values()]
        ys = [t[1] for t in tips]
        height = max(ys) - min(ys)
        spread = max(
            max(t[0] for t in tips) - min(t[0] for t in tips),
            max(t[2] for t in tips) - min(t[2] for t in tips),
        )
        ground = [
            tip[1] for name, (_direction, tip) in segments.items()
            if any(k in name for k in STAND_GROUND_BONES)
        ]
        lift = (min(ground) - min(ys)) / height if ground and height > 1e-6 else 0.0
        return height, spread, lift

    @classmethod
    def _stands_upright(cls, skeleton, rotations: Dict[str, tuple]) -> bool:
        """Whether a frame has this rig standing: legs under it, soles down."""
        angles = cls._stance_angles(skeleton.posed_segments(rotations))
        if angles is None:
            return False
        tilt, roll = angles
        return tilt <= STAND_MAX_LEG_TILT and roll <= STAND_MAX_FOOT_TILT

    @classmethod
    def _stands_hunched(cls, skeleton, rotations: Dict[str, tuple]) -> bool:
        """
        Whether a frame has a permanently bent-legged biped standing.

        Leg tilt alone cannot separate a crouch from a sprawl — a body lying on
        its back with its knees up scores the same as an ogre. What separates
        them is everything else about the silhouette, so a wider tilt is only
        allowed alongside the three things a sprawl gets wrong: the feet stay
        flat, the body stays taller than it is wide, and the feet stay the lowest
        part of it.
        """
        segments = skeleton.posed_segments(rotations)
        angles = cls._stance_angles(segments)
        if angles is None:
            return False
        tilt, roll = angles
        if tilt > STAND_MAX_HUNCH_TILT or roll > STAND_MAX_FOOT_TILT:
            return False
        height, spread, lift = cls._body_shape(segments)
        return height > spread and lift <= STAND_MAX_GROUND_LIFT

    @staticmethod
    def _is_bipedal(skeleton) -> bool:
        """
        Whether the upright test is the right one to judge this rig by.

        A biped carries its length in its legs; a hound, drake or viper carries
        it in spine, neck and tail. Foot count catches the spider, whose eight
        legs are long enough to read as bipedal on length alone.
        """
        legs = spine = 0.0
        feet = 0
        for bone in skeleton.bones:
            if not bone.name:
                continue
            name = bone.name.upper()
            if any(k in name for k in STAND_FOOT_BONES):
                feet += 1
            if name.startswith('R') and any(
                k in name for k in STAND_LEG_BONES + STAND_FOOT_BONES
            ):
                legs += bone.length
            if any(k in name for k in STAND_SPINE_BONES):
                spine += bone.length

        if feet > 2:
            return False
        return spine > 1e-6 and legs / spine >= STAND_BIPED_LEG_RATIO

    @staticmethod
    def _forelimbs_down(segments: Dict[str, tuple]) -> bool:
        """Whether nothing that counts as a forelimb is being held up."""
        return all(
            direction[1] <= STAND_MAX_ARM_RISE
            for name, (direction, _tip) in segments.items()
            if any(k in name for k in STAND_ARM_BONES)
        )

    @staticmethod
    def _feet_together(segments: Dict[str, tuple]) -> bool:
        """
        Whether the feet are under the body rather than stepping.

        Measured in the ground plane and scaled by body height, so it means the
        same thing on a rat and on a giant. A rig with fewer than two feet has
        no stride to measure and passes.
        """
        feet = [tip for name, (_direction, tip) in segments.items()
                if any(k in name for k in STAND_FOOT_BONES)]
        tips = [tip for _direction, tip in segments.values()]
        if len(feet) < 2 or not tips:
            return True
        ys = [t[1] for t in tips]
        height = max(ys) - min(ys)
        if height <= 1e-6:
            return True
        gap = max(math.dist((a[0], a[2]), (b[0], b[2])) for a in feet for b in feet)
        return gap / height <= STAND_MAX_FOOT_GAP

    @staticmethod
    def _arms_hang(segments: Dict[str, tuple]) -> bool:
        """Whether a biped's forelimbs hang rather than being held out or up."""
        return all(
            direction[1] <= STAND_MAX_BIPED_ARM_RISE
            for name, (direction, _tip) in segments.items()
            if any(k in name for k in STAND_ARM_BONES)
        )

    @staticmethod
    def _torso_upright(segments: Dict[str, tuple]) -> bool:
        """
        Whether the spine is near vertical rather than rolled onto a shoulder.

        The worst of the spine bones, which is the convention `_stance_angles`
        already uses for legs and feet: one segment thrown out disqualifies the
        frame however good the rest of the stack is.

        A rig that names no spine bone answers False, so it drops to the
        unconditioned rung below and keeps exactly the frame it had. That is the
        safe direction for a *preference*: no evidence must not read as
        agreement.
        """
        spine = [direction for name, (direction, _tip) in segments.items()
                 if any(k in name for k in STAND_TORSO_BONES)]
        if not spine:
            return False
        return all(
            math.degrees(math.acos(max(-1.0, min(1.0, d[1])))) <= STAND_MAX_TORSO_LEAN
            for d in spine
        )

    @classmethod
    def _stance_ladder(cls, gate):
        """
        One stance gate as four, each rung a `(tag, accepts)` pair.

        A stance gate asks where the legs and feet are, and a walk frame answers
        every part of it correctly — both soles flat, both legs under the body.
        What a walk gets wrong is what the gate does not ask: the feet are a
        stride apart and an arm is swinging. Those are asked here instead, as
        preferences rather than requirements.

        Separate rungs rather than one conjunction, because the extra conditions
        are not available together on every rig: some have frames with the arms
        down and none with the feet also together, and folding both into a
        single test drops such a rig all the way back to a swinging arm to buy a
        stride it was never going to lose. Each rung can only be reached by what
        the one above it rejected, so none of them can cost a rig the pose it
        already had.

        The torso rung is last before the bare gate, and sits there rather than
        at the top on purpose. Above it, the ladder is already choosing between
        frames whose arms hang; the rung exists for the case where it is not,
        because the bottom rung was unconditioned — it took whatever stood, in
        whatever attitude. Measured over every creature skeleton in this cache,
        **one** reaches it: 117, the only two-legged rig with no arms-down frame
        at all, whose second pair of arms are its wings. Every other rig is
        answered by a rung above and never consults this one.
        """
        def still(skeleton, rotations):
            segments = skeleton.posed_segments(rotations)
            return (gate(skeleton, rotations) and cls._arms_hang(segments)
                    and cls._feet_together(segments))

        def arms_down(skeleton, rotations):
            return (gate(skeleton, rotations)
                    and cls._arms_hang(skeleton.posed_segments(rotations)))

        def torso_up(skeleton, rotations):
            return (gate(skeleton, rotations)
                    and cls._torso_upright(skeleton.posed_segments(rotations)))

        return (('', still), ('', arms_down), ('+torso', torso_up), ('', gate))

    @classmethod
    def _rests_with_limbs_down(cls, skeleton, rotations: Dict[str, tuple]) -> bool:
        """Grounded, and not holding its forelimbs up."""
        if not cls._rests_on_ground(skeleton, rotations):
            return False
        return cls._forelimbs_down(skeleton.posed_segments(rotations))

    @classmethod
    def _rests_on_ground(cls, skeleton, rotations: Dict[str, tuple]) -> bool:
        """
        Whether a frame has a non-bipedal rig settled on the ground.

        Two things separate a real pose from the stacked rest pose: the body is
        no taller than it is wide or long, and anything the creature stands on
        is at the bottom of it. A snake has no feet, so only the first applies.
        """
        segments = skeleton.posed_segments(rotations)
        if not segments:
            return False
        height, spread, lift = cls._body_shape(segments)
        return height <= spread and lift <= STAND_MAX_GROUND_LIFT

    def load_render(self, asset_id: int) -> Optional[ArcRender]:
        """
        Load render template from the render cache.

        Args:
            asset_id: Render ID

        Returns:
            ArcRender object or None if not found
        """
        if asset_id in self.renders:
            return self.renders[asset_id]

        render = self._load_record('render', asset_id, ArcRender, "Render")
        if render is not None:
            self.renders[asset_id] = render
        return render

    # ------------------------------------------------------------------
    # CObjects
    # ------------------------------------------------------------------
    def get_cobject_summary(self, asset_id: int) -> Optional[Tuple[int, str]]:
        """
        Read just the type code and name off a COBJECT record.

        The catalog needs these for all ~10k cobjects at startup; parsing only
        the header avoids decoding every full object body.

        Returns:
            (type_code, name) or None if not found
        """
        cached = self._cobject_summaries.get(asset_id)
        if cached is not None:
            return cached

        data = self.archives['cobject'].read(asset_id)
        if data is None or len(data) < COBJECT_HEADER_SIZE:
            return None
        if data[:4] != COBJECT_MAGIC:
            print(f"CObject bad magic|id={asset_id}|magic={data[:4]!r}")
            return None

        type_code = struct.unpack_from("<I", data, 4)[0]
        try:
            name = ResStream(data[COBJECT_HEADER_SIZE:]).read_string()
        except Exception:
            name = ""

        summary = (type_code, name)
        self._cobject_summaries[asset_id] = summary
        return summary

    def load_cobject(self, asset_id: int) -> Optional[ArcCObject]:
        """
        Load a COBJECT record.

        The record body is parsed by the concrete ArcObj subclass for its type
        code, then normalised through ArcCObject so callers keep a single shape
        (`render_ids`, `skeleton_id`, `name`, ...) regardless of object type.

        Args:
            asset_id: CObject ID

        Returns:
            ArcCObject or None if not found
        """
        if asset_id in self.cobjects:
            return self.cobjects[asset_id]

        data = self.archives['cobject'].read(asset_id)
        if data is None:
            print(f"CObject missing|id={asset_id}")
            return None
        if len(data) < COBJECT_HEADER_SIZE or data[:4] != COBJECT_MAGIC:
            print(f"CObject bad magic|id={asset_id}")
            return None

        type_code = struct.unpack_from("<I", data, 4)[0]
        parser = COBJECT_TYPE_PARSERS.get(type_code)
        if parser is None:
            print(f"CObject unknown type|id={asset_id}|type={type_code}")
            return None

        try:
            obj = parser()
            obj.load_binary(ResStream(data[COBJECT_HEADER_SIZE:]))
            fields = obj.save_json()
            fields['obj_type'] = type_code

            cobject = ArcCObject()
            cobject.load_json(fields)
        except Exception as e:
            print(f"Error loading CObject {asset_id}: {e}")
            return None

        self.cobjects[asset_id] = cobject
        return cobject

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    def list_assets(self, asset_type: str) -> List[int]:
        """
        List all available asset IDs of a given type.

        Args:
            asset_type: Type of asset ('mesh', 'texture', 'skeleton', etc.)

        Returns:
            List of asset IDs
        """
        archive = self.archives.get(asset_type)
        if archive is None:
            return []
        return archive.ids()

    def get_texture_image_path(self, asset_id: int) -> Optional[str]:
        """
        Get a location string for a texture record.

        Textures live inside Textures.cache rather than as standalone files, so
        this is `<cache>#<id>` rather than an openable path.

        Args:
            asset_id: Texture ID

        Returns:
            Location string, or None if not found
        """
        return self.get_source_path('texture', asset_id)

    def clear_cache(self):
        """Clear all cached assets."""
        self.meshes.clear()
        self.textures.clear()
        self.skeletons.clear()
        self.motions.clear()
        self.renders.clear()
        self.cobjects.clear()
        self.texture_images.clear()
        self._cobject_summaries.clear()

    def close(self):
        """Close every open cache archive handle."""
        for archive in self.archives.values():
            archive.close()
