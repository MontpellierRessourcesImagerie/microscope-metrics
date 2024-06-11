import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from microscopemetrics_schema import datamodel as mm_schema
from scipy import ndimage
from skimage.filters import gaussian

from microscopemetrics import SaturationError
from microscopemetrics.samples import psf_beads
from microscopemetrics.strategies import strategies as st_mm


@given(
    # shift_z=st.floats(min_value=0.1, max_value=0.49),
    # shift_y=st.floats(min_value=0.1, max_value=0.49),
    # shift_x=st.floats(min_value=0.1, max_value=0.49),
    shift_z=st.just(3),
    shift_y=st.just(3),
    shift_x=st.just(3),
)
def test_calculate_shifts(shift_z, shift_y, shift_x):
    shifted_array = np.zeros((61, 21, 21), dtype=np.float32)
    shifted_array[30, 10, 10] = 10
    shifted_array = gaussian(shifted_array, sigma=1.5, preserve_range=True)
    shifted_array = ndimage.shift(
        shifted_array, (shift_z, shift_y, shift_x), mode="nearest", order=1
    )
    calculated_shifts = psf_beads._calculate_shift(shifted_array)

    assert np.isclose(calculated_shifts[0], shift_z, atol=0.01)


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
