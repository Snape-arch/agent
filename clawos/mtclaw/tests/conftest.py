import asyncio
import inspect

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: mark test as asyncio")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function):
    if "asyncio" not in pyfuncitem.keywords:
        return None
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None
    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in inspect.signature(testfunction).parameters
    }
    asyncio.run(testfunction(**kwargs))
    return True
