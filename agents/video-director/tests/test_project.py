from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from video_director.models import Asset
from video_director.project import (
    ProjectError,
    add_asset,
    add_clip,
    create_project,
    load_project,
    resolve_asset_path,
    save_project,
)

from tests.support import ffmpeg_available, make_solid_clip


class ProjectStorageTest(unittest.TestCase):
    def test_init_creates_layout_and_first_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = create_project(root, "demo", fps=25.0, width=320, height=180, project_id="proj-1")

            self.assertEqual(project.revision, 1)
            self.assertTrue((root / "project.json").is_file())
            self.assertTrue((root / "history" / "project-r001.json").is_file())
            for name in ("artifacts", "assets", "renders", "history"):
                self.assertTrue((root / name).is_dir())

            loaded = load_project(root)
            self.assertEqual(loaded.to_dict(), project.to_dict())

    def test_init_refuses_to_overwrite_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_project(root, "demo")
            with self.assertRaises(ProjectError):
                create_project(root, "again")

    def test_save_increments_revision_and_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root, "demo")
            save_project(project, root)
            save_project(project, root)

            self.assertEqual(project.revision, 3)
            self.assertTrue((root / "history" / "project-r002.json").is_file())
            self.assertTrue((root / "history" / "project-r003.json").is_file())
            self.assertEqual(load_project(root).revision, 3)

    def test_load_reports_missing_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ProjectError):
            load_project(Path(directory) / "missing")

    @unittest.skipUnless(ffmpeg_available(), "ffmpeg/ffprobe not installed")
    def test_add_asset_copies_and_probes_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            project = create_project(root, "demo", fps=25.0, width=320, height=180)
            source = make_solid_clip(Path(directory) / "source.mp4")

            asset = add_asset(project, root, source)
            save_project(project, root)

            self.assertEqual(asset.id, "A001")
            self.assertEqual(asset.path, "assets/A001.mp4")
            self.assertEqual(asset.kind, "video")
            self.assertAlmostEqual(asset.duration or 0.0, 2.0, places=1)
            self.assertTrue((root / asset.path).is_file())

    def test_add_clip_appends_to_end_of_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root, "demo")
            project.assets.append(Asset(id="A001", path="assets/a.mp4", duration=4.0))

            first = add_clip(project, "A001", 0.0, 2.0)
            second = add_clip(project, "A001", 2.0, 4.0)

            self.assertEqual((first.id, first.start), ("C001", 0.0))
            self.assertEqual((second.id, second.start), ("C002", 2.0))

    def test_add_clip_rejects_invalid_ranges_and_unknown_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root, "demo")
            project.assets.append(Asset(id="A001", path="assets/a.mp4", duration=2.0))

            with self.assertRaises(ProjectError):
                add_clip(project, "A999", 0.0, 1.0)
            with self.assertRaises(ProjectError):
                add_clip(project, "A001", 1.0, 1.0)
            with self.assertRaises(ProjectError):
                add_clip(project, "A001", 0.0, 3.0)

    def test_asset_paths_must_stay_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            create_project(root, "demo")

            with self.assertRaises(ProjectError):
                resolve_asset_path(root, Asset(id="A001", path="../escape.mp4"))
            with self.assertRaises(ProjectError):
                resolve_asset_path(root, Asset(id="A001", path=str(Path(directory) / "abs.mp4")))


if __name__ == "__main__":
    unittest.main()
