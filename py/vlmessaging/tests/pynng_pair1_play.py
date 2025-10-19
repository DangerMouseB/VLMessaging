# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import pynng, asyncio

# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging.utils import with_async_init


# https://github.com/nanomsg/nng
# https://nng.nanomsg.org/ref/
# https://github.com/codypiersall/pynng



@with_async_init
class Router:
    __slots__ = ('_sock', 'addr')

    async def __init__(self, addr):
        self.addr = addr
        self._sock = pynng.Pair1(polyamorous=True)
        self._sock.add_pre_pipe_connect_cb(self.pre_connect_cb)
        self._sock.add_post_pipe_remove_cb(self.post_remove_cb)
        self._sock.listen(addr)
        asyncio.create_task(self._route_eternally())

    def pre_connect_cb(self, pipe):
        print(f'{pipe.id}("{pipe.remote_address}") joining')

    def post_remove_cb(self, pipe):
        try:
            try:
                addr = str(pipe.remote_address)
            except Exception as ex:
                # OPEN: we need to store the mapping ourselves
                addr = 'unknown'
            print(f'id: {pipe.id}("{addr}") leaving')
        except Exception as ex:
            print(type(pipe), dir(pipe))
            print(f'Error: {repr(ex)}')

    async def _route_eternally(self):
        while True:
            pynngMsg = await self._sock.arecv_msg()
            source_addr = str(pynngMsg.pipe.remote_address)
            raw = pynngMsg.bytes
            content = raw.decode()
            print(f'From: {pynngMsg.pipe.id}("source_addr") got: {content}')
            for pipe in self._sock.pipes:
                await pipe.asend(raw)      # OPEN: why await here?
            await asyncio.sleep(0.1)
            if content == 'STOP':
                self._sock.close()
                self._sock = Missing
                break

    def __del__(self):
        if self._sock is not Missing:
            self._sock.close()
            self._sock = Missing



@with_async_init
class Agent:

    __slots__ = ('_sock', 'addr')

    async def __init__(self, addr):
        self.addr = addr
        self._sock = pynng.Pair1(polyamorous=True)
        self._sock.dial(addr)
        asyncio.create_task(self._recv_eternally())

    def __del__(self):
        if self._sock is not Missing:
            self._sock.close()
            self._sock = Missing

    async def _recv_eternally(self):
        while True:
            msg = await self._sock.arecv_msg()
            source_addr = str(msg.pipe.remote_address)
            content = msg.bytes.decode()
            print(f'From: {msg.pipe.id}("{source_addr}") got: {content} (AGENT)')



async def main(addr):
    router = await Router(addr)
    agent = await Agent(addr)
    with pynng.Pair1(polyamorous=True) as sock:
        sock.dial(addr)
        await asyncio.sleep(0.3)
        for i in range(1,4):
            await sock.asend(f'Hello {i}'.encode())
            await asyncio.sleep(0.3)
        await sock.asend('STOP'.encode())
        await asyncio.sleep(1)


if __name__ == "__main__":
    res = asyncio.run(main('ipc:///tmp/agent'))
    res = asyncio.run(main('tcp://127.0.0.1:13134'))
