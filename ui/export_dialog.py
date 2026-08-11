"""
Export Dialog - UI for exporting meshes to various formats.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFileDialog, QLineEdit, QCheckBox, QGroupBox,
    QMessageBox, QProgressDialog
)
from PyQt6.QtCore import Qt
from pathlib import Path
from typing import Optional

from export.obj_exporter import OBJExporter
from export.gltf_exporter import GLTFExporter


class ExportDialog(QDialog):
    """
    Dialog for exporting meshes to OBJ or GLTF formats.
    """

    def __init__(self, viewport, asset_manager, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.asset_manager = asset_manager

        self.setWindowTitle("Export Mesh")
        self.setModal(True)
        self.resize(500, 300)

        self._create_ui()

    def _create_ui(self):
        """Create export dialog UI."""
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # Format selection
        format_group = QGroupBox("Export Format")
        format_layout = QVBoxLayout()

        self.format_combo = QComboBox()
        self.format_combo.addItem("Wavefront OBJ (.obj)", "obj")
        self.format_combo.addItem("GLTF 2.0 (.gltf)", "gltf")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_layout.addWidget(self.format_combo)

        self.format_info = QLabel("OBJ: Static mesh export with texture support")
        self.format_info.setWordWrap(True)
        self.format_info.setStyleSheet("color: #888; font-size: 11px;")
        format_layout.addWidget(self.format_info)

        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        # Options
        options_group = QGroupBox("Export Options")
        options_layout = QVBoxLayout()

        # Bake animation checkbox
        self.bake_animation_checkbox = QCheckBox("Bake current animation pose")
        self.bake_animation_checkbox.setToolTip("Apply current skeleton pose to mesh vertices")
        self.bake_animation_checkbox.setEnabled(False)  # Only enabled if animation loaded
        options_layout.addWidget(self.bake_animation_checkbox)

        # Include texture checkbox
        self.include_texture_checkbox = QCheckBox("Include texture reference")
        self.include_texture_checkbox.setChecked(True)
        self.include_texture_checkbox.setToolTip("Reference texture file in exported material")
        options_layout.addWidget(self.include_texture_checkbox)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Output path
        path_group = QGroupBox("Output File")
        path_layout = QHBoxLayout()

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose export location...")
        path_layout.addWidget(self.path_edit)

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_output_path)
        path_layout.addWidget(browse_button)

        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # Buttons
        layout.addStretch()
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        export_button = QPushButton("Export")
        export_button.setDefault(True)
        export_button.clicked.connect(self._on_export)
        button_layout.addWidget(export_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Update UI based on current viewport state
        self._update_ui_state()

    def _update_ui_state(self):
        """Update UI based on current mesh/animation state."""
        # Enable animation baking if skeleton is loaded
        has_animation = (self.viewport.skeletal_animator is not None and
                        self.viewport.animation_controller is not None)
        self.bake_animation_checkbox.setEnabled(has_animation)

        if has_animation:
            current_frame = int(self.viewport.animation_controller.current_frame)
            self.bake_animation_checkbox.setText(f"Bake current animation pose (frame {current_frame})")

    def _on_format_changed(self, index):
        """Handle format selection change."""
        format_type = self.format_combo.currentData()

        if format_type == "obj":
            self.format_info.setText("OBJ: Static mesh export with texture support. Compatible with most 3D software.")
        elif format_type == "gltf":
            self.format_info.setText("GLTF 2.0: Modern 3D format with animation support. Best for game engines.")

    def _browse_output_path(self):
        """Open file dialog to choose output path."""
        format_type = self.format_combo.currentData()

        if format_type == "obj":
            file_filter = "Wavefront OBJ (*.obj)"
            default_ext = ".obj"
        else:
            file_filter = "GLTF 2.0 (*.gltf)"
            default_ext = ".gltf"

        # Suggest filename based on current mesh ID
        mesh_id = self.viewport.current_mesh_id
        default_name = f"mesh_{mesh_id}{default_ext}" if mesh_id else f"export{default_ext}"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Mesh",
            default_name,
            file_filter
        )

        if file_path:
            self.path_edit.setText(file_path)

    def _on_export(self):
        """Handle export button click."""
        # Validate inputs
        if not self.viewport.current_mesh_id:
            QMessageBox.warning(self, "No Mesh Loaded", "Please load a mesh before exporting.")
            return

        output_path = self.path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "No Output Path", "Please choose an output file location.")
            return

        # Get export options
        format_type = self.format_combo.currentData()
        bake_animation = self.bake_animation_checkbox.isChecked()
        include_texture = self.include_texture_checkbox.isChecked()

        # Get mesh
        mesh = self.asset_manager.load_mesh(self.viewport.current_mesh_id)
        if not mesh:
            QMessageBox.critical(self, "Export Error", "Failed to load mesh data.")
            return

        # Materialise the texture next to the export; it lives inside
        # Textures.cache, so the exporters have no file to reference otherwise.
        texture_path = None
        if include_texture and self.viewport.current_texture_id:
            texture_id = self.viewport.current_texture_id
            texture_path = self.asset_manager.save_texture_image(
                texture_id,
                str(Path(output_path).parent / f"texture_{texture_id}.png"),
            )

        # Create progress dialog
        progress = QProgressDialog("Exporting mesh...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # Export
        try:
            success = False
            mesh_name = f"mesh_{self.viewport.current_mesh_id}"

            if format_type == "obj":
                if bake_animation and self.viewport.skeletal_animator:
                    # Export with baked animation
                    success = OBJExporter.export_current_pose(
                        mesh,
                        self.viewport.skeletal_animator,
                        output_path,
                        texture_path,
                        mesh_name
                    )
                else:
                    # Export static mesh
                    success = OBJExporter.export_mesh(
                        mesh,
                        output_path,
                        texture_path,
                        mesh_name
                    )

            elif format_type == "gltf":
                if bake_animation and self.viewport.skeletal_animator and self.viewport.animation_controller:
                    # Export with animation
                    skeleton = self.asset_manager.load_skeleton(self.viewport.current_mesh_id)
                    motion = self.asset_manager.load_motion(self.viewport.current_mesh_id)
                    success = GLTFExporter.export_animated_mesh(
                        mesh,
                        skeleton,
                        motion,
                        output_path,
                        texture_path,
                        mesh_name
                    )
                else:
                    # Export static mesh
                    success = GLTFExporter.export_static_mesh(
                        mesh,
                        output_path,
                        texture_path,
                        mesh_name
                    )

            progress.setValue(1)

            if success:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Mesh exported successfully to:\n{output_path}"
                )
                self.accept()
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Export failed. Check console for details."
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Export failed with error:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()

        finally:
            progress.close()
