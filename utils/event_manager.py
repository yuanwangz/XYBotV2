import asyncio
import copy
from typing import Callable, Dict, List, Set
from collections import defaultdict
from loguru import logger


class EventManager:
    _handlers: Dict[str, List[tuple[Callable, object]]] = {}

    @classmethod
    def bind_instance(cls, instance: object):
        """将实例绑定到对应的事件处理函数"""
        for method_name in dir(instance):
            method = getattr(instance, method_name)
            if hasattr(method, '_event_type'):
                event_type = getattr(method, '_event_type')
                if event_type not in cls._handlers:
                    cls._handlers[event_type] = []
                cls._handlers[event_type].append((method, instance))
        
        # 按优先级排序处理器
        for event_type in cls._handlers:
            cls._handlers[event_type].sort(key=lambda x: getattr(x[1], 'priority', 10))

    @classmethod
    async def emit(cls, event_type: str, *args, **kwargs) -> None:
        """触发事件"""
        if event_type not in cls._handlers:
            return

        api_client, message = args
        
        # 按互斥组分组处理器
        mutex_groups = defaultdict(list)
        for handler, instance in cls._handlers[event_type]:
            group = getattr(instance, 'mutex_group', None)
            mutex_groups[group].append((handler, instance))
        
        # 记录已处理的互斥组
        handled_groups: Set[str] = set()
        
        # 创建所有可并行执行的任务
        tasks = []
        for group, handlers in mutex_groups.items():
            if group in handled_groups:
                continue
                
            async def process_group(group_handlers):
                for handler, instance in group_handlers:
                    handler_args = (api_client, copy.deepcopy(message))
                    new_kwargs = {k: copy.deepcopy(v) for k, v in kwargs.items()}
                    try:
                        if await handler(*handler_args, **new_kwargs):
                            return True
                    except Exception as e:
                        logger.error(f"处理器执行错误: {e}")
                return False
            
            task = asyncio.create_task(process_group(handlers))
            tasks.append((group, task))
            
            if group is not None:
                handled_groups.add(group)
        
        # 等待所有任务完成
        for group, task in tasks:
            try:
                await task
            except Exception as e:
                logger.error(f"任务执行错误: {e}")

    @classmethod
    def unbind_instance(cls, instance: object):
        """解绑实例的所有事件处理函数"""
        for event_type in cls._handlers:
            cls._handlers[event_type] = [
                (handler, inst) for handler, inst in cls._handlers[event_type]
                if inst is not instance
            ]
