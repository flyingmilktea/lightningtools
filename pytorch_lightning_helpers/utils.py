#!/usr/bin/env python3
from operator import itemgetter
from omegaconf import OmegaConf
from loguru import logger
import torch
from torch.optim.lr_scheduler import _LRScheduler
from icecream import ic
from collections.abc import Iterable
from functools import partial

from torch.optim.lr_scheduler import _LRScheduler


def compose(*funcs):
    def f(**kwargs):
        ret = {}
        for f in funcs:
            ret |= f(**{**kwargs, **ret})
        return ret

    return f


def build_loss(loss_fn, scale=1, start_step=0):
    def loss(step=None, start_step=start_step, **kwargs):
        if isinstance(start_step, Iterable):
            start_step = max(start_step)
        if step is not None and step < start_step:
            return {}
        return {k: v * scale for (k, v) in loss_fn(**kwargs).items()}

    return loss


class NoamLR(_LRScheduler):
    """
    Implements the Noam Learning rate schedule. This corresponds to increasing the learning rate
    linearly for the first ``warmup_steps`` training steps, and decreasing it thereafter proportionally
    to the inverse square root of the step number, scaled by the inverse square root of the
    dimensionality of the model. Time will tell if this is just madness or it's actually important.
    Parameters
    ----------
    warmup_steps: ``int``, required.
        The number of steps to linearly increase the learning rate.
    """

    def __init__(self, optimizer, warmup_steps):
        self.warmup_steps = warmup_steps
        super().__init__(optimizer)

    def get_lr(self):
        last_epoch = max(1, self.last_epoch)
        scale = self.warmup_steps**0.5 * min(
            last_epoch ** (-0.5), last_epoch * self.warmup_steps ** (-1.5)
        )
        return [base_lr * scale for base_lr in self.base_lrs]

    def state_dict(self):
        # Override so that we can change the lr on resume
        return {
            key: value
            for key, value in self.__dict__.items()
            if key not in ["base_lrs"]
        }

    def load_state_dict(self, state_dict):
        # Override so that we can change the lr on resume
        self.__dict__.update({k: v for k, v in state_dict.items() if k != "base_lrs"})

def build_module_pipeline(model_cfg):
    def build_pipeline_item(module, fn, start_step=0, cond=True):
        module_fn = fn_cache[module][fn]
        def pipeline_item(module_fn, start_step, cond, **kwargs):
            if isinstance(start_step, Iterable):
                start_step = max(start_step)
            if kwargs.get('step', 0) < start_step:
                return kwargs
            if not cond:
                return kwargs
            return module_fn(**kwargs)
        return partial(pipeline_item, module_fn, start_step, cond)


    module_cache = torch.nn.ModuleDict()
    fn_cache = {}
    for k, v in model_cfg.modules.items():
        module_cache.update(v['modules'])
        fn_cache[k] = v['methods']

    pipeline = []
    for pipeline_cfg_item in model_cfg.pipeline:
        pipeline.append(build_pipeline_item(**pipeline_cfg_item))

    pipeline = compose(*pipeline)

    param_group = {}
    if hasattr(model_cfg, 'param_group'):
        for k, v in model_cfg.param_group.items():
            param_group[k] = torch.nn.ModuleDict({name: module_cache[name] for
                                                  name in v}).parameters()
        modules_in_param_group = set(sum(OmegaConf.to_container(model_cfg.param_group).values(), []))
        modules_without_param_group = set(module_cache.keys()) - modules_in_param_group
        for name in modules_without_param_group:
            logger.warning(f'{name} does not belong to any param groups.')
    else:
        param_group['default'] = module_cache.parameters()

    return module_cache, pipeline, param_group


