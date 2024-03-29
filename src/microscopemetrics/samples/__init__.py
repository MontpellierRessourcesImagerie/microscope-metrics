# Main samples module defining the sample superclass

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Union

import microscopemetrics_schema.datamodel as mm_schema
import numpy as np

# We are defining some global dictionaries to register the different analysis types
IMAGE_ANALYSIS_REGISTRY = {}
DATASET_ANALYSIS_REGISTRY = {}
PROGRESSION_ANALYSIS_REGISTRY = {}


# Decorators to register exposed analysis functions
def register_image_analysis(cls):
    IMAGE_ANALYSIS_REGISTRY[cls.__name__] = cls
    return cls


def register_dataset_analysis(cls):
    DATASET_ANALYSIS_REGISTRY[cls.__name__] = cls
    return cls


def register_progression_analysis(cls):
    PROGRESSION_ANALYSIS_REGISTRY[cls.__name__] = cls
    return cls


# Create a logging service
logger = logging.getLogger(__name__)


def numpy_to_image_byref(
    array: np.ndarray,
    name: str = None,
    description: str = None,
    image_url: str = None,
    source_image_url: Union[str, List[str]] = None,
) -> mm_schema.ImageAsNumpy:
    """Converts a numpy array with dimensions order tzyxc to an image by reference (not inlined)"""
    if array.ndim == 5:
        return mm_schema.ImageAsNumpy(
            name=name,
            description=description,
            image_url=image_url,
            source_image_url=source_image_url,
            data=array,
            shape_t=array.shape[0],
            shape_z=array.shape[1],
            shape_y=array.shape[2],
            shape_x=array.shape[3],
            shape_c=array.shape[4],
        )
    elif array.ndim == 2:
        return mm_schema.ImageAsNumpy(
            name=name,
            description=description,
            image_url=image_url,
            source_image_url=source_image_url,
            data=array,
            shape_y=array.shape[0],
            shape_x=array.shape[1],
        )
    else:
        raise NotImplementedError(
            f"Array of dimension {array.ndim} is not supported by this function. Image has to have either 5 or 2 dimensions"
        )


def numpy_to_mask_inlined(
    array: np.ndarray,
    name: str = None,
    description: str = None,
    image_url: str = None,
    source_image_url: Union[str, List[str]] = None,
) -> mm_schema.ImageMask:
    """Converts a bool numpy array with dimensions order yx to an inlined mask"""
    if array.ndim != 2:
        raise ValueError("Input array should be 2D")
    if array.dtype != bool and array.dtype == np.uint8:
        try:
            array = array.astype(bool)
        except ValueError:
            raise ValueError("Input array could not be casted to type bool")
    if array.dtype != bool:
        raise ValueError("Input array should be of type bool")

    return mm_schema.ImageMask(
        name=name,
        description=description,
        image_url=image_url,
        source_image_url=source_image_url,
        data=array.flatten().tolist(),
        shape_y=array.shape[0],
        shape_x=array.shape[1],
    )


def numpy_to_image_inlined(
    array: np.ndarray,
    name: str = None,
    description: str = None,
    image_url: str = None,
    source_image_url: Union[str, List[str]] = None,
) -> mm_schema.ImageInline:
    """Converts a numpy array with dimensions order tzyxc or yx to an inlined image"""
    if array.ndim == 5:
        return mm_schema.Image5D(
            name=name,
            description=description,
            image_url=image_url,
            source_image_url=source_image_url,
            data=array.flatten().tolist(),
            shape_t=array.shape[0],
            shape_z=array.shape[1],
            shape_y=array.shape[2],
            shape_x=array.shape[3],
            shape_c=array.shape[4],
        )
    elif array.ndim == 2:
        return mm_schema.Image2D(
            name=name,
            description=description,
            image_url=image_url,
            source_image_url=source_image_url,
            data=array.flatten().tolist(),
            shape_y=array.shape[0],
            shape_x=array.shape[1],
        )
    else:
        raise NotImplementedError(
            f"Array of dimension {array.ndim} is not supported by this function"
        )


def dict_to_table_inlined(
    dictionary: Dict[str, list],
    name: str = None,
    description: str = None,
) -> mm_schema.Table:
    """Converts a dictionary to an microscope-metrics inlined table"""
    return mm_schema.TableAsDict(
        name=name,
        description=description,
        columns=[{"name": k, "values": dictionary[k]} for k in dictionary.keys()],
    )


class AnalysisMixin(ABC):
    """This is a mixin class defining some helper functions to work with the linkml autogenerated schema."""

    def __init__(self):
        pass

    def describe_requirements(self):
        print(self.input.describe_requirements())

    def validate_requirements(self) -> bool:
        logger.info("Validating requirements...")
        # TODO: check image dimensions/shape
        return True
