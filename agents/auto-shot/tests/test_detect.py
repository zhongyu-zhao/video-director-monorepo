from __future__ import annotations

import unittest

from auto_shot.detect import _parse_cuts


class ParseCutsTest(unittest.TestCase):
    def test_parses_ffmpeg_metadata_blocks(self) -> None:
        stderr = """[Parsed_metadata_1] frame:0 pts:51200 pts_time:4
[Parsed_metadata_1] lavfi.scene_score=0.400000
[Parsed_metadata_1] frame:1 pts:76800 pts_time:6
[Parsed_metadata_1] lavfi.scene_score=1.000000
"""

        cuts = _parse_cuts(stderr)

        self.assertEqual([(cut.time, cut.score) for cut in cuts], [(4.0, 0.4), (6.0, 1.0)])

    def test_handles_time_and_score_on_the_same_line(self) -> None:
        cuts = _parse_cuts("[metadata] pts_time:2 lavfi.scene_score=0.75")

        self.assertEqual([(cut.time, cut.score) for cut in cuts], [(2.0, 0.75)])


if __name__ == "__main__":
    unittest.main()
