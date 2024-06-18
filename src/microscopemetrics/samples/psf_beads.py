from datetime import datetime

import microscopemetrics_schema.datamodel as mm_schema
import numpy as np
import pandas as pd
from scipy import ndimage, signal
from skimage.feature import peak_local_max
from skimage.filters import gaussian

from microscopemetrics import FittingError, SaturationError
from microscopemetrics.samples import df_to_table, logger, validate_requirements
from microscopemetrics.utilities.utilities import fit_airy, fit_gaussian, is_saturated


def _add_column_name_level(df: pd.DataFrame, level_name: str, level_value: str):
    if isinstance(df.columns, pd.MultiIndex):
        new_columns = pd.MultiIndex.from_tuples(
            [(level_value, *col) for col in df.columns],
            names=[level_name] + list(df.columns.names),
        )
    else:
        new_columns = pd.MultiIndex.from_tuples(
            [(level_value, col) for col in df.columns],
            names=[level_name, df.columns.name],
        )
    df.columns = new_columns


def _add_row_index_level(df: pd.DataFrame, level_name: str, level_value: str):
    if isinstance(df.index, pd.MultiIndex):
        new_index = pd.MultiIndex.from_tuples(
            [(level_value, *row) for row in df.index],
            names=[level_name] + list(df.index.names),
        )
    else:
        new_index = pd.MultiIndex.from_tuples(
            [(level_value, row) for row in df.index], names=[level_name, df.index.name]
        )
    df.index = new_index


def _concatenate_index_levels(index_names, index_values, pattern="{level_name}-{level_value}_"):
    concatenated_str = "".join(
        pattern.format(level_name=level_name, level_value=level_value)
        for level_name, level_value in zip(index_names, index_values)
    )

    return concatenated_str.rstrip("_")


def _average_beads(group: pd.DataFrame) -> np.ndarray:
    """
    Averages the beads in the list by first aligning them to the center of the image and then averaging them.
    """
    if len(group) < 2:
        logger.warning("Less than 2 beads to average. Skipping averaging.")
        return None
    logger.info(f"Averaging {len(group)} beads")

    aligned_beads = [
        ndimage.shift(row.beads, _find_bead_shifts(row.beads), mode="nearest", order=1)
        for row in group.itertuples()
        if row.considered_valid
    ]

    return pd.Series(
        {
            "average_bead": np.mean(aligned_beads, axis=0),
        }
    )


def _find_bead_shifts(data1, data2=None):
    """Cross-correlates two 2D or 3D arrays and returns the shifts.
    If a second array is not provided, a Gaussian is used as a reference."""
    if data2 is None:
        data2 = np.zeros_like(data1)
        slices = []
        for dim in data2.shape:
            if dim % 2 == 0:
                slices.append(slice(dim // 2))
            else:
                slices.append(slice(dim // 2, dim // 2 + 1))
        data2[tuple(slices)] = 1
        data2 = gaussian(data2, sigma=1, preserve_range=True)

    if data1.ndim != data2.ndim:
        raise ValueError("Data1 and Data2 must have the same number of dimensions.")

    corr_arr = signal.correlate(data1, data2, mode="same")

    profiles = []
    max_pos = np.unravel_index(np.argmax(corr_arr), corr_arr.shape)
    for dim in range(corr_arr.ndim):
        pos_slices = [slice(pos, pos + 1) for pos in max_pos]
        pos_slices[dim] = slice(None)
        profiles.append(np.squeeze(corr_arr[tuple(pos_slices)]))

    return tuple(fit_gaussian(profile)[3][2] - profile.shape[0] // 2 for profile in profiles)


def _calculate_bead_intensity_outliers(
    bead_positions: pd.DataFrame, robust_z_score_threshold: float
) -> None:
    bead_positions["max_intensity_robust_z_score"] = pd.Series(dtype="float")
    bead_positions["considered_intensity_outlier"] = pd.Series(dtype="bool")

    median = bead_positions[bead_positions.considered_valid]["intensity_max"].median()
    mad = bead_positions[bead_positions.considered_valid]["intensity_max"].mad()

    if len(bead_positions[bead_positions.considered_valid]) == 1:
        bead_positions["max_intensity_robust_z_score"] = 0
        bead_positions["considered_intensity_outlier"] = False
    elif 1 < len(bead_positions[bead_positions.considered_valid]) < 6:
        bead_positions["max_intensity_robust_z_score"] = (
            0.6745 * (bead_positions["intensity_max"] - median) / mad
        )
        bead_positions["considered_intensity_outlier"] = False
    else:
        bead_positions["max_intensity_robust_z_score"] = (
            0.6745 * (bead_positions["intensity_max"] - median) / mad
        )
        bead_positions["considered_intensity_outlier"] = (
            abs(bead_positions["max_intensity_robust_z_score"]) > robust_z_score_threshold
        )

    bead_positions["considered_intensity_outlier"] = bead_positions[
        "considered_intensity_outlier"
    ].astype(bool)


def _generate_key_measurements(bead_properties_df, average_bead_properties):
    measurement_aggregation_columns = [
        "channel_nr",
        "intensity_max",
        "intensity_min",
        "intensity_std",
        "fit_r2_z",
        "fit_r2_y",
        "fit_r2_x",
        "fwhm_pixel_z",
        "fwhm_pixel_y",
        "fwhm_pixel_x",
        "fwhm_lateral_asymmetry_ratio",
        "fwhm_micron_z",
        "fwhm_micron_y",
        "fwhm_micron_x",
    ]
    count_aggregation_columns = [
        "channel_nr",
        "considered_valid",
        "considered_self_proximity",
        "considered_lateral_edge",
        "considered_axial_edge",
        "considered_intensity_outlier",
        "considered_bad_fit_z",
        "considered_bad_fit_y",
        "considered_bad_fit_x",
    ]

    reindex_bead_properties_df = bead_properties_df.reset_index()

    # We aggregate counts for each channel on beads according to their status
    channel_counts = (
        reindex_bead_properties_df[count_aggregation_columns].groupby("channel_nr").agg(["sum"])
    )
    channel_counts.columns = [
        "_".join((col[0], "count")).strip() for col in channel_counts.columns.values
    ]

    # We aggregate measurements for each channel only on beads considered valid
    valid_bead_properties_df = reindex_bead_properties_df[
        reindex_bead_properties_df.considered_valid
    ]
    channel_measurements = (
        valid_bead_properties_df[measurement_aggregation_columns]
        .groupby("channel_nr")
        .agg(["mean", "median", "std"])
    )
    channel_measurements.columns = [
        "_".join(col).strip() for col in channel_measurements.columns.values
    ]

    for ch_nr, values in average_bead_properties.items():
        channel_measurements.at[ch_nr, "average_bead_fit_r2_z"] = values["r2"][0]
        channel_measurements.at[ch_nr, "average_bead_fit_r2_y"] = values["r2"][1]
        channel_measurements.at[ch_nr, "average_bead_fit_r2_x"] = values["r2"][2]
        channel_measurements.at[ch_nr, "average_bead_fwhm_pixel_z"] = values["fwhm"][0]
        channel_measurements.at[ch_nr, "average_bead_fwhm_pixel_y"] = values["fwhm"][1]
        channel_measurements.at[ch_nr, "average_bead_fwhm_pixel_x"] = values["fwhm"][2]
        channel_measurements.at[ch_nr, "average_bead_fwhm_micron_z"] = values["fwhm_micron"][0]
        channel_measurements.at[ch_nr, "average_bead_fwhm_micron_y"] = values["fwhm_micron"][1]
        channel_measurements.at[ch_nr, "average_bead_fwhm_micron_x"] = values["fwhm_micron"][2]
        channel_measurements.at[ch_nr, "average_bead_fwhm_lateral_asymmetry_ratio"] = values[
            "fwhm_lateral_asymmetry_ratio"
        ]

    return pd.merge(channel_counts, channel_measurements, how="outer", on=["channel_nr"])


def _process_bead(bead: np.ndarray, voxel_size_micron: tuple[float, float, float]):
    # Find the strongest sections to generate profiles
    z_max = np.max(bead, axis=(1, 2))
    z_focus = np.argmax(z_max)
    y_max = np.max(bead, axis=(0, 2))
    y_focus = np.argmax(y_max)
    x_max = np.max(bead, axis=(0, 1))
    x_focus = np.argmax(x_max)

    # Generate profiles
    profile_z = np.squeeze(bead[:, y_focus, x_focus])
    profile_y = np.squeeze(bead[z_focus, :, x_focus])
    profile_x = np.squeeze(bead[z_focus, y_focus, :])

    # Normalize the profiles and subtract the background
    profile_z = (profile_z - profile_z.min()) / (profile_z.max() - profile_z.min())
    profile_y = (profile_y - profile_y.min()) / (profile_y.max() - profile_y.min())
    profile_x = (profile_x - profile_x.min()) / (profile_x.max() - profile_x.min())

    # Fitting the profiles
    profile_z_fitted, r2_z, fwhm_z, (center_pos_z, _) = fit_airy(profile_z)
    profile_y_fitted, r2_y, fwhm_y, (center_pos_y, _) = fit_airy(profile_y)
    profile_x_fitted, r2_x, fwhm_x, (center_pos_x, _) = fit_airy(profile_x)

    fwhm_lateral_asymmetry_ratio = max(fwhm_y, fwhm_x) / min(fwhm_y, fwhm_x)

    if all(voxel_size_micron):
        fwhm_micron_z = fwhm_z * voxel_size_micron[0]
        fwhm_micron_y = fwhm_y * voxel_size_micron[1]
        fwhm_micron_x = fwhm_x * voxel_size_micron[2]
    else:
        fwhm_micron_z = None
        fwhm_micron_y = None
        fwhm_micron_x = None

    considered_axial_edge = (
        center_pos_z < fwhm_z * 4 or profile_z.shape[0] - center_pos_z < fwhm_z * 4
    )

    intensity_max = bead.max()
    intensity_min = bead.min()
    intensity_std = bead.std()

    return {
        "profile_z": profile_z,
        "profile_z_fitted": profile_z_fitted,
        "profile_y": profile_y,
        "profile_y_fitted": profile_y_fitted,
        "profile_x": profile_x,
        "profile_x_fitted": profile_x_fitted,
        "fit_r2_z": r2_z,
        "fit_r2_y": r2_y,
        "fit_r2_x": r2_x,
        "fwhm_pixel_z": fwhm_z,
        "fwhm_pixel_y": fwhm_y,
        "fwhm_pixel_x": fwhm_x,
        "fwhm_micron_z": fwhm_micron_z,
        "fwhm_micron_y": fwhm_micron_y,
        "fwhm_micron_x": fwhm_micron_x,
        "fwhm_lateral_asymmetry_ratio": fwhm_lateral_asymmetry_ratio,
        "considered_axial_edge": considered_axial_edge,
        "intensity_max": intensity_max,
        "intensity_min": intensity_min,
        "intensity_std": intensity_std,
    }


def _find_beads(channel: np.ndarray, sigma: tuple[float, float, float], min_distance: float):
    logger.debug("Finding beads in channel...")

    if all(sigma):
        logger.debug(f"Applying Gaussian filter with sigma {sigma}")
        channel_gauss = gaussian(image=channel, sigma=sigma)
    else:
        logger.debug("No Gaussian filter applied")
        channel_gauss = channel

    # We find the beads in the MIP for performance and to avoid anisotropy issues in the axial direction
    channel_gauss_mip = np.max(channel_gauss, axis=0)

    # Find bead centers
    positions_all = peak_local_max(image=channel_gauss_mip, threshold_rel=0.2)
    positions_all_not_proximity_not_edge = peak_local_max(
        image=channel_gauss_mip,
        threshold_rel=0.2,
        min_distance=int(min_distance),
        exclude_border=(int(1 + min_distance // 2), int(1 + min_distance // 2)),
        p_norm=2,
    )
    positions_all_not_proximity = peak_local_max(
        image=channel_gauss_mip,
        threshold_rel=0.2,
        min_distance=int(min_distance),
        exclude_border=False,
        p_norm=2,
    )

    # We convert the arrays into sets to perform easier to follow filtering logic
    positions_all = set(map(tuple, positions_all))
    positions_all_not_proximity_not_edge = set(map(tuple, positions_all_not_proximity_not_edge))
    positions_all_not_proximity = set(map(tuple, positions_all_not_proximity))

    # positions_proximity_edge = positions_all - positions_all_not_proximity_not_edge
    positions_edge = positions_all_not_proximity - positions_all_not_proximity_not_edge
    positions_proximity = positions_all - positions_all_not_proximity

    positions_df = pd.DataFrame(
        positions_all,
        columns=["center_y", "center_x"],
        index=pd.Index(range(len(positions_all)), name="bead_id"),
    )
    positions_df["center_z"] = positions_df.apply(
        lambda row: int(channel_gauss[:, row["center_y"], row["center_x"]].argmax()),
        axis=1,
    )

    positions_df["considered_valid"] = positions_df.apply(
        lambda row: (row["center_y"], row["center_x"]) in positions_all_not_proximity_not_edge,
        axis=1,
    )
    positions_df["considered_self_proximity"] = positions_df.apply(
        lambda row: (row["center_y"], row["center_x"]) in positions_proximity, axis=1
    )
    positions_df["considered_lateral_edge"] = positions_df.apply(
        lambda row: (row["center_y"], row["center_x"]) in positions_edge, axis=1
    )

    logger.debug(f"Beads found: {len(positions_all)}")
    logger.debug(f"Beads kept for further analysis: {positions_df['considered_valid'].sum()}")
    logger.debug(
        f"Beads considered for being to close to the edge: {positions_df['considered_lateral_edge'].sum()}"
    )
    logger.debug(
        f"Beads considered for being to close to each other: {positions_df['considered_self_proximity'].sum()}"
    )

    def get_bead_image(row, channel, min_distance):
        return channel[
            :,
            max(0, (row["center_y"] - int(min_distance // 2))) : min(
                channel.shape[1], (row["center_y"] + int(min_distance // 2) + 1)
            ),
            max(0, (row["center_x"] - int(min_distance // 2))) : min(
                channel.shape[2], (row["center_x"] + int(min_distance // 2) + 1)
            ),
        ]

    positions_df["beads"] = positions_df.apply(get_bead_image, axis=1, args=(channel, min_distance))

    return positions_df


def _process_channel(
    channel: np.ndarray,
    sigma: tuple[float, float, float],
    min_bead_distance: float,
    snr_threshold: float,
    fitting_r2_threshold: float,
    intensity_robust_z_score_threshold: float,
    voxel_size_micron: tuple[float, float, float],
) -> tuple:
    bead_properties = _find_beads(
        channel=channel,
        sigma=sigma,
        min_distance=min_bead_distance,
    )

    bead_properties = bead_properties.assign(
        considered_intensity_outlier=pd.Series(dtype=bool),
    )

    bead_properties = bead_properties.join(
        bead_properties["beads"].apply(lambda x: pd.Series(_process_bead(x, voxel_size_micron)))
    )
    bead_properties["considered_bad_fit_z"] = bead_properties["fit_r2_z"] < fitting_r2_threshold
    bead_properties["considered_bad_fit_y"] = bead_properties["fit_r2_y"] < fitting_r2_threshold
    bead_properties["considered_bad_fit_x"] = bead_properties["fit_r2_x"] < fitting_r2_threshold

    _calculate_bead_intensity_outliers(
        bead_properties, robust_z_score_threshold=intensity_robust_z_score_threshold
    )

    # We need to invalidate all the bad fits and outliers
    bead_properties["considered_valid"] = bead_properties.apply(
        lambda row: not any(
            [
                row["considered_axial_edge"],
                row["considered_bad_fit_z"],
                row["considered_bad_fit_y"],
                row["considered_bad_fit_x"],
                row["considered_intensity_outlier"],
            ]
        ),
        axis=1,
    )

    return bead_properties


def _process_image(
    image: np.ndarray,
    sigma: tuple[float, float, float],
    min_bead_distance: float,
    snr_threshold: float,
    fitting_r2_threshold: float,
    intensity_robust_z_score_threshold: float,
    voxel_size_micron: tuple[float, float, float],
) -> tuple:
    # Remove the time dimension
    image = image[0, ...]

    # Some images (e.g. OMX-3D-SIM) may contain negative values.
    image = np.clip(image, a_min=0, a_max=None)

    nr_channels = image.shape[-1]

    bead_properties = []

    for ch in range(nr_channels):
        ch_bead_positions = _process_channel(
            channel=image[..., ch],
            sigma=sigma,
            min_bead_distance=min_bead_distance,
            snr_threshold=snr_threshold,
            fitting_r2_threshold=fitting_r2_threshold,
            intensity_robust_z_score_threshold=intensity_robust_z_score_threshold,
            voxel_size_micron=voxel_size_micron,
        )

        _add_row_index_level(ch_bead_positions, "channel_nr", ch)
        bead_properties.append(ch_bead_positions)

    return pd.concat(bead_properties)


def _estimate_min_bead_distance(dataset: mm_schema.PSFBeadsDataset) -> float:
    # TODO: get the resolution somewhere or pass it as a metadata
    return dataset.input.min_lateral_distance_factor


def _generate_center_roi(
    dataset: mm_schema.PSFBeadsDataset,
    positions,
    root_name,
    color,
    stroke_width=1,
):
    rois = []

    for image in dataset.input.psf_beads_images:
        if positions.empty or image.name not in positions.index.get_level_values("image_name"):
            continue
        points = []
        for index, row in positions.xs(image.name, level="image_name").iterrows():
            points.append(
                mm_schema.Point(
                    name=_concatenate_index_levels(
                        index_names=positions.index.names[1:], index_values=index
                    ),
                    z=row["center_z"],
                    y=row["center_y"] + 0.5,  # Rois are centered on the voxel
                    x=row["center_x"] + 0.5,
                    c=index[positions.index.names[1:].index("channel_nr")],
                    stroke_color=mm_schema.Color(
                        r=color[0], g=color[1], b=color[2], alpha=color[3]
                    ),
                    stroke_width=stroke_width,
                )
            )

        if points:
            rois.append(
                mm_schema.Roi(
                    name=f"{root_name}_{image.name}",
                    description=f"{root_name} in image {image.name}",
                    linked_references=image.data_reference,
                    points=points,
                )
            )

    return rois


def analyse_psf_beads(dataset: mm_schema.PSFBeadsDataset) -> bool:
    validate_requirements()
    # TODO: Implement Nyquist validation??

    # Containers for input data and input parameters
    images = {}
    voxel_sizes_micron = {}
    min_bead_distance = _estimate_min_bead_distance(dataset)
    snr_threshold = dataset.input.snr_threshold
    fitting_r2_threshold = dataset.input.fitting_r2_threshold

    # Containers for output data
    saturated_channels = {}
    beads = {}
    bead_properties = []
    bead_profiles_z = []
    bead_profiles_y = []
    bead_profiles_x = []

    # First loop to prepare data
    for image in dataset.input.psf_beads_images:
        images[image.name] = image.array_data[0, ...]

        voxel_sizes_micron[image.name] = (
            image.voxel_size_z_micron,
            image.voxel_size_y_micron,
            image.voxel_size_x_micron,
        )
        saturated_channels[image.name] = []

        # Check image shape
        logger.info(f"Checking image {image.name} shape...")
        if len(image.array_data.shape) != 5:
            logger.error(f"Image {image.name} must be 5D")
            return False
        if image.array_data.shape[0] != 1:
            logger.warning(
                f"Image {image.name} must be in TZYXC order and single time-point. Using first time-point."
            )

        # Check image saturation
        logger.info(f"Checking image {image.name} saturation...")
        for c in range(image.array_data.shape[-1]):
            if is_saturated(
                channel=image.array_data[..., c],
                threshold=dataset.input.saturation_threshold,
                detector_bit_depth=dataset.input.bit_depth,
            ):
                logger.error(f"Image {image.name}: channel {c} is saturated")
                saturated_channels[image.name].append(c)

    if any(len(saturated_channels[name]) for name in saturated_channels):
        logger.error(f"Channels {saturated_channels} are saturated")
        raise SaturationError(f"Channels {saturated_channels} are saturated")

    # Second loop main image analysis
    for image in dataset.input.psf_beads_images:
        logger.info(f"Processing image {image.name}...")

        image_bead_properties = _process_image(
            image=image.array_data,
            sigma=(dataset.input.sigma_z, dataset.input.sigma_y, dataset.input.sigma_x),
            min_bead_distance=min_bead_distance,
            snr_threshold=snr_threshold,
            fitting_r2_threshold=fitting_r2_threshold,
            intensity_robust_z_score_threshold=dataset.input.intensity_robust_z_score_threshold,
            voxel_size_micron=voxel_sizes_micron[image.name],
        )

        logger.info(
            f"Image {image.name} processed."
            f"    {image_bead_properties.considered_valid.sum()} beads considered valid."
            f"    {image_bead_properties.considered_lateral_edge.sum()} beads considered lateral edge."
            f"    {image_bead_properties.considered_self_proximity.sum()} beads considered self proximity."
            f"    {image_bead_properties.considered_axial_edge.sum()} beads considered axial edge."
            f"    {image_bead_properties.considered_intensity_outlier.sum()} beads considered intensity outlier."
            f"    {image_bead_properties.considered_bad_fit_z.sum()} beads considered bad fit in z."
            f"    {image_bead_properties.considered_bad_fit_y.sum()} beads considered bad fit in y."
            f"    {image_bead_properties.considered_bad_fit_x.sum()} beads considered bad fit in x."
        )

        _add_row_index_level(image_bead_properties, "image_name", image.name)
        bead_properties.append(image_bead_properties)

    bead_properties = pd.concat(bead_properties)

    # Before averaging any bead we need to verify that all voxel sizes are equal
    if len(set(voxel_sizes_micron.values())) == 1:
        # TODO: catch up here with pandization
        average_beads_properties = bead_properties.groupby("channel_nr").apply(_average_beads)
        average_beads_properties = average_beads_properties.join(
            average_beads_properties["average_bead"].apply(
                lambda x: pd.Series(_process_bead(x, voxel_sizes_micron[image.name]))
            )
        )

    else:
        logger.error("Voxel sizes are not equal among images. Skipping average bead calculation.")
        average_beads_properties = None

    # TODO: catch up here with pandization
    considered_valid_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_valid],
        root_name="considered_valid_bead_centers",
        color=(0, 255, 0, 100),
        stroke_width=8,
    )
    considered_lateral_edge_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_lateral_edge],
        root_name="considered_lateral_edge_bead_centers",
        color=(255, 0, 0, 100),
        stroke_width=4,
    )
    considered_self_proximity_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_self_proximity],
        root_name="considered_self_proximity_bead_centers",
        color=(255, 0, 0, 100),
        stroke_width=4,
    )
    considered_axial_edge_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_axial_edge],
        root_name="considered_axial_edge_bead_centers",
        color=(0, 0, 255, 100),
        stroke_width=4,
    )
    considered_intensity_outlier_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_intensity_outlier],
        root_name="considered_intensity_outlier_bead_centers",
        color=(0, 0, 255, 100),
        stroke_width=4,
    )
    considered_bad_fit_z_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_bad_fit_z],
        root_name="considered_bad_fit_z_bead_centers",
        color=(0, 0, 255, 100),
        stroke_width=4,
    )
    considered_bad_fit_y_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_bad_fit_y],
        root_name="considered_bad_fit_y_bead_centers",
        color=(0, 0, 255, 100),
        stroke_width=4,
    )
    considered_bad_fit_x_bead_centers = _generate_center_roi(
        dataset=dataset,
        positions=bead_properties[bead_properties.considered_bad_fit_x],
        root_name="considered_bad_fit_x_bead_centers",
        color=(0, 0, 255, 100),
        stroke_width=4,
    )
    key_measurements = mm_schema.PSFBeadsKeyMeasurements(
        name="psf_bead_key_measurements",
        description="Averaged key measurements for all beads considered valid in the dataset.",
        **_generate_key_measurements(
            bead_properties_df=bead_properties, average_bead_properties=average_beads_properties
        ).to_dict("list"),
    )
    bead_properties = df_to_table(bead_properties, "bead_properties")
    bead_profiles_z = df_to_table(bead_profiles_z, "bead_profiles_z")
    bead_profiles_y = df_to_table(bead_profiles_y, "bead_profiles_y")
    bead_profiles_x = df_to_table(bead_profiles_x, "bead_profiles_x")

    dataset.output = mm_schema.PSFBeadsOutput(
        processing_application="microscopemetrics",
        processing_version="0.1.0",
        processing_datetime=datetime.now(),
        analyzed_bead_centers=considered_valid_bead_centers,
        considered_bead_centers_lateral_edge=considered_lateral_edge_bead_centers,
        considered_bead_centers_self_proximity=considered_self_proximity_bead_centers,
        considered_bead_centers_axial_edge=considered_axial_edge_bead_centers,
        considered_bead_centers_intensity_outlier=considered_intensity_outlier_bead_centers,
        considered_bead_centers_z_fit_quality=considered_bad_fit_z_bead_centers,
        considered_bead_centers_y_fit_quality=considered_bad_fit_y_bead_centers,
        considered_bead_centers_x_fit_quality=considered_bad_fit_x_bead_centers,
        key_measurements=key_measurements,
        bead_properties=bead_properties,
        bead_z_profiles=bead_profiles_z,
        bead_y_profiles=bead_profiles_y,
        bead_x_profiles=bead_profiles_x,
    )

    dataset.processed = True

    return True


# Calculate 2D FFT
# slice_2d = raw_img[17, ...].reshape([1, n_channels, x_size, y_size])
# fft_2D = fft_2d(slice_2d)

# Calculate 3D FFT
# fft_3D = fft_3d(spots_image)
#
# plt.imshow(np.log(fft_3D[2, :, :, 1]))  # , cmap='hot')
# # plt.imshow(np.log(fft_3D[2, 23, :, :]))  # , cmap='hot')
# plt.show()
#
