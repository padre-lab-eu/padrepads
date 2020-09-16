import os
import uuid
from logging import warning
from typing import Iterable, Type, Any, List

from pydantic import HttpUrl, BaseModel
from pypads import logger
from pypads.app.injections.base_logger import TrackedObject
from pypads.app.injections.injection import InjectionLogger
from pypads.importext.mappings import LibSelector
from pypads.model.models import OutputModel, TrackedObjectModel


class SingleInstanceTO(TrackedObject):
    """
        Tracking Object class for single instance results
        """

    class SingleInstancesModel(TrackedObjectModel):
        uri: HttpUrl = "https://www.padre-lab.eu/onto/SingleInstanceResult"

        class DecisionModel(BaseModel):
            instance: str = ...
            prediction: Any = ...
            probability: float = ...

            class Config:
                orm_mode = True
                arbitrary_types_allowed = True

        split_id: uuid.UUID = ...
        decisions: List[DecisionModel] = []

    @classmethod
    def get_model_cls(cls) -> Type[BaseModel]:
        return cls.SingleInstancesModel

    def __init__(self, *args, split_id, tracked_by, **kwargs):
        super().__init__(*args, split_id=split_id, tracked_by=tracked_by, **kwargs)

    def add_instance(self, instance, prediction, probability):
        pass


class SingleInstanceILF(InjectionLogger):
    """
    Function logging individual decisions
    """
    name = "SingleInstanceILF"
    uri = "https://www.padre-lab.eu/single-instance-logger"

    class SingleInstanceOuptut(OutputModel):
        is_a: HttpUrl = "https://www.padre-lab.eu/onto/SingleInstanceILF-Output"

        individual_decisions: SingleInstanceTO.get_model_cls() = None

        class Config:
            orm_mode = True

    @classmethod
    def output_schema_class(cls) -> Type[OutputModel]:
        return cls.SingleInstanceOuptut

    def __post__(self, ctx, *args, _logger_call, _pypads_pre_return, _pypads_result, _logger_output, _args, _kwargs,
                 **kwargs):
        """
        :param ctx:
        :param args:
        :param _pypads_result:
        :param kwargs:
        :return:
        """
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()
        _pypads_env = _logger_call.logging_env

        preds = _pypads_result
        if pads.cache.run_exists("predictions"):
            preds = pads.cache.run_pop("predictions")

        # check if there is info about decision scores
        probabilities = None
        if pads.cache.run_exists("probabilities"):
            probabilities = pads.cache.run_pop("probabilities")

        # check if there exists information about the current split
        num = 0
        split_info = None
        if pads.cache.run_exists("current_split"):
            num = pads.cache.run_get("current_split")
        if pads.cache.run_exists(num):
            split_info = pads.cache.run_get(num).get("split_info", None)

        # depending on available info log the predictions
        if split_info is None:
            logger.warning("No split information were found in the cache of the current run, "
                           "individual decision tracking might be missing Truth values, try to decorate you splitter!")
            pads.cache.run_add(num,
                               {'predictions': {str(i): {'predicted': preds[i]} for i in range(len(preds))}})
            if probabilities is not None:
                for i in pads.cache.run_get(num).get('predictions').keys():
                    pads.cache.run_get(num).get('predictions').get(str(i)).update(
                        {'probabilities': probabilities[int(i)]})
        else:
            try:
                # for i, sample in enumerate(split_info.get('test')):
                #     pads.cache.run_get(num).get('predictions').get(str(sample)).update({'predicted': preds[i]})
                pads.cache.run_add(num,
                                   {'predictions': {str(sample): {'predicted': preds[i]} for i, sample in
                                                    enumerate(split_info.get('test'))}})

                if probabilities is not None:
                    for i, sample in enumerate(split_info.get('test')):
                        pads.cache.run_get(num).get('predictions').get(str(sample)).update(
                            {'probabilities': probabilities[i]})
            except Exception as e:
                logger.warning("Could not log predictions due to this error '%s'" % str(e))
        if pads.cache.run_exists("targets"):
            try:
                targets = pads.cache.run_get("targets")
                if isinstance(targets, Iterable):
                    for i in pads.cache.run_get(num).get('predictions').keys():
                        pads.cache.run_get(num).get('predictions').get(str(i)).update(
                            {'truth': targets[int(i)]})
            except Exception as e:
                logger.warning("Could not add the truth values due to this error '%s'" % str(e))

        name = os.path.join(_pypads_env.call.to_folder(),
                            "decisions",
                            str(id(_pypads_env.callback)))
        pads.api.log_mem_artifact(name, pads.cache.run_get(num))


class Decisions_sklearn(SingleInstanceILF):
    """
    Function getting the prediction scores from sklearn estimators
    """

    supported_libraries = {LibSelector(name="sklearn", constraint="*", specificity=1)}

    def __pre__(self, ctx, *args,
                _logger_call, _logger_output, _args, _kwargs, **kwargs):
        """

        :param ctx:
        :param args:
        :param kwargs:
        :return:
        """
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()

        # check if the estimator computes decision scores
        probabilities = None
        predict_proba = None
        if hasattr(ctx, "predict_proba"):
            # TODO find a cleaner way to invoke the original predict_proba in case it is wrapped
            predict_proba = ctx.predict_proba
            if _logger_call.original_call.call_id.context.has_original(predict_proba):
                predict_proba = _logger_call.original_call.call_id.context.original(predict_proba)
        elif hasattr(ctx, "_predict_proba"):
            predict_proba = ctx._predict_proba
            if _logger_call.original_call.call_id.context.has_original(predict_proba):
                _logger_call.original_call.call_id.context.original(predict_proba)
        if hasattr(predict_proba, "__wrapped__"):
            predict_proba = predict_proba.__wrapped__
        try:
            probabilities = predict_proba(*_args, **_kwargs)
        except Exception as e:
            if isinstance(e, TypeError):
                try:
                    predict_proba = predict_proba.__get__(ctx)
                    probabilities = predict_proba(*_args, **_kwargs)
                except Exception as ee:
                    logger.warning("Couldn't compute probabilities because %s" % str(ee))
            else:
                logger.warning("Couldn't compute probabilities because %s" % str(e))
        finally:
            pads.cache.run_add("probabilities", probabilities)


class Decisions_keras(SingleInstanceILF):
    """
    Function getting the prediction scores from keras models
    """

    supported_libraries = {LibSelector(name="keras", constraint = "*", specificity=1)}

    def __pre__(self, ctx, *args,
                _logger_call, _logger_output, _args, _kwargs, **kwargs):
        """

        :param ctx:
        :param args:
        :param kwargs:
        :return:
        """
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()

        probabilities = None
        try:
            probabilities = ctx.predict(*_args, **_kwargs)
        except Exception as e:
            logger.warning("Couldn't compute probabilities because %s" % str(e))

        pads.cache.run_add("probabilities", probabilities)


class Decisions_torch(SingleInstanceILF):
    """
    Function getting the prediction scores from torch models
    """

    supported_libraries = {LibSelector(name="torch", constraint="*", specificity=1)}

    def __post__(self, ctx, *args, _logger_call, _pypads_pre_return, _pypads_result, _logger_output, _args, _kwargs,
                 **kwargs):
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()

        if hasattr(ctx, "training") and ctx.training:
            pass
        else:
            pads.cache.run_add("probabilities", _pypads_result.data.numpy())
            pads.cache.run_add("predictions", _pypads_result.argmax(dim=1).data.numpy())

            return super().__post__(ctx, *args, _logger_call=_logger_call, _pypads_pre_return=_pypads_pre_return,
                                    _pypads_result=_pypads_result, _logger_output=_logger_output, _args=_args,
                                    _kwargs=_kwargs, **kwargs)
