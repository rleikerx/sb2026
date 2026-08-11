from collections import OrderedDict

from arcane.util import ResStream


class ArcMotion:
    def load_binary(self, stream: ResStream):
        # Attempt to parse alternate format observed in Motion.cache
        # Layout:
        #   utf16 name, dword nFrames, skip 27 bytes, dword nAnimBones,
        #   for each bone: utf16 bone name,
        #   dword totalBlocks, then for x in frames, y in bones: AnimBlock (pos[3], rot[4], scale[3]) floats
        start = stream.buffer.tell()
        try:
            name = stream.read_string()
            frames = stream.read_dword()
            probe_pos = stream.buffer.tell()
            # The 27 bytes between the frame count and the bone count are not padding: the first
            # eight state the clip's TIME BASE, and it was being skipped. Offset 0 is an int32
            # frames-per-second and offset 4 is a float32 seconds-per-frame — its exact reciprocal.
            # Measured over all 1,503 clips: 1,483 at 15 fps and 20 at 120 fps, with zero clips where
            # the int and the float disagree, which is what says this is a stated rate rather than a
            # coincidence. Clip lengths then come out 0.07 s to 18.87 s, median 1.73 s.
            #
            # Without it a clip is a frame count with no way to play it at the right speed, which is
            # exactly what the consumer of this export reported missing.
            gap = stream.buffer.read(27)
            fps = 0
            seconds_per_frame = 0.0
            if len(gap) >= 8:
                from struct import unpack as _unpack
                (fps,) = _unpack("<i", gap[0:4])
                (seconds_per_frame,) = _unpack("<f", gap[4:8])
            stream.buffer.seek(probe_pos + 27)
            n_bones = stream.read_dword()
            # Peek first bone name length
            name_len = stream.read_dword()
            # Heuristic checks
            if frames > 0 and 0 < n_bones < 256 and 0 < name_len < 128:
                # Looks like alternate format
                self.motion_file = name
                self.motion_smoothed_count = 0
                self.motion_smoothed_value = 0
                self.motion_smoothed_factor = 0.0
                self.motion_sound = 0
                self.motion_sheath = 0
                self.motion_reset_loc = False
                self.motion_leave_ground = False
                self.motion_force = 0.0
                self.motion_disable_blend = False
                self.motion_parts = []
                self.motion_smoothing = []
                self.motion_target_frames = [frames]

                # Read bone names list
                stream.buffer.seek(probe_pos + 27)
                n_bones = stream.read_dword()
                bone_names = []
                for _ in range(n_bones):
                    bone_names.append(stream.read_string())
                # total blocks (unused for now; we rely on nFrames*nBones)
                total_blocks = stream.read_dword()
                # Read all frames
                frames_pos = []
                frames_rot = []
                frames_scl = []
                # Initialize per-bone lists
                for _ in range(n_bones):
                    frames_pos.append([])
                    frames_rot.append([])
                    frames_scl.append([])
                from struct import unpack
                for x in range(frames):
                    for y in range(n_bones):
                        # Read 10 floats: 3 pos, 4 rot, 3 scale
                        px, py, pz = stream.read_tuple()
                        rx = stream.read_float()
                        ry = stream.read_float()
                        rz = stream.read_float()
                        rw = stream.read_float()
                        sx, sy, sz = stream.read_tuple()
                        # Apply quaternion component remap seen in C++
                        # old = (rx, ry, rz, rw)
                        qx = ry
                        qy = rw
                        qz = rz
                        qw = rx
                        if y == 0:
                            qy = rz
                            qz = rw
                        frames_pos[y].append([px, py, pz])
                        frames_rot[y].append([qx, qy, qz, qw])
                        frames_scl[y].append([sx, sy, sz])

                # Store compact structure
                self.frames = {
                    'bones': {
                        bone_names[i]: {
                            'pos': frames_pos[i],
                            'rot': frames_rot[i],
                            'scale': frames_scl[i],
                        } for i in range(n_bones)
                    },
                    'frame_count': frames,
                    # Stated by the clip rather than assumed by the reader. Zero means the header was
                    # short and the caller should say so instead of inventing 30.
                    'fps': fps,
                    'seconds_per_frame': seconds_per_frame,
                }
                return
        except Exception:
            # Fall back to legacy format below
            stream.buffer.seek(start)

        # Legacy/metadata-only format
        self.motion_file = stream.read_string()
        self.motion_smoothed_count = stream.read_dword()
        self.motion_smoothed_value = stream.read_dword()
        self.motion_smoothed_factor = stream.read_float()
        self.motion_sound = stream.read_qword()
        self.motion_sheath = stream.read_dword()
        self.motion_reset_loc = stream.read_bool()
        self.motion_leave_ground = stream.read_bool()
        self.motion_force = stream.read_float()
        self.motion_disable_blend = stream.read_bool()
        num_parts = stream.read_dword()
        self.motion_parts = [stream.read_string() for _ in range(num_parts)]
        num_smoothing = stream.read_dword()
        self.motion_smoothing = [
            [
                stream.read_float() for _ in range(10)
            ] for _ in range(num_smoothing)
        ]
        num_target_frames = stream.read_dword()
        self.motion_target_frames = [stream.read_dword() for _ in range(num_target_frames)]

    def save_binary(self, stream: ResStream):
        # Not used for alternate format in this project
        stream.write_string(self.motion_file)
        stream.write_dword(self.motion_smoothed_count)
        stream.write_dword(self.motion_smoothed_value)
        stream.write_float(self.motion_smoothed_factor)
        stream.write_qword(self.motion_sound)
        stream.write_dword(self.motion_sheath)
        stream.write_bool(self.motion_reset_loc)
        stream.write_bool(self.motion_leave_ground)
        stream.write_float(self.motion_force)
        stream.write_bool(self.motion_disable_blend)
        stream.write_dword(len(self.motion_parts))
        for i in range(len(self.motion_parts)):
            stream.write_string(self.motion_parts[i])
        stream.write_dword(len(self.motion_smoothing))
        for i in range(len(self.motion_smoothing)):
            for j in range(10):
                stream.write_float(self.motion_smoothing[i][j])
        stream.write_dword(len(self.motion_target_frames))
        for i in range(len(self.motion_target_frames)):
            stream.write_dword(self.motion_target_frames[i])

    def load_json(self, data):
        self.motion_file = data['motion_file']
        self.motion_smoothed_count = data.get('motion_smoothed_count', 0)
        self.motion_smoothed_value = data.get('motion_smoothed_value', 0)
        self.motion_smoothed_factor = data.get('motion_smoothed_factor', 0.0)
        self.motion_sound = data.get('motion_sound', 0)
        self.motion_sheath = data.get('motion_sheath', 0)
        self.motion_reset_loc = data.get('motion_reset_loc', False)
        self.motion_leave_ground = data.get('motion_leave_ground', False)
        self.motion_force = data.get('motion_force', 0.0)
        self.motion_disable_blend = data.get('motion_disable_blend', False)
        self.motion_parts = data.get('motion_parts', [])
        self.motion_smoothing = data.get('motion_smoothing', [])
        self.motion_target_frames = data.get('motion_target_frames', [])
        self.frames = data.get('frames', None)

    def save_json(self):
        data = OrderedDict()
        data['motion_file'] = self.motion_file
        if hasattr(self, 'frames'):
            data['frames'] = self.frames
        else:
            data['motion_smoothed_count'] = self.motion_smoothed_count
            data['motion_smoothed_value'] = self.motion_smoothed_value
            data['motion_smoothed_factor'] = self.motion_smoothed_factor
            data['motion_sound'] = self.motion_sound
            data['motion_sheath'] = self.motion_sheath
            data['motion_reset_loc'] = self.motion_reset_loc
            data['motion_leave_ground'] = self.motion_leave_ground
            data['motion_force'] = self.motion_force
            data['motion_disable_blend'] = self.motion_disable_blend
            data['motion_parts'] = self.motion_parts
            data['motion_smoothing'] = self.motion_smoothing
            data['motion_target_frames'] = self.motion_target_frames
        return data
