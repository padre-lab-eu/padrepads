from typing import List, Any, Type, Union

from pydantic import BaseModel, Field
from pypads import logger
from pypads.app.backends.repository import RepositoryEntryModel
from pypads.app.env import InjectionLoggerEnv
from pypads.app.injections.base_logger import TrackedObject
from pypads.app.injections.injection import InjectionLogger
from pypads.importext.versioning import all_libs
from pypads.model.logger_call import InjectionLoggerCallModel
from pypads.model.logger_output import TrackedObjectModel, OutputModel
from pypads.model.models import BaseStorageModel, ResultType, IdReference
from pypads.utils.logging_util import FileFormats, data_str
from pypads_onto.arguments import ontology_uri
from pypads_onto.model.ontology import EmbeddedOntologyModel

from pypads_padre.concepts.dataset import Crawler
from pypads_padre.concepts.util import persistent_hash, validate_type


class DatasetRepositoryObject(BaseStorageModel):
    """
    Class to be used in the repository holding a dataset. Repositories are supposed to store objects used over
    multiple runs.
    """
    name: str = ...  # Name of the dataset
    category: str = "DatasetRepositoryEntry"
    description: str = ...
    documentation: str = ...
    binary_reference: str = ...  # Reference to the dataset binary
    location: str = ...  # Place where it is defined
    storage_type: Union[str, ResultType] = "dataset"


class DatasetOutput(OutputModel):
    """
    Output of the logger
    """
    dataset: IdReference = ...  # Reference to dataset TO


class DatasetPropertyValue(EmbeddedOntologyModel):
    """
    Represents the property value. This can be any dataset property which can be saved as a simple value.
    This subclass allows for valid json-ld representation with nested resources.
    """
    context: Union[List[Union[str, dict]], str, dict] = Field(alias="@context", default={
        "has_value": {
            "@id": f"{ontology_uri}has_value",
            "@type": "rdf:XMLLiteral"
        }
    })
    has_value: str = ...
    category: str = "DatasetPropertyValue"


class DatasetTO(TrackedObject):
    """
    Tracking Object logging the used dataset in your run.
    """

    class DatasetModel(TrackedObjectModel):
        """ƒ
        Model defining the values for the tracked object.
        """

        context: Union[List[str], str, dict] = {
            "number_of_instances": {
                "@id": f"{ontology_uri}has_instances",
                "@type": f"{ontology_uri}DatasetProperty"
            },
            "number_of_features": {
                "@id": f"{ontology_uri}has_features",
                "@type": f"{ontology_uri}DatasetProperty"
            },
            # "features": {
            #     "type": {
            #         "@id": f"{ontology_uri}has_type",
            #         "@type": f"{ontology_uri}FeatureProperty"
            #     },
            #     "default_target": {
            #         "@id": f"{ontology_uri}is_target",
            #         "@type": f"{ontology_uri}FeatureProperty"
            #     }
            # },
            "data": {
                "@id": f"{ontology_uri}stored_at",
                "@type": f"{ontology_uri}Data"
            }
        }

        class Feature(EmbeddedOntologyModel):
            context: Union[List[Union[str, dict]], str, dict] = Field(alias="@context", default={
                "type": {
                    "@id": f"{ontology_uri}has_type",
                    "@type": "rdf:XMLLiteral"  # TODO which type?
                },
                "default_target": {
                    "@id": f"{ontology_uri}is_default_target",
                    "@type": "rdf:XMLLiteral"  # TODO which type?
                },
                "range": {
                    "@id": f"{ontology_uri}has_range",  # TODO maybe add owl rules?
                    "@type": "rdf:XMLLiteral"  # TODO which type?
                }
            })
            category: str = "Feature"
            name: str = ...
            type: str = ...
            default_target: bool = False
            range: tuple = None

            class Config:
                orm_mode = True

        category: str = "Dataset"
        name: str = ...
        description = "This tracked object references a dataset used in the experiment. "
        number_of_instances: DatasetPropertyValue = ...
        number_of_features: DatasetPropertyValue = ...
        features: List[Feature] = []
        repository_reference: str = ...  # reference to the dataset in the repository
        repository_type: str = ...  # type of the repository. Will always be extracted from the repository aka
        # 'pypads_datasets'

    @classmethod
    def get_model_cls(cls) -> Type[BaseModel]:
        return cls.DatasetModel

    def __init__(self, *args, parent, name, shape, metadata, **kwargs):
        super().__init__(*args, parent=parent, name=name,
                         number_of_instances=DatasetPropertyValue(has_value=str(shape[0])),
                         number_of_features=DatasetPropertyValue(has_value=shape[1]), **kwargs)
        features = metadata.get("features", None)
        if features is not None:
            for name, type, default_target, range in features:
                self.features.append(
                    self.DatasetModel.Feature(name=validate_type(name), type=validate_type(type),
                                              default_target=default_target,
                                              range=validate_type(range)))

    def store_data(self, obj: Any, metadata, format):
        # Fill the tracked object for the current run
        return self.store_mem_artifact(self.name, obj, write_format=format, description="Dataset binary",
                                       additional_data=metadata)


class DatasetILF(InjectionLogger):
    """
    Function logging the wrapped dataset loader.

        Hook:
        Hook this logger to the loader of a dataset (it can be a function, or class)
    """
    name = "Dataset Logger"
    type: str = "DatasetLogger"
    supported_libraries = {all_libs}

    @classmethod
    def output_schema_class(cls) -> Type[OutputModel]:
        return DatasetOutput

    def __post__(self, ctx, *args, _pypads_env: InjectionLoggerEnv, _logger_call: InjectionLoggerCallModel,
                 _logger_output, _pypads_result, _args, _kwargs, _pypads_write_format=FileFormats.pickle, **kwargs):
        pads = _pypads_env.pypads

        # if the return object is None, take the object instance ctx
        dataset_object = _pypads_result if _pypads_result is not None else ctx

        mapping_data = _pypads_env.data
        dataset_data = data_str(mapping_data, "dataset", "@schema", default={})

        # Get additional arguments if given by the user
        _dataset_kwargs = dict()
        if pads.cache.run_exists("dataset_kwargs"):
            _dataset_kwargs = pads.cache.run_get("dataset_kwargs")

        # Scrape the data object
        crawler = Crawler(dataset_object, ctx=_logger_call.original_call.call_id.context.container,
                          callback=_logger_call.original_call.call_id.wrappee,
                          kw=_kwargs)
        data, metadata, targets = crawler.crawl(**_dataset_kwargs)
        pads.cache.run_add("targets", targets)

        # Look for metadata information given by the user when using the decorators
        if pads.cache.run_exists("dataset_metadata"):
            metadata = {**metadata, **pads.cache.run_get("dataset_metadata")}

        # getting the dataset object name
        if hasattr(dataset_object, "name"):
            ds_name = dataset_object.name
        elif pads.cache.run_exists("dataset_name") and pads.cache.run_exists("dataset_name") is not None:
            ds_name = pads.cache.run_get("dataset_name")
        else:
            ds_name = _logger_call.original_call.call_id.wrappee.__qualname__

        # compile identifying hash
        try:
            data_hash = persistent_hash(str(dataset_object))
        except Exception:
            logger.warning("Could not compute the hash of the dataset object, falling back to dataset name hash...")
            data_hash = persistent_hash(str(self.name))

        # create referencing object
        dto = DatasetTO(parent=_logger_output, name=ds_name, shape=metadata.get("shape"), metadata=metadata,
                        repository_reference=data_hash, repository_type=_pypads_env.pypads.dataset_repository.name)

        # Add to repo if needed
        if not pads.dataset_repository.has_object(uid=data_hash):
            logger.info("Detected Dataset was not found in the store. Adding an entry...")
            repo_obj = pads.dataset_repository.get_object(uid=data_hash)
            binary_ref = repo_obj.log_mem_artifact(dto.name, dataset_object, write_format=_pypads_write_format,
                                                   description="Dataset binary",
                                                   additional_data=metadata, holder=dto)
            logger.info("Entry added in the dataset repository.")
            # create repository object
            dro = DatasetRepositoryObject(name=data_str(dataset_data, "rdfs:label", default=self.name),
                                          uid=data_hash,
                                          description=data_str(dataset_data, "rdfs:description",
                                                               default="Some unkonwn Dataset"),
                                          documentation=data_str(dataset_data, "padre:documentation",
                                                                 default=ctx.__doc__ if ctx else _logger_call.original_call.call_id.wrappee.__doc__),
                                          binary_reference=binary_ref,
                                          location=_logger_call.original_call.call_id.context.reference,
                                          additional_data=dataset_data)
            repo_obj.log_json(dro)

        # Store object
        _logger_output.dataset = dto.store()
