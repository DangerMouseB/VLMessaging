# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import asyncio, time

# 3rd party imports
from pynng import Message

# local imports
from vlmessaging._utils.sentinels import Void


# Async concepts - Task
# Async objects - OneOffEvent (function), EventSource (Timer, Queue, Socket)
# Async operations - await single, await multiple (until), inBackgroundDo / addToLoop / do / schedule / add


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


def monotonicTimeMs():
    # we can be in control of time for testing etc
    try:
        return asyncio.get_running_loop().time() * 1000
    except RuntimeError:
        return time.monotonic() * 1000

