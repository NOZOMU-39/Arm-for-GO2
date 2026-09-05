"""RegistryStore 单测: upsert/remove/set_limits/rev/校验(契约 SetRegistry/SetLimits)"""
import pytest

from arm_controller.registry import RegistryStore, load_list

REAL = [
    {"id": 1, "name": "基座", "proto": "V3", "gear": 6, "dir": -1, "E0": -92.97,
     "limMinDeg": -91, "limMaxDeg": 91},
    {"id": 2, "name": "大臂", "proto": "V43", "gear": 1, "dir": 1,
     "limMinDeg": -40, "limMaxDeg": 94.5},
    {"id": 3, "name": "小臂", "proto": "V43", "gear": 1, "dir": 1,
     "limMinDeg": -170, "limMaxDeg": 80},
    {"id": 4, "name": "腕", "proto": "V44", "gear": 1, "dir": 1,
     "limMinDeg": -124, "limMaxDeg": 85},
    {"id": 5, "name": "末端", "proto": "V44", "gear": 1, "dir": 1,
     "limMinDeg": -120, "limMaxDeg": 120},
]


def _store():
    return RegistryStore(load_list(REAL))


def test_init_rev_zero_and_get():
    st = _store()
    assert st.rev == 0 and len(st.get_all()) == 5
    assert st.get(3)["name"] == "小臂"
    assert st.get(99) is None


def test_upsert_new_motor_increments_rev():
    st = _store()
    m = st.upsert({"id": 9, "proto": "V3"})
    assert st.rev == 1 and st.get(9)["gear"] == 1.0
    assert len(st.get_all()) == 6


def test_upsert_overwrite_same_id():
    st = _store()
    st.upsert({"id": 5, "proto": "V44", "gear": 2, "dir": -1, "limMinDeg": -90, "limMaxDeg": 90})
    m = st.get(5)
    assert m["gear"] == 2.0 and m["dir"] == -1 and m["limMaxDeg"] == 90.0
    assert len(st.get_all()) == 5 and st.rev == 1


def test_upsert_bad_limits_rejected():
    st = _store()
    with pytest.raises(ValueError, match="限幅下限"):
        st.upsert({"id": 7, "proto": "V3", "limMinDeg": 10, "limMaxDeg": -10})
    assert st.rev == 0


def test_upsert_bad_proto_rejected():
    with pytest.raises(ValueError):
        _store().upsert({"id": 7, "proto": "V5"})


def test_remove_and_missing():
    st = _store()
    assert st.remove(4) is True and st.rev == 1
    assert st.get(4) is None
    assert st.remove(4) is False and st.rev == 1


def test_set_limits_replace_all():
    st = _store()
    m = st.set_limits(5, lim_min_deg=-30, lim_max_deg=30, lim_max_spd=100)
    assert m["limMinDeg"] == -30.0 and m["limMaxDeg"] == 30.0
    assert m["limMaxSpd"] == 100.0 and m["limMaxIq"] is None
    # 清除某项(None)
    st.set_limits(5, lim_min_deg=None, lim_max_deg=None, lim_max_spd=100)
    m2 = st.get(5)
    assert m2["limMinDeg"] is None and m2["limMaxDeg"] is None
    assert st.rev == 2


def test_set_limits_min_ge_max_rejected():
    st = _store()
    with pytest.raises(ValueError):
        st.set_limits(5, lim_min_deg=50, lim_max_deg=10)


def test_set_limits_unknown_motor():
    with pytest.raises(ValueError, match="不在注册表"):
        _store().set_limits(99, lim_min_deg=0, lim_max_deg=10)


def test_nan_clears_limit():
    """NaN 语义 = 未设(对应消息契约 float32 NaN)"""
    st = _store()
    st.set_limits(5, lim_min_deg=float("nan"), lim_max_deg=float("nan"))
    m = st.get(5)
    assert m["limMinDeg"] is None and m["limMaxDeg"] is None
