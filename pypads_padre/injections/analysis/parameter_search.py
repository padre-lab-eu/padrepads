from pypads.app.injections.base_logger import LoggerCall
from pypads.app.injections.injection import InjectionLogger
from pypads.app.env import InjectionLoggerEnv
import json

from pypads.utils.logging_util import try_write_artifact, WriteFormats
from pypads.utils.util import is_package_available


class ParameterSearch(InjectionLogger):

    _dependencies = {"sklearn"}

    def __pre__(self, ctx, *args, _pypads_write_format=None, _logger_call: LoggerCall, _logger_output, _args, _kwargs,
                **kwargs):
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()
        pads.cache.add("parameter_search", ctx)
        # TODO save parameter grid used for the search

    def __post__(self, ctx, *args, _logger_call, _pypads_pre_return,
                 _pypads_result, _logger_output, _args, _kwargs,
                 **kwargs):
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()

        pads.cache.pop("parameter_search")
        from sklearn.model_selection._search import BaseSearchCV
        if isinstance(ctx, BaseSearchCV):
            # TODO Write general information we can extract from base search
            from sklearn.model_selection import GridSearchCV
            if isinstance(ctx, GridSearchCV):
                # TODO Write information we can extract from GridSearchCV
                serialized_dict = self.traverse_dict(ctx.cv_results_)

                name = 'GridSearchCV'
                try_write_artifact(name, json.dumps(serialized_dict),
                                   write_format=WriteFormats.text)

    def traverse_dict(self, input_dict):
        """
        Function to traverse a dictionary and convert the values to JSON serializable format
        :param input_dict:
        :return: dict
        """

        serialized_dict = dict()
        for key, value in input_dict.items():

            if hasattr(value, 'tolist'):
                serialized_dict[key] = value.tolist()

            elif isinstance(value, list):
                serialized_dict[key] = value

            elif isinstance(value, dict):
                serialized_dict[key] = self.traverse_dict(value)

            else:
                serialized_dict[key] = str(value)

        return serialized_dict


class ParameterSearchExecutor(InjectionLogger):

    def __pre__(self, ctx, *args, **kwargs):
        pass

    def __post__(self, ctx, *args, **kwargs):
        pass

    def call_wrapped(self,ctx, *args, _pypads_env: InjectionLoggerEnv, _args, _kwargs):
        from pypads.app.pypads import get_current_pads
        pads = get_current_pads()

        if pads.cache.exists("parameter_search"):
            with pads.api.intermediate_run(experiment_id=pads.api.active_run().info.experiment_id):
                out = _pypads_env.callback(*_args, **_kwargs)
            return out
        else:
            return _pypads_env.callback(*_args, **_kwargs)
