
import math
from collections import OrderedDict
from arcane.util import ResStream

MAGIC_SKEL = b'SKEL'
CURRENT_VERSION = 3
IDENTITY_3X3 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


# ────────────────────── small row-major 3x3 helpers ──────────────────────
# Kept as plain tuples so this module stays free of numpy, like the rest of
# arcane/. Callers that want 4x4s build them from these.

def _quat_to_mat(q):
    """(x, y, z, w) -> row-major 3x3. Degenerate quaternions fall back to identity."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-9:
        return IDENTITY_3X3
    x, y, z, w = x / n, y / n, z / n, w / n
    return (
        1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w),
        2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w),
        2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y),
    )


def _mat_mul(a, b):
    return tuple(
        a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c]
        for r in range(3) for c in range(3)
    )


def _mat_apply(m, v):
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    )


def _mat_transpose(m):
    """A rotation matrix's inverse."""
    return (m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8])


def _quat_mul(a, b):
    """(x, y, z, w) * (x, y, z, w), same order convention as `_mat_mul`."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def _euler_to_quat(v):
    """
    Radian (x, y, z) triple -> (x, y, z, w), composed Z then Y then X.

    The quaternion twin of `_euler_to_mat`, and the form the client actually
    computes in: `MakeTripleRotate` returns a quaternion and the setup pass
    stores it as one. Kept alongside the matrix version rather than derived from
    it so neither has to round-trip through the other.
    """
    hx, hy, hz = v[0] * 0.5, v[1] * 0.5, v[2] * 0.5
    qx = (math.sin(hx), 0.0, 0.0, math.cos(hx))
    qy = (0.0, math.sin(hy), 0.0, math.cos(hy))
    qz = (0.0, 0.0, math.sin(hz), math.cos(hz))
    return _quat_mul(_quat_mul(qz, qy), qx)


def _euler_to_mat(v):
    """
    Radian (x, y, z) triple -> row-major 3x3, composed Z then Y then X.

    This is `math::Quaternion::MakeTripleRotate`, which `Math.dll` exports and
    which `FromEuler` tail-calls -- the client has exactly one Euler path and
    this is it. See docs/CLIENT_BINARY_FINDINGS.md section 3.
    """
    sx, cx = math.sin(v[0]), math.cos(v[0])
    sy, cy = math.sin(v[1]), math.cos(v[1])
    sz, cz = math.sin(v[2]), math.cos(v[2])
    rx = (1.0, 0.0, 0.0, 0.0, cx, -sx, 0.0, sx, cx)
    ry = (cy, 0.0, sy, 0.0, 1.0, 0.0, -sy, 0.0, cy)
    rz = (cz, -sz, 0.0, sz, cz, 0.0, 0.0, 0.0, 1.0)
    return _mat_mul(_mat_mul(rz, ry), rx)


class ArcBoneRecord(object):
    __slots__ = ('name_hash', 'parent_index', 'flags', 'bind_pose_matrix', 'name',
                 'direction', 'length', 'axis', 'flip', '_axis_matrix')

    def __init__(self):
        self.name_hash = 0
        self.parent_index = -1  # -1 denotes root
        self.flags = 0          # attachment / billboard bits
        self.bind_pose_matrix = [0.0] * 16
        self.name = None        # optional string name when available
        # ASF-style rest geometry (present in the string-headed format).
        self.direction = (0.0, 0.0, 0.0)
        self.length = 0.0
        self.axis = (0.0, 0.0, 0.0)
        self.flip = 0           # mirrored limb: reuse the opposite side's mesh
        self._axis_matrix = None  # lazily built from `axis`; see `joint_frame`

    # ────────────────────────── binary ──────────────────────────

    def load_binary(self, stream: ResStream):
        self.name_hash = stream.read_dword()

        raw_parent = stream.read_word()
        # Treat as signed int16
        if raw_parent >= 0x8000:
            raw_parent -= 0x10000
        self.parent_index = raw_parent

        self.flags = stream.read_word()
        self.bind_pose_matrix = [stream.read_float() for _ in range(16)]

    def save_binary(self, stream: ResStream):
        stream.write_dword(self.name_hash)
        stream.write_word(self.parent_index & 0xFFFF)
        stream.write_word(self.flags)
        for value in self.bind_pose_matrix:
            stream.write_float(value)

    # ────────────────────────── json ──────────────────────────

    def load_json(self, data):
        self.name_hash = data['name_hash']
        self.parent_index = data['parent_index']
        self.flags = data['flags']
        self.bind_pose_matrix = data['bind_pose_matrix']
        self.name = data.get('name')
        self.direction = tuple(data.get('direction', (0.0, 0.0, 0.0)))
        self.length = data.get('length', 0.0)
        self.axis = tuple(data.get('axis', (0.0, 0.0, 0.0)))
        self.flip = data.get('flip', 0)
        self._axis_matrix = None

    def save_json(self):
        out = OrderedDict([
            ('name_hash', self.name_hash),
            ('parent_index', self.parent_index),
            ('flags', self.flags),
            ('bind_pose_matrix', self.bind_pose_matrix),
        ])
        if self.name is not None:
            out['name'] = self.name
        out['direction'] = list(self.direction)
        out['length'] = self.length
        out['axis'] = list(self.axis)
        out['flip'] = self.flip
        return out

    # ────────────────────────── joint frame ──────────────────────────

    def joint_frame(self):
        """
        The bone's own coordinate frame, as a row-major 3x3. `axis` is its Euler
        triple, and this is what ASF calls the bone's axis.

        Cached because a pose evaluates it once per bone per frame.
        """
        if self._axis_matrix is None:
            self._axis_matrix = _euler_to_mat(self.axis)
        return self._axis_matrix

    def local_rotation(self, quaternion):
        """
        A clip's (x, y, z, w) for this bone -> its turn in the *parent's* frame.

        A motion clip states a bone's rotation in that bone's own frame, so it
        has to be carried back out through `axis` before it can be composed with
        the parent: `C * R * C^-1`. The client does exactly this. `ArcSkeleton`'s
        setup pass (`sb.exe` 0x5d78c0, recursing through 0x5d7ba0) reads the raw
        axis at `bone+0x30`, calls `Quaternion::MakeTripleRotate` on it, stores
        the result at `bone+0x90` and its `Quaternion::Inverse` at `bone+0xa0`,
        then hands each child *its parent's* inverse to keep at `bone+0xb0` --
        which is the ASF chain `A_i = A_parent * C_parent^-1 * C_i * R_i` with
        the constant factors precomputed. Composing world-space turns instead,
        as `pose` does, the same chain reads `G_i = G_parent * C_i R_i C_i^-1`.

        Bones the clip does not name keep their rest frame: `C * I * C^-1` is
        the identity, so leaving them out and passing identity agree.
        """
        rotation = _quat_to_mat(quaternion)
        if not any(self.axis):
            return rotation
        frame = self.joint_frame()
        return _mat_mul(_mat_mul(frame, rotation), _mat_transpose(frame))

    def local_rotation_quat(self, quaternion):
        """
        `local_rotation` without the detour through a matrix: quaternion in,
        quaternion out, `C * R * C^-1`.

        For exporters that hand a consumer rotations rather than positions. The
        matrix form is what `pose` wants; this is what a glTF track wants.
        """
        if not any(self.axis):
            return tuple(quaternion)
        frame = _euler_to_quat(self.axis)
        inverse = (-frame[0], -frame[1], -frame[2], frame[3])
        return _quat_mul(_quat_mul(frame, tuple(quaternion)), inverse)

    def clip_rotation(self, matrix):
        """
        Inverse of `local_rotation`: a turn in the parent's frame -> this bone's.

        For code that *authors* a rotation geometrically and then feeds it back
        through `pose` as though a clip had supplied it.
        """
        if not any(self.axis):
            return matrix
        frame = self.joint_frame()
        return _mat_mul(_mat_mul(_mat_transpose(frame), matrix), frame)


class ArcSkeleton(object):
    """In-memory representation of Shadowbane *.skel* files (see asset-loading.md)."""

    def __init__(self):
        self.version = CURRENT_VERSION
        self.flags = 0
        self.bones = []          # type: list[ArcBoneRecord]
        self.motion_tokens = []  # type: list[int]

    # ────────────────────────── binary ──────────────────────────

    def load_binary(self, stream: ResStream):
        # Support two observed formats:
        # 1) 'SKEL' magic, then version/counts/flags
        # 2) UTF-16 length-prefixed string (e.g., 'skeleton'), then animations table, then bones
        pos = stream.buffer.tell()
        head = stream.read_bytes(4)
        if head == MAGIC_SKEL:
            # Original format
            self.version = stream.read_dword()
            bone_count = stream.read_word()
            motion_count = stream.read_word()
            self.flags = stream.read_dword()

            self.bones = []
            for _ in range(bone_count):
                bone = ArcBoneRecord()
                bone.load_binary(stream)
                self.bones.append(bone)

            self.motion_tokens = [stream.read_dword() for _ in range(motion_count)]
            return

        # Alternate format: rewind and parse string name, then animations, then bones
        stream.buffer.seek(pos)
        _name = stream.read_string()  # e.g., 'skeleton'

        # Animations list (ids referencing Motion.cache)
        try:
            anim_count = stream.read_dword()
        except Exception:
            anim_count = 0
        motion_tokens: list[int] = []
        for _ in range(anim_count):
            # Layout per C++: 4 bytes skip, 4 bytes id, 8 bytes skip
            try:
                _skip_a = stream.read_dword()
                anim_id = stream.read_dword()
                if anim_id > 0:
                    motion_tokens.append(anim_id)
                # skip two dwords
                _skip_b = stream.read_dword()
                _skip_c = stream.read_dword()
            except Exception:
                break

        # Bones: read until we can no longer parse a full record
        bones: list[ArcBoneRecord] = []
        nchildren: list[int] = []
        while True:
            try:
                # Probe if at EOF: attempt to read next dword of id
                peek_pos = stream.buffer.tell()
                maybe_id = stream.read_bytes(4)
                if len(maybe_id) < 4:
                    break
                stream.buffer.seek(peek_pos)

                # Bone id (use as name_hash surrogate)
                bone_id = stream.read_dword()

                # UTF-16 bone name
                bone_name = stream.read_string()

                # Direction (Vec3)
                dir_x, dir_y, dir_z = stream.read_tuple()
                # Length
                bone_length = stream.read_float()
                # Axis (Vec3) - Euler angles, radians
                axis_x, axis_y, axis_z = stream.read_tuple()

                # Skip flags string
                try:
                    flen = stream.read_dword()
                    if flen > 0:
                        _ = stream.read_bytes(flen * 2)
                except Exception:
                    flen = 0

                # Skip 36 bytes of unused data
                _ = stream.read_bytes(36)

                # Flip flag and unknown flag
                flip = stream.read_byte()
                _unknown = stream.read_byte()

                # Number of children
                child_count = stream.read_dword()

                b = ArcBoneRecord()
                b.name_hash = bone_id
                b.parent_index = -1
                b.flags = 0
                b.name = bone_name
                b.direction = (dir_x, dir_y, dir_z)
                b.length = bone_length
                b.axis = (axis_x, axis_y, axis_z)
                b.flip = flip
                # This format carries no explicit matrix (the 36 skipped bytes
                # are zero throughout). Rest pose is ASF-style: the bone runs
                # from its parent's tip along `direction` for `length`, so the
                # local transform is that offset.
                b.bind_pose_matrix = [1.0, 0.0, 0.0, dir_x * bone_length,
                                      0.0, 1.0, 0.0, dir_y * bone_length,
                                      0.0, 0.0, 1.0, dir_z * bone_length,
                                      0.0, 0.0, 0.0, 1.0]
                bones.append(b)
                nchildren.append(child_count)
            except Exception:
                break

        # Reconstruct parent indices based on sequential layout and nChildren
        setup = [False] * len(bones)
        next_idx = 1

        def assign(idx: int, parent: int):  # noqa: ANN001
            nonlocal next_idx
            bones[idx].parent_index = parent
            setup[idx] = True
            for _ in range(nchildren[idx] if idx < len(nchildren) else 0):
                # find next unused bone
                while next_idx < len(bones) and setup[next_idx]:
                    next_idx += 1
                if next_idx >= len(bones):
                    return
                child = next_idx
                next_idx += 1
                assign(child, idx)

        if bones:
            assign(0, -1)

        self.version = CURRENT_VERSION
        self.flags = 0
        self.bones = bones
        self.motion_tokens = motion_tokens
        return

    # ────────────────────────── rest pose ──────────────────────────

    def bone_tips(self):
        """
        Model-space position of each bone's tip in the rest pose.

        Bones are stored parent-before-child, so a single forward pass resolves
        the whole hierarchy.
        """
        tips = [(0.0, 0.0, 0.0)] * len(self.bones)
        for i, bone in enumerate(self.bones):
            if 0 <= bone.parent_index < i:
                px, py, pz = tips[bone.parent_index]
            else:
                px, py, pz = 0.0, 0.0, 0.0
            dx, dy, dz = bone.direction
            tips[i] = (px + dx * bone.length, py + dy * bone.length, pz + dz * bone.length)
        return tips

    def attach_points(self):
        """
        Map bone name -> the joint a mesh attached to that bone sits on.

        Part meshes are modelled about the joint at the *start* of their bone,
        which is the parent's tip.
        """
        return {name: position for name, (_rotation, position) in self.pose().items()}

    def pose(self, rotations=None):
        """
        Map bone name -> (rotation, position) for the joint its mesh hangs from.

        `rotations` gives a bone's local turn as an (x, y, z, w) quaternion, the
        form the motion clips store; bones it leaves out stay at rest. Passing
        nothing yields the rest layout with an identity rotation on every joint,
        which is what `attach_points` reports.

        The rest pose the cache stores is a zero pose — every limb bone runs
        straight down its axis, so feet point at the floor and knees never bend.
        A standing character is a clip frame applied on top of it, which is why
        this takes rotations at all.

        Rotation is row-major 3x3. Bones are stored parent-before-child, so one
        forward pass resolves the hierarchy.
        """
        rotations = rotations or {}
        rots = [IDENTITY_3X3] * len(self.bones)
        tips = [(0.0, 0.0, 0.0)] * len(self.bones)
        out = {}

        for i, bone in enumerate(self.bones):
            if 0 <= bone.parent_index < i:
                parent_rot = rots[bone.parent_index]
                start = tips[bone.parent_index]
            else:
                parent_rot = IDENTITY_3X3
                start = (0.0, 0.0, 0.0)

            local = rotations.get(bone.name.upper()) if bone.name else None
            rots[i] = (_mat_mul(parent_rot, bone.local_rotation(local))
                       if local else parent_rot)

            dx, dy, dz = bone.direction
            sx, sy, sz = _mat_apply(
                rots[i], (dx * bone.length, dy * bone.length, dz * bone.length)
            )
            tips[i] = (start[0] + sx, start[1] + sy, start[2] + sz)

            if bone.name:
                out[bone.name.upper()] = (rots[i], start)

        return out

    def posed_segments(self, rotations=None):
        """
        Map bone name -> (unit direction, tip) with `rotations` applied.

        Where `pose` gives the joint a mesh hangs from, this gives the bone's
        own line, which is what tells you whether a limb is upright or a foot
        is lying flat. Zero-length bones — attachment points like HELM or
        LHELD — have no direction and are left out.
        """
        out = {}
        joints = self.pose(rotations)
        for bone in self.bones:
            if not bone.name or bone.length <= 1e-6:
                continue
            entry = joints.get(bone.name.upper())
            if entry is None:
                continue
            rotation, start = entry
            seg = _mat_apply(rotation, tuple(c * bone.length for c in bone.direction))
            out[bone.name.upper()] = (
                tuple(c / bone.length for c in seg),
                (start[0] + seg[0], start[1] + seg[1], start[2] + seg[2]),
            )
        return out

    def node_hierarchy(self, rotations=None):
        """
        The same pose as a tree: bone name -> (parent name, local 4x4, flip).

        `pose` hands back every joint already resolved into model space, which
        is what you want to place a mesh and the wrong thing to write into a
        scene file. This gives each bone's transform *relative to its parent*,
        so a consumer can drive the rig itself — walk the tree and the chain
        reproduces `pose` exactly, or replace a rotation and the limb below it
        follows.

        A bone's local transform is its parent's own length along its parent's
        direction, then this bone's rotation. Matrices are row-major 16-float
        lists, matching `bind_pose_matrix`. Order is the file's, parents first.
        """
        rotations = rotations or {}
        out = OrderedDict()

        for i, bone in enumerate(self.bones):
            if not bone.name:
                continue

            parent = None
            offset = (0.0, 0.0, 0.0)
            if 0 <= bone.parent_index < i:
                parent_bone = self.bones[bone.parent_index]
                if parent_bone.name:
                    parent = parent_bone.name.upper()
                dx, dy, dz = parent_bone.direction
                offset = (dx * parent_bone.length,
                          dy * parent_bone.length,
                          dz * parent_bone.length)

            local = rotations.get(bone.name.upper())
            r = bone.local_rotation(local) if local else IDENTITY_3X3
            out[bone.name.upper()] = (
                parent,
                [r[0], r[1], r[2], offset[0],
                 r[3], r[4], r[5], offset[1],
                 r[6], r[7], r[8], offset[2],
                 0.0, 0.0, 0.0, 1.0],
                int(getattr(bone, 'flip', 0) or 0),
            )

        return out

    # ────────────────────────── json ──────────────────────────

    def load_json(self, data):
        self.version = data.get('version', CURRENT_VERSION)
        self.flags = data.get('flags', 0)

        self.bones = []
        for bone_data in data.get('bones', []):
            bone = ArcBoneRecord()
            bone.load_json(bone_data)
            self.bones.append(bone)

        self.motion_tokens = data.get('motion_tokens', [])

    def save_json(self):
        return OrderedDict([
            ('version', self.version),
            ('flags', self.flags),
            ('bones', [b.save_json() for b in self.bones]),
            ('motion_tokens', self.motion_tokens),
        ])
