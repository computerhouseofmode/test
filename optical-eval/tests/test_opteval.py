import json
import math
from pathlib import Path

import numpy as np
import pytest

from opteval import Evaluator, OpticalSystem, Surface, first_order, focus_paraxial, seidel
from opteval import analysis as an
from opteval.glass import FRAUNHOFER, abbe_number, refractive_index
from opteval.optimize import optimize

EX = Path(__file__).resolve().parents[1] / "examples"
WD = FRAUNHOFER["d"]


def singlet(epd=4.0, fields=(0.0, 1.0)):
    s = OpticalSystem(
        [Surface(thickness=math.inf), Surface(radius=50, thickness=4, material="N-BK7", stop=True),
         Surface(radius=-50, thickness=40), Surface()],
        wavelengths=[WD], primary=0, fields=list(fields), aperture_value=epd)
    focus_paraxial(s)
    return s


def ellipsoid():
    n = refractive_index("N-BK7", WD)
    s = OpticalSystem(
        [Surface(thickness=math.inf), Surface(radius=20, conic=-1 / n**2, thickness=10, material="N-BK7", stop=True),
         Surface()],
        wavelengths=[WD], primary=0, fields=[0.0], aperture_value=20)
    focus_paraxial(s)
    return s


@pytest.mark.parametrize("name,nd,vd", [
    ("N-BK7", 1.5168, 64.17), ("F2", 1.62004, 36.37), ("N-SK16", 1.62041, 60.32), ("SILICA", 1.45846, 67.82)])
def test_catalog_glass(name, nd, vd):
    assert refractive_index(name, WD) == pytest.approx(nd, abs=2e-5)
    assert abbe_number(name) == pytest.approx(vd, abs=0.05)


def test_model_glass():
    assert refractive_index("1.6:40", WD) == pytest.approx(1.6)
    assert abbe_number("1.6:40") == pytest.approx(40)


def test_thick_lens_efl():
    s = singlet()
    n = refractive_index("N-BK7", WD)
    c1, c2, t = 1 / 50, -1 / 50, 4
    phi = (n - 1) * (c1 - c2 + (n - 1) * t * c1 * c2 / n)
    assert first_order(s).efl == pytest.approx(1 / phi, rel=1e-12)


def test_small_aperture_rays_meet_paraxial_focus():
    s = singlet(epd=0.02)
    ev = Evaluator(s)
    r = ev.trace(0.0, [0.0, 0.0], [0.0, 1.0], WD)
    assert abs(r.P[1, 1]) < 1e-9


def test_cartesian_oval_is_perfect():
    s = ellipsoid()
    ev = Evaluator(s)
    assert seidel(s).totals()["SI"] == pytest.approx(0, abs=1e-12)
    assert an.wavefront(ev, 0.0).rms < 1e-6
    m = an.mtf(ev, 0.0)
    assert np.max(np.abs(m.tangential - m.diffraction_limit)) < 0.01
    assert an.psf(ev, 0.0).strehl == pytest.approx(1.0, abs=1e-6)


def test_seidel_matches_real_opd():
    """小口径・小画角では Seidel 波面係数と実光線の OPD が一致する。"""
    s = singlet()
    ev = Evaluator(s)
    w = seidel(s).wave_coefficients()
    W040, W131, W222, W220 = (w[k] for k in ("W040 (球面)", "W131 (コマ)", "W222 (非点)", "W220 (像面湾曲)"))
    assert ev.opd(0.0, [0.0], [1.0], WD)[0][0] == pytest.approx(W040, rel=0.01)
    t, _ = ev.opd(1.0, [0.0, 0.0], [1.0, -1.0], WD)
    assert (t[0] - t[1]) / 2 == pytest.approx(W131, rel=0.02)
    assert (t[0] + t[1]) / 2 == pytest.approx(W040 + W222 + W220, rel=0.02)
    sg, _ = ev.opd(1.0, [1.0], [0.0], WD)
    assert sg[0] == pytest.approx(W040 + W220, rel=0.02)


def test_cooke_triplet_first_order():
    s = OpticalSystem.load(EX / "cooke_triplet.json")
    fo = first_order(s)
    assert fo.efl == pytest.approx(50.02, abs=0.01)
    assert fo.fno == pytest.approx(5.0, abs=0.01)
    s2 = s.copy()
    focus_paraxial(s2)   # 近軸焦点面では y' = -f tanθ
    assert first_order(s2).image_height == pytest.approx(-fo.efl * math.tan(math.radians(20)), rel=1e-12)


def test_cooke_triplet_image_quality():
    s = OpticalSystem.load(EX / "cooke_triplet.json")
    ev = Evaluator(s)
    for f in s.fields:
        assert an.spot(ev, f).rms < 0.02          # 20 µm 以下
    # 像面湾曲: 軸上の焦点ずれ = 近軸像距離 - 実際の像面距離
    fc = an.field_curves(ev, n=3)
    shift = first_order(s).image_distance - s.surfaces[-2].thickness
    assert fc.tangential[s.primary][0] == pytest.approx(shift, abs=1e-4)
    assert fc.sagittal[s.primary][0] == pytest.approx(shift, abs=1e-4)


def test_psf_orientation_matches_rays():
    s = OpticalSystem.load(EX / "cooke_triplet.json")
    ev = Evaluator(s)
    p = an.psf(ev, 20.0)
    m = p.psf.shape[0]
    yy = np.arange(m)[:, None] - m // 2
    cy_psf = (yy * p.psf).sum() / p.psf.sum() * p.pixel
    sp = an.spot(ev, 20.0)
    assert np.sign(cy_psf) == np.sign(sp.centroid[1])


def test_vignetting_by_fixed_semi_diameter():
    s = singlet(epd=4.0)
    s.surfaces[1].semi_diameter = 1.0
    ev = Evaluator(s)
    r = ev.trace(0.0, [0.0, 0.0], [0.4, 0.8], WD)
    assert r.valid.tolist() == [True, False]


def test_json_roundtrip(tmp_path):
    s = OpticalSystem.load(EX / "cooke_triplet.json")
    p = tmp_path / "lens.json"
    s.save(p)
    s2 = OpticalSystem.load(p)
    assert json.loads(p.read_text()) == s2.to_dict()
    assert first_order(s2).efl == pytest.approx(first_order(s).efl)


def test_optimizer_reduces_merit():
    s = OpticalSystem.load(EX / "doublet_start.json")
    res = optimize(s)
    assert res.merit_history[-1] < 1e-3 * res.merit_history[0]
    assert first_order(res.system).efl == pytest.approx(100.0, abs=0.05)
    assert max(res.rms_spot_um) < 10


def test_finite_object_conjugate():
    # 有限物体: Newton の式 m = f / (z_obj - z_F) と実光線像高
    s = OpticalSystem(
        [Surface(thickness=100.0), Surface(radius=50, thickness=4, material="N-BK7", stop=True),
         Surface(radius=-50, thickness=100), Surface()],
        wavelengths=[WD], primary=0, fields=[0.0, 2.0], field_type="height",
        aperture_type="NAO", aperture_value=0.01)
    focus_paraxial(s)
    fo = first_order(s)
    assert fo.magnification == pytest.approx(fo.efl / (-100.0 - fo.ffl), rel=1e-10)
    ev = Evaluator(s)
    assert ev.chief(2.0).P[0, 1] == pytest.approx(fo.magnification * 2.0, rel=0.01)
