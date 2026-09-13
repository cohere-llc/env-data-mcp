"""EIA: a point + radius → the states whose bounding box the circle touches (one or two), never the
nation."""

from env_data_mcp.sources.eia._states import STATE_BBOX, states_near


def test_states_near_points():
    near = states_near(
        35.97, -84.31, 50
    )  # the FRC: Tennessee (+ the KY/NC boxes the circle grazes)
    assert "TN" in near and len(near) <= 3 and "TX" not in near
    wide = states_near(35.97, -84.31, 150)
    assert "TN" in wide and "KY" in wide
    assert states_near(38.9, -77.0, 20) == ["DC", "MD", "VA"]  # Washington
    assert states_near(48.0, 2.0, 50) == []  # Paris: outside the US → empty
    assert len(STATE_BBOX) == 51
