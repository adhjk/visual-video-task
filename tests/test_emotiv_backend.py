from __future__ import annotations

import numpy as np
import pytest

from video_eeg.devices.emotiv.buffer import EEGBuffer
from video_eeg.devices.emotiv.cortex_client import select_headset
from video_eeg.devices.emotiv.errors import CortexProtocolError, EmotivConfigurationError, EmotivError
from video_eeg.devices.emotiv.profiles import resolve_profile
from video_eeg.devices.emotiv.stream_parser import StreamParser
from video_eeg.devices.base import AcquirerMetadata
from video_eeg.storage.session_recorder import SessionRecorder


def test_parser_uses_subscribe_cols_and_preserves_auxiliary_fields() -> None:
    parser = StreamParser(["COUNTER", "AF3", "INTERPOLATED", "T7", "RAW_CQ", "MARKERS"])
    parsed = parser.parse(
        {
            "eeg": [7, 1.25, 0, -2.5, 813, [{"label": "video_on"}]],
            "time": 1234.5,
        }
    )
    assert parser.channel_names == ("AF3", "T7")
    assert parser.auxiliary_names == ("COUNTER", "INTERPOLATED", "RAW_CQ", "MARKERS")
    np.testing.assert_array_equal(parsed.eeg, [1.25, -2.5])
    assert parsed.timestamp == 1234.5
    assert parsed.auxiliary["COUNTER"] == 7
    assert parsed.auxiliary["MARKERS"] == [{"label": "video_on"}]


def test_parser_rejects_packet_shape_and_non_finite_eeg_at_source() -> None:
    parser = StreamParser(["AF3", "AF4"])
    with pytest.raises(CortexProtocolError, match="length"):
        parser.parse({"eeg": [1.0], "time": 1.0})
    with pytest.raises(CortexProtocolError, match="non-finite"):
        parser.parse({"eeg": [1.0, float("nan")], "time": 1.0})


def test_buffer_returns_cortex_timestamps_without_replacement() -> None:
    buffer = EEGBuffer(channels=2, capacity=2)
    buffer.append(np.asarray([1.0, 2.0]), 100.25)
    buffer.append(np.asarray([3.0, 4.0]), 100.5)
    samples, timestamps = buffer.read_new()
    np.testing.assert_array_equal(samples, [[1.0, 3.0], [2.0, 4.0]])
    np.testing.assert_array_equal(timestamps, [100.25, 100.5])
    empty, empty_timestamps = buffer.read_new()
    assert empty.shape == (2, 0)
    assert empty_timestamps.shape == (0,)


def test_session_recorder_persists_original_timestamps(tmp_path) -> None:
    class Source:
        metadata = AcquirerMetadata(name="emotiv", sfreq=128.0, n_channels=2)

        def __init__(self) -> None:
            self.read = False

        def get_new_samples(self):
            if self.read:
                return np.empty((2, 0)), np.empty(0)
            self.read = True
            return np.asarray([[1.0, 2.0], [3.0, 4.0]]), np.asarray([987.125, 987.1328125])

    recorder = SessionRecorder(Source(), sfreq=128.0, n_channels=2)
    recorder.start_spooling(tmp_path)
    recorder.pull()
    recorder.export(tmp_path, metadata={}, pull_final=False)
    np.testing.assert_array_equal(
        np.load(tmp_path / "continuous_timestamps.npy"), [987.125, 987.1328125]
    )


def test_auto_headset_selection_never_guesses_between_devices() -> None:
    with pytest.raises(EmotivError, match="exactly one"):
        select_headset([{"id": "INSIGHT-1"}, {"id": "EPOCPLUS-2"}], "auto")


def test_explicit_model_mismatch_fails() -> None:
    with pytest.raises(EmotivConfigurationError, match="does not match"):
        resolve_profile("epoc_x", {"id": "INSIGHT-123"})


@pytest.mark.parametrize(
    ("headset_id", "model", "requires_mapping"),
    [
        ("INSIGHT-123", "insight", False),
        ("EPOCPLUS-123", "epoc_x", False),
        ("EPOCFLEX-123", "epoc_flex", True),
        ("FLEX-123", "flex_2", True),
    ],
)
def test_supported_profiles(headset_id: str, model: str, requires_mapping: bool) -> None:
    profile = resolve_profile("auto", {"id": headset_id})
    assert profile.name == model
    assert profile.requires_mapping is requires_mapping
