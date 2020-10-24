import pytest
from os import path


from microscopemetrics.samples import argolight
import numpy as np


@pytest.fixture
def argolight_b():
    temp_dir = path.abspath('/Users/julio/PycharmProjects/microscope-metrics/tests/data/')
    file_name = '201702_RI510_Argolight-1-1_010_SIR_ALX.npy'
    file_url = 'http://dev.mri.cnrs.fr/attachments/download/2290/201702_RI510_Argolight-1-1_010_SIR_ALX.npy'
    try:
        data = np.load(path.join(temp_dir, file_name))
    except FileNotFoundError as e:
        repos = np.DataSource(temp_dir)
        repos.open(file_url)


    analysis = argolight.ArgolightAnalysis()
    analysis.input.data = {'argolight_b': data}
    analysis.set_metadata('spots_distance', 5)
    analysis.set_metadata('pixel_size', (.125, .39, .39))

    return analysis


@pytest.fixture
def argolight_e_horizontal():
    temp_dir = path.abspath('/Users/julio/PycharmProjects/microscope-metrics/tests/data/')
    file_name = '201702_RI510_Argolight-1-1_004_SIR_ALX.npy'
    file_url = 'http://dev.mri.cnrs.fr/attachments/download/2291/201702_RI510_Argolight-1-1_004_SIR_ALX.npy'
    try:
        data = np.load(path.join(temp_dir, file_name))
    except FileNotFoundError as e:
        repos = np.DataSource(temp_dir)
        repos.open(file_url)


    analysis = argolight.ArgolightAnalysis()
    analysis.input.data = {'argolight_e_horizontal': data}
    analysis.set_metadata('spots_distance', 5)
    analysis.set_metadata('pixel_size', (.125, .39, .39))

    return analysis


@pytest.fixture
def argolight_e_vertical():
    temp_dir = path.abspath('/Users/julio/PycharmProjects/microscope-metrics/tests/data/')
    file_name = '201702_RI510_Argolight-1-1_005_SIR_ALX.npy'
    file_url = 'http://dev.mri.cnrs.fr/attachments/download/2292/201702_RI510_Argolight-1-1_005_SIR_ALX.npy'
    try:
        data = np.load(path.join(temp_dir, file_name))
    except FileNotFoundError as e:
        repos = np.DataSource(temp_dir)
        repos.open(file_url)


    analysis = argolight.ArgolightAnalysis()
    analysis.input.data = {'argolight_e_vertical': data}
    analysis.set_metadata('spots_distance', 5)
    analysis.set_metadata('pixel_size', (.125, .39, .39))

    return analysis


def test_run_argolight_b(argolight_b):
    output = argolight_b.analyze_spots()
    assert output


def test_run_argolight_e_horizontal(argolight_e_horizontal):
    output = argolight_e_horizontal.analyze_vertical_resolution()
    assert output


def test_run_argolight_e_vertical(argolight_e_vertical):
    output = argolight_e_vertical.analyze_horizontal_resolution()
    assert output


