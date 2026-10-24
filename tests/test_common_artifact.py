import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common


TIMESTAMP_END = "2026-10-23T23:35:33.123456+00:00"
DATE_PREFIX_LENGTH = len("2026-10-23_")


def get_artifact(task_id="Example-Task", agent="example-agent", timestamp_end=TIMESTAMP_END):
    return {
        "session_id": "session-a",
        "task_id": task_id,
        "agent": agent,
        "timestamp_end": timestamp_end,
    }


class WriteArtifact(unittest.TestCase):
    def setUp(self):
        artifacts_dir = tempfile.TemporaryDirectory()
        self.addCleanup(artifacts_dir.cleanup)
        self.artifacts_dir = Path(artifacts_dir.name)
        artifacts_dir_patch = mock.patch.object(_common, "ARTIFACTS_DIR", self.artifacts_dir)
        artifacts_dir_patch.start()
        self.addCleanup(artifacts_dir_patch.stop)

    def write_and_get_filename_without_date(self, artifact):
        artifact_path = _common.write_artifact(artifact)
        return artifact_path.name[DATE_PREFIX_LENGTH:]

    def test_colon_in_agent_name_becomes_underscore(self):
        artifact = get_artifact(agent="pr-review-toolkit:code-reviewer")

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "Example-Task_pr-review-toolkit_code-reviewer_20261023T233533.json")

    def test_spaces_slashes_and_non_ascii_letters_in_agent_become_underscores(self):
        artifact = get_artifact(agent="a b/c\\dé")

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "Example-Task_a_b_c_d__20261023T233533.json")

    def test_path_and_reserved_characters_in_task_id_become_underscores(self):
        artifact = get_artifact(task_id='a b/c\\d<e>f:g"h|i?j*k\x01l')

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "a_b_c_d_e_f_g_h_i_j_k_l_example-agent_20261023T233533.json")

    def test_non_ascii_letters_in_task_id_become_underscores(self):
        artifact = get_artifact(task_id="café日本")

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "caf____example-agent_20261023T233533.json")

    def test_letters_digits_dots_underscores_and_hyphens_are_kept(self):
        artifact = get_artifact(task_id="Example-Task_1.2", agent="Agent.B-3_c")

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "Example-Task_1.2_Agent.B-3_c_20261023T233533.json")

    def test_task_id_is_cut_to_80_characters(self):
        artifact = get_artifact(task_id="t" * 100)

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "t" * 80 + "_example-agent_20261023T233533.json")

    def test_agent_is_cut_to_60_characters(self):
        artifact = get_artifact(agent="a" * 100)

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "Example-Task_" + "a" * 60 + "_20261023T233533.json")

    def test_unsafe_timestamp_suffix_characters_become_underscores_within_15_characters(self):
        artifact = get_artifact(timestamp_end="2026/10/23 23 33 00")

        filename = self.write_and_get_filename_without_date(artifact)

        self.assertEqual(filename, "Example-Task_example-agent_2026_10_23_23_3.json")

    def test_written_file_holds_the_artifact_with_original_task_id_and_agent(self):
        artifact = get_artifact(task_id="Review: slot search", agent="pr-review-toolkit:code-reviewer")

        artifact_path = _common.write_artifact(artifact)

        written_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(written_artifact, get_artifact(task_id="Review: slot search", agent="pr-review-toolkit:code-reviewer"))

    def test_returned_path_is_the_written_file_inside_artifacts_dir(self):
        artifact = get_artifact()

        artifact_path = _common.write_artifact(artifact)

        self.assertEqual(list(self.artifacts_dir.iterdir()), [artifact_path])


if __name__ == "__main__":
    unittest.main()
