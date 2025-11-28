# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

import asyncio, time
from pynng import Message

Void = None

def with_async_init(cls):
    # baseed on https://gist.github.com/AnoRebel/433110fcf589dba6f26ea6cf8c3320a4 - AnoRebel/asyncinit.py

    # override __new__ with replacement_new, which, instead of directly returning the new instance, returns a
    # coroutine, __async_init__, that first does `new_inst.__init__(*args, **kwargs)` before returning the newly
    # created instance. Python will still call __init__ after __new__, but since __init__ is a coroutine, it won't
    # do anything.

    orig_new = cls.__new__

    async def __async_init__(new_inst, *args, **kwargs):
        await new_inst.__init__(*args, **kwargs)
        return new_inst

    def replacement_new(cls, *args, **kwargs):
        try:
            new_inst = orig_new(cls, *args, **kwargs)
        except TypeError:
            #  handle case where __new__ takes no arguments - see override_new_play.py for more details
            new_inst = orig_new(cls)
        return __async_init__(new_inst, *args, **kwargs)

    cls.__new__ = replacement_new
    return cls


# Async concepts - Task
# Async objects - OneOffEvent (function), EventSource (Timer, Queue, Socket)
# Async operations - await single, await multiple (until), inBackgroundDo / addToLoop / do / schedule / add


tDictKeys = type({}.keys())
tDictValues = type({}.values())

async def until(*awaitables, return_when=asyncio.ALL_COMPLETED, timeout=None):
    """Wraps any Event in awaitables in a Task then returns await asyncio.wait(...)."""
    things = awaitables
    if len(awaitables) == 1:
        if isinstance(awaitables[0], (list, tuple, set)):
            things = awaitables[0]
        elif isinstance(awaitables[0], (tDictKeys, tDictValues)):
            things = list(awaitables[0])
    things = [taskOnEvent(thing) if isinstance(thing, asyncio.Event) else thing for thing in things]
    secs = timeout / 1000.0 if timeout else None
    if awaitables:
        return await asyncio.wait(things, timeout=secs, return_when=return_when)
    elif timeout is not None:
        await asyncio.sleep(timeout / 1000.0)     # even if timeout == 0 yield at least once
        return [], []
    else:
        return [], []

def startEventLoopWith(fn):
    asyncio.run(fn())

def taskOnEvent(ev):
    async def _(ev):
        return await ev.wait()
    return asyncio.create_task(ev.wait())
    # return asyncio.create_task(_(ev))

def Queue():
    return asyncio.Queue()

def pushBack(q, x) -> Void:
    q.put_nowait(x)

def coPopFront(q):
    return asyncio.create_task(q.get())

def corecv(s):
    return asyncio.create_task(s.arecv_msg())

def cosend(p, bytes):
    return asyncio.create_task(p.asend(bytes))

def dial(s, addr, *, block):
    return s.dial(addr, block=block)

def send(p, bytes, *, block) -> Void:
    assert not isinstance(bytes, str)
    p.socket.send_msg(Message(bytes, p), block)

def pipeConnectionType(pipe):
    try:
        pipe.listener
        return 'incoming'
    except TypeError:
        pipe.dialer
        return 'outgoing'

class Timer:
    """Monotonic timer in milliseconds.

    Usage:
        t = timer(10000)
        while not t:
            ...
    """

    __slots__ = ('_deadline')

    def __init__(self, timeoutInMilliseconds:float):
        self._deadline = time.monotonic() + timeoutInMilliseconds / 1000.0

    def __bool__(self):
        # returns True if timer has expired
        return time.monotonic() >= self._deadline

    def __repr__(self) -> str:
        return f"<timer expired={not not self}>"


class CountFailures(object):
    def __init__(self, counter):
        self.counter = counter
    def __enter__(self):
        return None
    def __exit__(self, type, value, traceback):
        if value is not None: next(self.counter)
        return True


def monotonicTimeMs():
    # we can be in control of time for testing etc
    try:
        return asyncio.get_running_loop().time() * 1000
    except RuntimeError:
        return time.monotonic() * 1000

