import random

import numpy as np
import pytest
from hypothesis import given, settings, reproduce_failure
from hypothesis import strategies as st
from microscopemetrics_schema import datamodel as mm_schema
from scipy import ndimage
from skimage.filters import gaussian
from skimage.util import random_noise as skimage_random_noise
from skimage.exposure import rescale_intensity as skimage_rescale_intensity

from microscopemetrics import SaturationError
from microscopemetrics.samples import psf_beads
from microscopemetrics.strategies import strategies as st_mm
from microscopemetrics.utilities.utilities import fit_gaussian


@given(
    shifts=st.lists(
        st.tuples(
            st.floats(min_value=.1, max_value=.49),
            st.floats(min_value=.1, max_value=.49),
            st.floats(min_value=.1, max_value=.49),
        )
        , min_size=3, max_size=10),
    signal=st.integers(min_value=10, max_value=1000),
    sigma_axial=st.floats(min_value=1.0, max_value=3.0),
    sigma_lateral=st.floats(min_value=1.0, max_value=2.0),
)
def test_average_beads(shifts, signal, sigma_axial, sigma_lateral):
    beads = []
    ref_bead = np.zeros((61, 21, 21), dtype=np.int16)
    ref_bead[30, 10, 10] = signal
    ref_bead = gaussian(ref_bead, sigma=(sigma_axial, sigma_lateral, sigma_lateral), preserve_range=True)
    ref_bead = skimage_random_noise(ref_bead, mode="poisson", clip=False)

    for i, shift in enumerate(shifts):
        bead = np.zeros((61, 21, 21), dtype=np.int16)
        bead[30, 10, 10] = signal
        bead = ndimage.shift(
            bead,
            shift,
            mode="nearest",
            order=1
        )
        bead = gaussian(bead, sigma=(sigma_axial, sigma_lateral, sigma_lateral), preserve_range=True)
        bead = skimage_random_noise(bead, mode="poisson", clip=False)
        beads.append(bead)

    averaged_bead = psf_beads._average_beads(beads)

    averaged_profile_z = np.squeeze(averaged_bead[:, 10, 10])
    averaged_profile_y = np.squeeze(averaged_bead[30, :, 10])
    averaged_profile_x = np.squeeze(averaged_bead[30, :, 10])

    averaged_sigma_z = fit_gaussian(averaged_profile_z)[3][3]
    averaged_sigma_y = fit_gaussian(averaged_profile_y)[3][3]
    averaged_sigma_x = fit_gaussian(averaged_profile_x)[3][3]

    ref_sigma_z = fit_gaussian(np.squeeze(ref_bead[:, 10, 10]))[3][3]
    ref_sigma_y = fit_gaussian(np.squeeze(ref_bead[30, :, 10]))[3][3]
    ref_sigma_x = fit_gaussian(np.squeeze(ref_bead[30, :, 10]))[3][3]

    assert averaged_sigma_z == pytest.approx(ref_sigma_z, abs=0.1)
    assert averaged_sigma_y == pytest.approx(ref_sigma_y, abs=0.1)
    assert averaged_sigma_x == pytest.approx(ref_sigma_x, abs=0.1)

    # We assume that the average is better than the individual beads
    assert averaged_sigma_z < ref_sigma_z
    assert averaged_sigma_y < ref_sigma_y
    assert averaged_sigma_x < ref_sigma_x

    assert averaged_sigma_z > sigma_axial
    assert averaged_sigma_y > sigma_lateral
    assert averaged_sigma_x > sigma_lateral


@given(st_mm.st_psf_beads_dataset())
@settings(max_examples=1)
def test_psf_beads_analysis_instantiation(dataset):
    dataset = dataset["unprocessed_dataset"]
    assert isinstance(dataset, mm_schema.PSFBeadsDataset)
    assert dataset.name
    assert dataset.description
    assert dataset.microscope
    assert dataset.input


@given(st_mm.st_psf_beads_dataset())
@settings(max_examples=1)
def test_psf_beads_analysis_run(dataset):
    dataset = dataset["unprocessed_dataset"]
    assert not dataset.processed
    assert psf_beads.analyse_psf_beads(dataset)
    assert dataset.processed


@given(
    st_mm.st_psf_beads_dataset(
        test_data=st_mm.st_psf_beads_test_data(
            z_image_shape=st.just(61),
            y_image_shape=st.just(512),
            x_image_shape=st.just(512),
            c_image_shape=st.just(3),
            nr_valid_beads=st.integers(min_value=0, max_value=10),
            nr_edge_beads=st.just(0),
            nr_out_of_focus_beads=st.just(0),
            nr_clustering_beads=st.just(0),
        )
    )
)
def test_psf_beads_analysis_nr_valid_beads(dataset):
    psf_beads_dataset = dataset["unprocessed_dataset"]
    expected_output = dataset["expected_output"]
    psf_beads.analyse_psf_beads(psf_beads_dataset)

    expected = sum(len(im_vbp) for im_vbp in expected_output["valid_bead_positions"])

    for measured in psf_beads_dataset.output.key_measurements.considered_valid_count:
        assert measured == expected


@given(
    st_mm.st_psf_beads_dataset(
        test_data=st_mm.st_psf_beads_test_data(
            z_image_shape=st.just(61),
            y_image_shape=st.just(512),
            x_image_shape=st.just(512),
            c_image_shape=st.just(3),
            nr_valid_beads=st.just(0),
            nr_edge_beads=st.integers(min_value=0, max_value=5),
            nr_out_of_focus_beads=st.just(0),
            nr_clustering_beads=st.just(0),
        )
    )
)
def test_psf_beads_analysis_nr_lateral_edge_beads(dataset):
    psf_beads_dataset = dataset["unprocessed_dataset"]
    expected_output = dataset["expected_output"]
    psf_beads.analyse_psf_beads(psf_beads_dataset)

    expected = sum(len(im_ebp) for im_ebp in expected_output["edge_bead_positions"])

    for measured in psf_beads_dataset.output.key_measurements.considered_lateral_edge_count:
        assert measured == expected


@given(
    st_mm.st_psf_beads_dataset(
        test_data=st_mm.st_psf_beads_test_data(
            z_image_shape=st.just(71),
            y_image_shape=st.just(512),
            x_image_shape=st.just(512),
            c_image_shape=st.just(3),
            nr_valid_beads=st.just(0),
            nr_edge_beads=st.just(0),
            nr_out_of_focus_beads=st.integers(min_value=0, max_value=5),
            nr_clustering_beads=st.just(0),
        )
    )
)
def test_psf_beads_analysis_nr_axial_edge_beads(dataset):
    psf_beads_dataset = dataset["unprocessed_dataset"]
    expected_output = dataset["expected_output"]
    psf_beads.analyse_psf_beads(psf_beads_dataset)

    expected = sum(len(im_ofbp) for im_ofbp in expected_output["out_of_focus_bead_positions"])

    for measured in psf_beads_dataset.output.key_measurements.considered_axial_edge_count:
        assert measured == expected


@given(
    st_mm.st_psf_beads_dataset(
        test_data=st_mm.st_psf_beads_test_data(
            z_image_shape=st.just(61),
            y_image_shape=st.just(512),
            x_image_shape=st.just(512),
            c_image_shape=st.just(3),
            nr_valid_beads=st.just(12),
            nr_edge_beads=st.just(0),
            nr_out_of_focus_beads=st.just(0),
            nr_clustering_beads=st.integers(min_value=1, max_value=2),
            # To find the outliers we need to ensure that all images have the same intensity related parameters
            dtype=st.just(np.uint16),
            do_noise=st.just(True),
            signal=st.just(100.0),
            target_min_intensity=st.just(0.1),
            target_max_intensity=st.just(0.5),
            sigma_z=st.just(2),
            sigma_y=st.just(1.5),
            sigma_x=st.just(1.5),
        )
    )
)
@settings(deadline=200000)
def test_psf_beads_analysis_nr_intensity_outliers_beads(dataset):
    psf_beads_dataset = dataset["unprocessed_dataset"]
    expected_output = dataset["expected_output"]
    psf_beads.analyse_psf_beads(psf_beads_dataset)

    expected = sum(len(img_cbp) for img_cbp in expected_output["clustering_bead_positions"])

    for measured in psf_beads_dataset.output.key_measurements.considered_intensity_outlier_count:
        assert measured == expected
