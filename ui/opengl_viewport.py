"""
OpenGL Viewport - 3D rendering viewport with camera controls.
"""

from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QSurfaceFormat
from OpenGL.GL import *
import numpy as np
import os
from typing import Iterable, List, Optional

from rendering.camera import Camera
from rendering.shader_manager import ShaderManager
from rendering.mesh_renderer import MeshRenderer
from rendering.texture_manager import TextureManager
from rendering.runtime_render_payload import (
    ByteMemoryReader,
    ImmediateSubmissionRequest,
    MemorySegment,
    RuntimeImmediateSubmission,
    RuntimeRenderParser,
)
from rendering.mesh_renderer import ImmediateRenderRequest
from rendering.runtime_dispatch_dump import dump_runtime_dispatch_candidates
from animation.skeletal_animator import SkeletalAnimator
from animation.animation_controller import AnimationController
import time
from assets.asset_catalog import AssembledAsset, MeshPart


class OpenGLViewport(QOpenGLWidget):
    """
    OpenGL 3.3 viewport for rendering 3D assets.
    """

    # Signals
    fps_updated = pyqtSignal(float)  # Emit FPS
    frame_updated = pyqtSignal(float)  # Emit current animation frame

    def __init__(self, asset_manager, parent=None):
        super().__init__(parent)

        # Set OpenGL format
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)  # 4x MSAA
        self.setFormat(fmt)

        # Asset manager
        self.asset_manager = asset_manager

        # Rendering components (initialized in initializeGL)
        self.camera: Optional[Camera] = None
        self.shader_manager: Optional[ShaderManager] = None
        self.mesh_renderer: Optional[MeshRenderer] = None
        self.texture_manager: Optional[TextureManager] = None

        # Current asset
        self.current_mesh_id: Optional[int] = None
        self.current_texture_id: Optional[int] = None
        self.current_parts: List[MeshPart] = []
        self._pending_assembled_asset: Optional[AssembledAsset] = None
        self._pending_single_mesh: Optional[tuple[int, Optional[int], Optional[int], Optional[int]]] = None
        self.current_runtime_submission: Optional[RuntimeImmediateSubmission] = None
        self.current_segments: List[MemorySegment] = []

        # Animation components
        self.skeletal_animator: Optional[SkeletalAnimator] = None
        self.animation_controller: Optional[AnimationController] = None
        self.last_frame_time = time.time()

        # Animation timer (updates animation)
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._update_animation)
        self.animation_timer.start(16)  # ~60 FPS

        # Mouse state
        self.last_mouse_pos = None
        self.mouse_button = None

        # FPS counter
        self.frame_count = 0
        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self._update_fps)
        self.fps_timer.start(1000)  # Update every second

        # Enable mouse tracking
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def initializeGL(self):
        """Initialize OpenGL resources."""
        print(f"OpenGL Version: {glGetString(GL_VERSION).decode()}")
        print(f"GLSL Version: {glGetString(GL_SHADING_LANGUAGE_VERSION).decode()}")
        print(f"Renderer: {glGetString(GL_RENDERER).decode()}")

        # Initialize camera
        self.camera = Camera(self.width(), self.height())

        # Initialize shader manager
        self.shader_manager = ShaderManager()
        self.basic_shader = self.shader_manager.load_shader("basic", "basic.vert", "basic.frag")
        self.skinned_shader = self.shader_manager.load_shader("skinned", "skinned.vert", "skinned.frag")

        if not self.basic_shader:
            print("ERROR: Failed to load basic shader!")
            return
        if not self.skinned_shader:
            print("ERROR: Failed to load skinned shader!")
            return

        # Initialize renderers
        self.mesh_renderer = MeshRenderer()
        self.texture_manager = TextureManager(self.asset_manager)

        # OpenGL state
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glEnable(GL_MULTISAMPLE)  # Enable MSAA

        # Clear color (dark gray)
        glClearColor(0.2, 0.2, 0.2, 1.0)

        print("OpenGL initialized successfully")

        # Apply any deferred loads that happened before GL init
        if self._pending_assembled_asset is not None:
            asset = self._pending_assembled_asset
            self._pending_assembled_asset = None
            self.load_assembled_asset(asset)
        elif self._pending_single_mesh is not None:
            mesh_id, texture_id, skeleton_id, motion_id = self._pending_single_mesh
            self._pending_single_mesh = None
            self.load_mesh(mesh_id, texture_id, skeleton_id, motion_id)

    def resizeGL(self, w: int, h: int):
        """Handle viewport resize."""
        glViewport(0, 0, w, h)
        if self.camera:
            self.camera.resize(w, h)

    def paintGL(self):
        """Render frame."""
        # Clear buffers
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        if not self.camera or not self.basic_shader:
            return

        # Get camera matrices
        view_matrix = self.camera.get_view_matrix()
        projection_matrix = self.camera.get_projection_matrix()
        model_matrix = np.identity(4, dtype=np.float32)

        # Calculate normal matrix (for lighting)
        normal_matrix = np.linalg.inv(model_matrix).T

        # Choose shader based on whether we have animation
        has_animation = self.skeletal_animator is not None and self.animation_controller is not None
        shader = self.skinned_shader if has_animation else self.basic_shader

        # Set shader uniforms
        shader.use()
        shader.set_mat4("uModel", model_matrix)
        shader.set_mat4("uView", view_matrix)
        shader.set_mat4("uProjection", projection_matrix)
        shader.set_mat4("uNormalMatrix", normal_matrix)

        # Lighting parameters
        shader.set_vec3("uLightDir", np.array([0.5, 1.0, 0.3], dtype=np.float32))
        shader.set_vec3("uLightColor", np.array([1.0, 1.0, 1.0], dtype=np.float32))
        shader.set_vec3("uAmbientColor", np.array([0.3, 0.3, 0.3], dtype=np.float32))
        shader.set_vec3("uViewPos", self.camera.get_position())

        if self.current_runtime_submission and self.mesh_renderer:
            self.mesh_renderer.render_immediate_payload(
                ImmediateRenderRequest(submission=self.current_runtime_submission, shader_program=shader)
            )
            self._render_grid()
            self.frame_count += 1
            return

        # Render assembled parts (preferred), else fallback to single-mesh mode
        if self.current_parts and self.mesh_renderer:
            bone_matrices = None
            if has_animation and self.skeletal_animator:
                bone_matrices = self.skeletal_animator.get_skinning_matrices()

            for part in self.current_parts:
                gpu_mesh = self.mesh_renderer.meshes.get(part.mesh_id)
                if not gpu_mesh:
                    continue

                # Per-part model + normal matrix
                shader.set_mat4("uModel", part.transform)
                shader.set_mat4("uNormalMatrix", np.linalg.inv(part.transform).T)

                # Mirrored limbs carry a negative determinant, which reverses
                # triangle winding; without flipping the front face they would
                # be culled away entirely.
                glFrontFace(GL_CW if np.linalg.det(part.transform[:3, :3]) < 0 else GL_CCW)

                tex_gl_id = None
                if part.texture_id is not None:
                    tex_gl_id = self.texture_manager.load_texture(part.texture_id)

                self.mesh_renderer.render_mesh(gpu_mesh, shader, tex_gl_id, bone_matrices)

            glFrontFace(GL_CCW)

        elif self.current_mesh_id is not None and self.mesh_renderer:
            gpu_mesh = self.mesh_renderer.meshes.get(self.current_mesh_id)
            if gpu_mesh:
                texture_id = None
                if self.current_texture_id is not None:
                    texture_id = self.texture_manager.load_texture(self.current_texture_id)

                bone_matrices = None
                if has_animation and self.skeletal_animator:
                    bone_matrices = self.skeletal_animator.get_skinning_matrices()

                self.mesh_renderer.render_mesh(gpu_mesh, shader, texture_id, bone_matrices)

        # Render grid (optional)
        self._render_grid()

        # Update FPS
        self.frame_count += 1

    def load_runtime_dispatch(self, dispatch_address: int, segments: Iterable[MemorySegment]) -> None:
        if not self.mesh_renderer or not self.camera:
            return

        self.current_segments = list(segments)
        reader = ByteMemoryReader(segments)
        parser = RuntimeRenderParser()
        submission = parser.parse_immediate_submission(
            request=ImmediateSubmissionRequest(reader=reader, dispatch_address=dispatch_address)
        )
        if submission is None:
            return

        self.current_runtime_submission = submission
        self.current_mesh_id = None
        self.current_texture_id = None
        self.current_parts = []
        self.skeletal_animator = None
        self.animation_controller = None
        self.update()

    def dump_runtime_dispatches(self) -> None:
        if not self.current_segments:
            print("runtime_dump_skipped|reason=no_segments")
            return
        output_dir = os.path.join(os.getcwd(), "dumps")
        paths = dump_runtime_dispatch_candidates(
            segments=self.current_segments,
            output_dir=output_dir,
            max_candidates=25,
        )
        print("runtime_dump_written|count=%d" % len(paths))
        for p in paths[:10]:
            print("runtime_dump_file|path=%s" % p)

    def _render_grid(self):
        """Render a grid on the ground plane for reference."""
        # TODO: Implement grid rendering (optional)
        pass

    def load_mesh(self, mesh_id: int, texture_id: Optional[int] = None, skeleton_id: Optional[int] = None, motion_id: Optional[int] = None):
        """
        Load and display a mesh.

        Args:
            mesh_id: Mesh asset ID
            texture_id: Optional texture asset ID
            skeleton_id: Optional skeleton asset ID
            motion_id: Optional motion/animation asset ID
        """
        # If GL not ready yet, defer the request
        if not self.mesh_renderer or not self.camera:
            self._pending_single_mesh = (mesh_id, texture_id, skeleton_id, motion_id)
            return

        # Ensure the widget's GL context is current for any GL calls (VAO/VBO creation)
        self.makeCurrent()

        # Load mesh from asset manager
        mesh = self.asset_manager.load_mesh(mesh_id)
        if not mesh:
            print(f"Failed to load mesh {mesh_id}")
            self.doneCurrent()
            return

        # Upload to GPU
        gpu_mesh = self.mesh_renderer.upload_mesh(mesh, mesh_id)
        if not gpu_mesh:
            print(f"Failed to upload mesh {mesh_id}")
            self.doneCurrent()
            return

        # Set as current
        self.current_mesh_id = mesh_id
        self.current_texture_id = texture_id
        self.current_runtime_submission = None
        self.current_parts = [
            MeshPart(
                mesh_id=mesh_id,
                texture_id=texture_id,
                transform=np.identity(4, dtype=np.float32),
                source_render_id=0,
                target_bone=None,
            )
        ]

        # Load skeleton and animation if provided
        self.skeletal_animator = None
        self.animation_controller = None

        if skeleton_id is not None:
            skeleton = self.asset_manager.load_skeleton(skeleton_id)
            if skeleton:
                self.skeletal_animator = SkeletalAnimator(skeleton)
                print(f"Loaded skeleton {skeleton_id} with {len(self.skeletal_animator.bones)} bones")

                # Load motion if provided
                if motion_id is not None:
                    motion = self.asset_manager.load_motion(motion_id)
                    if motion:
                        self.animation_controller = AnimationController(motion)
                        print(f"Loaded motion {motion_id} with {self.animation_controller.frame_count} frames")

        # Frame camera on mesh
        self.camera.frame_object(gpu_mesh.bounds_min, gpu_mesh.bounds_max)

        # Trigger redraw
        self.update()

        print(f"Loaded mesh {mesh_id}" + (f" with texture {texture_id}" if texture_id else ""))
        self.doneCurrent()

    def load_assembled_asset(self, asset: AssembledAsset) -> None:
        """
        Load and display an assembled multi-mesh asset.

        Materials are simplified: first texture in each render is applied to all meshes in that render.
        """
        if not self.mesh_renderer or not self.camera:
            # GL not initialized yet; defer
            self._pending_assembled_asset = asset
            return

        # Ensure the widget's GL context is current for any GL calls (VAO/VBO creation)
        self.makeCurrent()

        self.current_mesh_id = None
        self.current_texture_id = None
        self.current_runtime_submission = None
        self.current_parts = asset.parts

        # Disable animation for now (Task C will drive skeleton attachment rules)
        self.skeletal_animator = None
        self.animation_controller = None

        # Upload all meshes referenced by the assembled asset
        for part in self.current_parts:
            mesh = self.asset_manager.load_mesh(part.mesh_id)
            if not mesh:
                continue
            self.mesh_renderer.upload_mesh(mesh, part.mesh_id)

        # Frame camera on combined transformed bounds
        bounds_min, bounds_max = self._compute_scene_bounds(self.current_parts)
        if bounds_min is not None and bounds_max is not None:
            self.camera.frame_object(bounds_min, bounds_max)

        self.update()
        self.doneCurrent()

    def _compute_scene_bounds(self, parts: List[MeshPart]) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if not self.mesh_renderer:
            return (None, None)

        scene_min: Optional[np.ndarray] = None
        scene_max: Optional[np.ndarray] = None

        for part in parts:
            gpu_mesh = self.mesh_renderer.meshes.get(part.mesh_id)
            if not gpu_mesh:
                continue

            local_min = gpu_mesh.bounds_min
            local_max = gpu_mesh.bounds_max
            corners = np.array(
                [
                    [local_min[0], local_min[1], local_min[2], 1.0],
                    [local_min[0], local_min[1], local_max[2], 1.0],
                    [local_min[0], local_max[1], local_min[2], 1.0],
                    [local_min[0], local_max[1], local_max[2], 1.0],
                    [local_max[0], local_min[1], local_min[2], 1.0],
                    [local_max[0], local_min[1], local_max[2], 1.0],
                    [local_max[0], local_max[1], local_min[2], 1.0],
                    [local_max[0], local_max[1], local_max[2], 1.0],
                ],
                dtype=np.float32,
            )
            world = (part.transform @ corners.T).T[:, :3]
            wmin = np.min(world, axis=0)
            wmax = np.max(world, axis=0)

            if scene_min is None:
                scene_min = wmin
                scene_max = wmax
            else:
                scene_min = np.minimum(scene_min, wmin)
                scene_max = np.maximum(scene_max, wmax)

        return (scene_min, scene_max)

    def mousePressEvent(self, event):
        """Handle mouse press."""
        self.last_mouse_pos = event.pos()
        self.mouse_button = event.button()

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        self.last_mouse_pos = None
        self.mouse_button = None

    def mouseMoveEvent(self, event):
        """Handle mouse move (camera controls)."""
        if self.last_mouse_pos is None:
            return

        # Calculate delta
        dx = event.pos().x() - self.last_mouse_pos.x()
        dy = event.pos().y() - self.last_mouse_pos.y()

        # Rotate camera (left button)
        if self.mouse_button == Qt.MouseButton.LeftButton:
            self.camera.rotate(-dx * 0.5, -dy * 0.5)
            self.update()

        # Pan camera (middle button or Shift+Left)
        elif self.mouse_button == Qt.MouseButton.MiddleButton or \
             (self.mouse_button == Qt.MouseButton.LeftButton and
              event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.camera.pan(dx, -dy)
            self.update()

        self.last_mouse_pos = event.pos()

    def wheelEvent(self, event):
        """Handle mouse wheel (zoom)."""
        delta = event.angleDelta().y() / 120.0  # Normalize to steps
        self.camera.zoom(-delta)
        self.update()

    def keyPressEvent(self, event):
        """Handle key press."""
        if event.key() == Qt.Key.Key_R:
            # Reset camera
            self.camera.reset()
            if self.current_mesh_id is not None:
                gpu_mesh = self.mesh_renderer.meshes.get(self.current_mesh_id)
                if gpu_mesh:
                    self.camera.frame_object(gpu_mesh.bounds_min, gpu_mesh.bounds_max)
            self.update()
        elif event.key() == Qt.Key.Key_G:
            # Toggle grid (TODO)
            pass
        elif event.key() == Qt.Key.Key_D and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.dump_runtime_dispatches()

    def _update_animation(self):
        """Update animation (called by timer)."""
        if not self.animation_controller or not self.skeletal_animator:
            return

        # Calculate delta time
        current_time = time.time()
        delta_time = current_time - self.last_frame_time
        self.last_frame_time = current_time

        # Update animation controller
        self.animation_controller.update(delta_time)

        # Get current pose
        pose = self.animation_controller.get_current_pose()

        # Apply pose to skeleton
        if pose:
            self.skeletal_animator.apply_pose(pose)

        # Emit frame update for timeline
        self.frame_updated.emit(self.animation_controller.current_frame)

        # Trigger redraw if playing
        if self.animation_controller.is_playing():
            self.update()

    def _update_fps(self):
        """Update FPS counter."""
        fps = self.frame_count
        self.frame_count = 0
        self.fps_updated.emit(fps)

    def cleanup(self):
        """Clean up OpenGL resources."""
        if self.mesh_renderer:
            self.mesh_renderer.cleanup()
        if self.texture_manager:
            self.texture_manager.cleanup()
        if self.shader_manager:
            self.shader_manager.cleanup()
