# Main samples module defining the sample superclass

import logging
from abc import ABC, abstractmethod
from typing import Any, Union

from ..model import model

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


class Configurator(ABC):
    """This is a superclass taking care of the configuration of a new sample. Helps generating configuration files and
    defines the metadata required for the different analyses. You should subclass this when you create a
    new sample. One for each type of configurator that you wish to have.
    """

    # The configuration section has to be defined for every subclass
    CONFIG_SECTION: str = None

    def __init__(self, config):
        self.config = config
        self.metadata_definitions = self.define_metadata()

    @abstractmethod
    def define_metadata(self):
        pass

    @classmethod
    def register_sample_analysis(cls, sample_class):
        cls.SAMPLE_CLASS = sample_class
        return sample_class


class Analysis(ABC):
    """This is the superclass defining the interface to a sample object. You should subclass this when you create a
    new sample analysis."""

    def __init__(self, output_description):
        self.input = model.MetricsDataset()
        self.output = model.MetricsOutput(description=output_description)

    @classmethod
    def get_name(cls):
        """Returns the module name of the class. Without path and extension.
        :returns a string with the module name
        """
        return cls.__module__.split(sep=".")[-1]

    def add_data_requirement(
        self,
        name: str,
        description: str,
        data_type,
        optional: bool = False,
        replace: bool = False,
    ):
        self.input.add_data_requirement(
            name=name,
            description=description,
            data_type=data_type,
            optional=optional,
            replace=replace,
        )

    def add_metadata_requirement(
        self,
        name: str,
        description: str,
        data_type,
        optional: bool,
        units: str = None,
        default: Any = None,
    ):
        self.input.add_metadata_requirement(
            name=name,
            description=description,
            data_type=data_type,
            optional=optional,
            units=units,
            default=default,
        )

    def describe_requirements(self):
        print(self.input.describe_requirements())

    def validate_requirements(self):
        return self.input.validate_requirements()

    def list_unmet_requirements(self):
        return self.input.list_unmet_requirements()

    def set_data(self, name: str, value):
        self.input.set_data_values(name, value)

    def set_metadata(self, name: str, value):
        self.input.set_metadata_values(name, value)

    def delete_data(self, name: str):
        self.input.del_data_values(name)

    def delete_metadata(self, name: str):
        self.input.del_metadata_values(name)

    def get_data_values(self, name: Union[str, list]):
        return self.input.get_data_values(name)

    def get_metadata_values(self, name: Union[str, list]):
        return self.input.get_metadata_values(name)

    def get_metadata_units(self, name: Union[str, list]):
        return self.input.get_metadata_units(name)

    def get_metadata_defaults(self, name: Union[str, list]):
        return self.input.get_metadata_defaults(name)

    @abstractmethod
    def run(self):
        raise NotImplemented()
